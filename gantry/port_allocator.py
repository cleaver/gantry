import socket
from pathlib import Path
from typing import Dict, List, TypedDict

import yaml

from .registry import Project, Registry


class PortConflictError(Exception):
    """Raised when a port conflict is detected."""
    def __init__(self, conflicts: List[Dict]):
        self.conflicts = conflicts
        super().__init__(f"Port conflict(s) detected: {conflicts}")


class Conflict(TypedDict):
    port: int
    conflicting_project: str
    service: str


HTTP_PORT_RANGE = range(5000, 6000)


class PortAllocator:
    def __init__(self, registry: Registry):
        self._registry = registry

    def is_port_available(self, port: int) -> bool:
        """Check if a port is available on the system."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                # Set a timeout to avoid long waits
                s.settimeout(0.1)
                # Try to bind to the port on localhost
                s.bind(("127.0.0.1", port))
                return True
            except (socket.error, OverflowError):
                return False

    def allocate_port(self) -> int:
        """Find and return the first available port in the defined range."""
        projects = self._registry.list_projects()
        allocated_ports = set()
        for project in projects:
            allocated_ports.update(project.exposed_ports)

        for port in HTTP_PORT_RANGE:
            if port not in allocated_ports and self.is_port_available(port):
                return port

        raise RuntimeError("No available ports in the specified range.")

    def get_project_port(self, hostname: str) -> int | None:
        """Get the main HTTP port for a project."""
        project = self._registry.get_project(hostname)
        return project.port if project else None

    def detect_service_ports(self, compose_file_path: Path) -> Dict[str, int]:
        """
        Parse a docker-compose.yml file and extract exposed host ports.
        """
        if not compose_file_path.is_file():
            return {}

        with open(compose_file_path, "r", encoding="utf-8") as f:
            try:
                compose_data = yaml.safe_load(f)
            except yaml.YAMLError:
                return {}  # Or raise a specific error

        if not compose_data or "services" not in compose_data:
            return {}

        service_ports = {}
        for service_name, service_config in compose_data.get("services", {}).items():
            if not service_config:
                continue
            ports = service_config.get("ports")
            if not ports:
                continue

            for port_mapping in ports:
                try:
                    # Short syntax "HOST:CONTAINER"
                    host_port_str = str(port_mapping).split(":")[0]
                    if host_port_str.isdigit():
                        host_port = int(host_port_str)
                        # Take the first valid port mapping for the service
                        if service_name not in service_ports:
                            service_ports[service_name] = host_port
                except (ValueError, IndexError):
                    # Long syntax would need more complex parsing, skipping for now
                    # as short syntax is most common for simple host exposure.
                    # Example:
                    # ports:
                    #  - target: 80
                    #    published: 8080
                    #    protocol: tcp
                    #    mode: host
                    if isinstance(port_mapping, dict) and 'published' in port_mapping:
                        if str(port_mapping['published']).isdigit():
                             host_port = int(port_mapping['published'])
                             if service_name not in service_ports:
                                 service_ports[service_name] = host_port

        return service_ports

    def get_running_project_ports(self) -> Dict[str, List[int]]:
        """Get a map of running projects to their exposed ports."""
        running_projects = self._registry.get_running_projects()
        return {p.hostname: p.exposed_ports for p in running_projects}

    def check_port_conflicts(self, hostname: str, ports_to_check: List[int]) -> List[Conflict]:
        """
        Check if any of the given ports conflict with other running projects.
        """
        running_ports = self.get_running_project_ports()
        conflicts: List[Conflict] = []

        for port in ports_to_check:
            for other_hostname, other_ports in running_ports.items():
                if other_hostname == hostname:
                    continue  # Don't check against self

                if port in other_ports:
                    project = self._registry.get_project(other_hostname)
                    service_name = "http" # Default
                    if project:
                        for s_name, s_port in project.service_ports.items():
                            if s_port == port:
                                service_name = s_name
                                break

                    conflicts.append({
                        "port": port,
                        "conflicting_project": other_hostname,
                        "service": service_name
                    })
        return conflicts

    def validate_startup_ports(self, hostname: str):
        """
        Validate that a project's ports do not conflict with any other
        currently running projects.
        """
        project = self._registry.get_project(hostname)
        if not project:
            raise ValueError(f"Project '{hostname}' not found.")

        conflicts = self.check_port_conflicts(hostname, project.exposed_ports)
        if conflicts:
            raise PortConflictError(conflicts)

    def get_port_usage(self) -> Dict[int, List[str]]:
        """Get a report of which projects are using which ports."""
        projects = self._registry.list_projects()
        usage: Dict[int, List[str]] = {}
        for project in projects:
            for port in project.exposed_ports:
                if port not in usage:
                    usage[port] = []
                usage[port].append(project.hostname)
        return usage
