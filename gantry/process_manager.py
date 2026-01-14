"""Process management for Docker Compose projects."""
import json
import logging
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Literal, Optional
from urllib.error import URLError
from urllib.request import urlopen

import psutil

from .port_allocator import MIN_PORT, MAX_PORT, PortAllocator, PortConflictError
from .registry import GANTRY_HOME, Project, Registry


# --- Custom Exceptions ---

class ProcessManagerError(Exception):
    """Base exception for process manager errors."""
    pass


class ServiceAlreadyRunningError(ProcessManagerError):
    """Raised when trying to start an already running project."""
    pass


class ServiceNotRunningError(ProcessManagerError):
    """Raised when trying to stop a non-running project."""
    pass


class DockerComposeNotFoundError(ProcessManagerError):
    """Raised when docker-compose.yml is missing."""
    pass


class HealthCheckFailedError(ProcessManagerError):
    """Raised when health check fails after retries."""
    pass


# --- State Management ---

def _get_state_file_path(hostname: str) -> Path:
    """Get the path to the state.json file for a project."""
    return GANTRY_HOME / "projects" / hostname / "state.json"


def _load_state(hostname: str) -> Dict:
    """Load state from state.json file."""
    state_file = _get_state_file_path(hostname)
    if not state_file.exists():
        return {}
    
    try:
        with open(state_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return {}


def _save_state(hostname: str, state: Dict):
    """Save state to state.json file."""
    state_file = _get_state_file_path(hostname)
    state_file.parent.mkdir(parents=True, exist_ok=True)
    
    with open(state_file, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def _clear_state(hostname: str):
    """Clear state.json file."""
    state_file = _get_state_file_path(hostname)
    if state_file.exists():
        state_file.unlink()


# --- Process Manager ---

class ProcessManager:
    """Manages the lifecycle of Docker Compose projects."""
    
    def __init__(self, registry: Registry, port_allocator: PortAllocator):
        self._registry = registry
        self._port_allocator = port_allocator
        self._shutdown_timeout = 30  # seconds
    
    def _find_compose_file(self, project_path: Path) -> Optional[Path]:
        """Find docker-compose.yml or docker-compose.yaml in project path."""
        for filename in ["docker-compose.yml", "docker-compose.yaml"]:
            compose_file = project_path / filename
            if compose_file.exists():
                return compose_file
        return None
    
    def _get_docker_compose_pids(self, project_path: Path) -> List[int]:
        """Get PIDs of running Docker Compose services."""
        try:
            result = subprocess.run(
                ["docker", "compose", "ps", "--format", "json"],
                cwd=project_path,
                capture_output=True,
                text=True,
                check=True,
                timeout=10
            )
            
            pids = []
            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                try:
                    service_info = json.loads(line)
                    # Docker Compose ps format includes PID field
                    if "Pid" in service_info and service_info["Pid"]:
                        try:
                            pid = int(service_info["Pid"])
                            if pid > 0:
                                pids.append(pid)
                        except (ValueError, TypeError):
                            pass
                except json.JSONDecodeError:
                    continue
            
            return pids
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
            return []
    
    def _validate_pids(self, pids: List[int]) -> List[int]:
        """Validate that PIDs are still running."""
        valid_pids = []
        for pid in pids:
            try:
                if psutil.pid_exists(pid):
                    process = psutil.Process(pid)
                    if process.is_running():
                        valid_pids.append(pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return valid_pids
    
    def check_startup_conflicts(self, hostname: str) -> Optional[List[Dict]]:
        """
        Check for port conflicts before starting a project.
        Returns list of conflicts or None if no conflicts.
        """
        try:
            self._port_allocator.validate_startup_ports(hostname)
            return None
        except PortConflictError as e:
            return e.conflicts
    
    def get_status(self, hostname: str) -> Literal["running", "stopped", "error"]:
        """
        Get the current status of a project.
        Validates PIDs and Docker Compose services.
        """
        project = self._registry.get_project(hostname)
        if not project:
            raise ValueError(f"Project '{hostname}' not found.")
        
        # Check if docker-compose.yml exists
        compose_file = self._find_compose_file(project.path)
        if not compose_file:
            # No docker-compose, check registry status
            return project.status
        
        # Check Docker Compose services
        try:
            result = subprocess.run(
                ["docker", "compose", "ps", "--format", "json"],
                cwd=project.working_directory,
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode != 0:
                # Docker Compose command failed
                self._registry.update_project_status(hostname, "error")
                return "error"
            
            # Parse services
            services_running = False
            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                try:
                    service_info = json.loads(line)
                    state = service_info.get("State", "").lower()
                    if state in ["running", "up"]:
                        services_running = True
                        break
                except (json.JSONDecodeError, KeyError):
                    continue
            
            # Check PIDs from state file
            state = _load_state(hostname)
            pids = state.get("pids", [])
            valid_pids = self._validate_pids(pids) if pids else []
            
            # Determine status
            if services_running or valid_pids:
                if project.status != "running":
                    self._registry.update_project_status(hostname, "running")
                return "running"
            else:
                if project.status != "stopped":
                    self._registry.update_project_status(hostname, "stopped")
                return "stopped"
        
        except (subprocess.TimeoutExpired, FileNotFoundError):
            # Docker not available or timeout
            self._registry.update_project_status(hostname, "error")
            return "error"
    
    def start_project(
        self, hostname: str, force: bool = False, port: Optional[int] = None
    ):
        """
        Start a Docker Compose project.
        
        Args:
            hostname: Project hostname
            force: If True, proceed even with port conflicts (with warning)
            port: If provided, set as the main HTTP port for the project
        
        Raises:
            ServiceAlreadyRunningError: If project is already running
            PortConflictError: If port conflicts detected and force=False
            DockerComposeNotFoundError: If docker-compose.yml not found
            ValueError: If provided port is invalid
        """
        project = self._registry.get_project(hostname)
        if not project:
            raise ValueError(f"Project '{hostname}' not found.")

        if port is not None:
            if not (MIN_PORT <= port <= MAX_PORT):
                raise ValueError(
                    f"Port {port} is outside the allowed range ({MIN_PORT}-{MAX_PORT})."
                )
            if port != project.port:
                self._registry.update_project_metadata(hostname, port=port)
                project = self._registry.get_project(hostname)
        
        # Check if already running
        current_status = self.get_status(hostname)
        if current_status == "running":
            raise ServiceAlreadyRunningError(
                f"Project '{hostname}' is already running."
            )
        
        # Check for port conflicts
        conflicts = self.check_startup_conflicts(hostname)
        if conflicts:
            if not force:
                raise PortConflictError(conflicts)
            # Log warning but proceed
            logging.warning(
                f"Port conflicts detected for '{hostname}': {conflicts}. "
                "Proceeding with --force flag."
            )
        
        # Find docker-compose.yml
        compose_file = self._find_compose_file(project.path)
        if not compose_file:
            raise DockerComposeNotFoundError(
                f"No docker-compose.yml found in {project.path}"
            )
        
        # Start Docker Compose services
        try:
            # Prepare environment variables
            env = os.environ.copy()
            env.update(project.environment_vars)
            
            # Run docker compose up -d
            result = subprocess.run(
                ["docker", "compose", "up", "-d"],
                cwd=project.working_directory,
                env=env,
                capture_output=True,
                text=True,
                check=True,
                timeout=120  # 2 minute timeout for startup
            )
            
            # Wait a bit for services to start
            time.sleep(2)
            
            # Get PIDs
            pids = self._get_docker_compose_pids(project.working_directory)
            
            # Save state
            state = {
                "pids": pids,
                "started_at": datetime.now(timezone.utc).isoformat(),
            }
            _save_state(hostname, state)
            
            # Update registry
            self._registry.update_project_metadata(
                hostname,
                status="running",
                last_started=datetime.now(timezone.utc)
            )
            
        except subprocess.CalledProcessError as e:
            self._registry.update_project_status(hostname, "error")
            raise ProcessManagerError(
                f"Failed to start project '{hostname}': {e.stderr}"
            ) from e
        except subprocess.TimeoutExpired:
            self._registry.update_project_status(hostname, "error")
            raise ProcessManagerError(
                f"Timeout starting project '{hostname}'"
            )
    
    def stop_project(self, hostname: str):
        """
        Stop a Docker Compose project with graceful shutdown.
        
        Args:
            hostname: Project hostname
        
        Raises:
            ServiceNotRunningError: If project is not running
        """
        project = self._registry.get_project(hostname)
        if not project:
            raise ValueError(f"Project '{hostname}' not found.")
        
        # Check if already stopped
        current_status = self.get_status(hostname)
        if current_status == "stopped":
            return  # Already stopped, nothing to do
        
        # Read PIDs from state
        state = _load_state(hostname)
        pids = state.get("pids", [])
        valid_pids = self._validate_pids(pids) if pids else []
        
        # Try graceful shutdown via docker compose down first
        try:
            result = subprocess.run(
                ["docker", "compose", "down"],
                cwd=project.working_directory,
                capture_output=True,
                text=True,
                timeout=self._shutdown_timeout
            )
            
            # Wait a moment for processes to stop
            time.sleep(1)
            
            # Check if processes are still running
            remaining_pids = self._validate_pids(valid_pids)
            
            if remaining_pids:
                # Force kill remaining processes
                for pid in remaining_pids:
                    try:
                        process = psutil.Process(pid)
                        process.terminate()  # SIGTERM
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                
                # Wait for graceful termination
                time.sleep(2)
                
                # Force kill if still running
                for pid in remaining_pids:
                    try:
                        if psutil.pid_exists(pid):
                            process = psutil.Process(pid)
                            process.kill()  # SIGKILL
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
        
        except subprocess.TimeoutExpired:
            # Timeout on docker compose down, force kill
            for pid in valid_pids:
                try:
                    if psutil.pid_exists(pid):
                        process = psutil.Process(pid)
                        process.kill()  # SIGKILL
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        
        # Clear state
        _clear_state(hostname)
        
        # Update registry
        self._registry.update_project_status(hostname, "stopped")
    
    def restart_project(self, hostname: str):
        """
        Restart a Docker Compose project (stop then start).
        
        Args:
            hostname: Project hostname
        """
        self.stop_project(hostname)
        time.sleep(1)  # Brief pause between stop and start
        self.start_project(hostname)
    
    def health_check(self, hostname: str) -> bool:
        """
        Perform health check on project's HTTP endpoint.
        
        Args:
            hostname: Project hostname
        
        Returns:
            True if health check passes, False otherwise
        
        Raises:
            HealthCheckFailedError: If health check fails after retries
        """
        project = self._registry.get_project(hostname)
        if not project:
            raise ValueError(f"Project '{hostname}' not found.")
        
        if not project.port:
            return False
        
        url = f"http://localhost:{project.port}"
        max_retries = 3
        retry_delay = 1.0  # seconds
        
        for attempt in range(max_retries):
            try:
                with urlopen(url, timeout=5) as response:
                    status_code = response.getcode()
                    if 200 <= status_code < 300:
                        # Update last health check time
                        state = _load_state(hostname)
                        state["last_health_check"] = datetime.now(timezone.utc).isoformat()
                        _save_state(hostname, state)
                        return True
            except (URLError, OSError, ValueError) as e:
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    continue
                # Last attempt failed
                return False
        
        return False
    
    def get_logs(
        self,
        hostname: str,
        service: Optional[str] = None,
        follow: bool = False
    ) -> subprocess.Popen:
        """
        Get logs from Docker Compose services.
        
        Args:
            hostname: Project hostname
            service: Optional service name to filter logs
            follow: If True, follow logs (streaming)
        
        Returns:
            subprocess.Popen object for streaming logs
        
        Raises:
            ValueError: If project not found
        """
        project = self._registry.get_project(hostname)
        if not project:
            raise ValueError(f"Project '{hostname}' not found.")
        
        # Build command
        cmd = ["docker", "compose", "logs"]
        if follow:
            cmd.append("--follow")
        if service:
            cmd.append(service)
        
        # Start subprocess for streaming
        process = subprocess.Popen(
            cmd,
            cwd=project.working_directory,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1  # Line buffered
        )
        
        return process
