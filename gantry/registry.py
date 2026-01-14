import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


# --- Data Models ---

class Project(BaseModel):
    hostname: str
    path: Path
    port: Optional[int] = None
    services: List[str] = Field(default_factory=list)
    service_ports: Dict[str, int] = Field(default_factory=dict)
    exposed_ports: List[int] = Field(default_factory=list)
    docker_compose: bool = False
    working_directory: Path
    environment_vars: Dict[str, str] = Field(default_factory=dict)
    registered_at: datetime
    last_started: Optional[datetime] = None
    last_updated: datetime
    status: Literal["running", "stopped", "error"] = "stopped"
    last_status_change: Optional[datetime] = None


class RegistryData(BaseModel):
    projects: Dict[str, Project] = Field(default_factory=dict)


# --- Registry ---

GANTRY_HOME = Path.home() / ".gantry"
PROJECTS_JSON = GANTRY_HOME / "projects.json"


class Registry:
    def __init__(self):
        GANTRY_HOME.mkdir(exist_ok=True)
        (GANTRY_HOME / "projects").mkdir(exist_ok=True)

    def _load_registry(self) -> RegistryData:
        if not PROJECTS_JSON.exists():
            return RegistryData()
        try:
            with open(PROJECTS_JSON, "r", encoding="utf-8") as f:
                data = json.loads(f.read())
                # Pydantic will handle path conversion and other type coercions
                return RegistryData.model_validate(data)
        except (json.JSONDecodeError, FileNotFoundError):
            # Handle empty or corrupted file
            return RegistryData()

    def _save_registry(self, data: RegistryData):
        # Atomic write using a temporary file
        fd, tmp_path_str = tempfile.mkstemp(dir=GANTRY_HOME, text=True)
        tmp_path = Path(tmp_path_str)
        try:
            with os.fdopen(fd, "w") as tmp_file:
                # Use pydantic's model_dump_json for serialization
                tmp_file.write(data.model_dump_json(indent=2))
            # `os.rename` is an atomic operation on most POSIX systems
            os.rename(tmp_path, PROJECTS_JSON)
        except Exception:
            # Cleanup in case of error
            tmp_path.unlink(missing_ok=True)
            raise

    def register_project(
        self,
        hostname: str,
        path: Path,
        port: Optional[int] = None,
    ) -> Project:
        data = self._load_registry()
        if hostname in data.projects:
            raise ValueError(f"Project '{hostname}' is already registered.")

        now = datetime.now(timezone.utc)
        project = Project(
            hostname=hostname,
            path=path.resolve(),
            port=port,
            working_directory=path.resolve(),
            registered_at=now,
            last_updated=now,
        )

        data.projects[hostname] = project
        self._save_registry(data)
        
        project_dir = GANTRY_HOME / "projects" / hostname
        project_dir.mkdir(exist_ok=True)
        
        return project

    def get_project(self, hostname: str) -> Optional[Project]:
        data = self._load_registry()
        return data.projects.get(hostname)

    def list_projects(self) -> List[Project]:
        data = self._load_registry()
        return list(data.projects.values())

    def unregister_project(self, hostname: str):
        data = self._load_registry()
        if hostname not in data.projects:
            raise ValueError(f"Project '{hostname}' not found.")
        
        del data.projects[hostname]
        self._save_registry(data)

        project_dir = GANTRY_HOME / "projects" / hostname
        if project_dir.is_dir():
            # Basic cleanup of per-project directory
            import shutil
            shutil.rmtree(project_dir)

    def update_project_status(self, hostname: str, status: Literal["running", "stopped", "error"]):
        self.update_project_metadata(hostname, status=status)

    def get_running_projects(self) -> List[Project]:
        data = self._load_registry()
        return [p for p in data.projects.values() if p.status == "running"]

    def update_service_ports(self, hostname: str, service_ports: Dict[str, int], exposed_ports: List[int]):
        self.update_project_metadata(
            hostname,
            service_ports=service_ports,
            exposed_ports=exposed_ports,
        )

    def update_project_metadata(self, hostname: str, **updates: Any):
        data = self._load_registry()
        if hostname not in data.projects:
            raise ValueError(f"Project '{hostname}' not found.")

        project = data.projects[hostname]
        
        # Create a dictionary from the existing model to apply updates
        updated_data = project.model_dump()
        updated_data.update(updates)

        # If status is being updated and it's different from current, set last_status_change
        if "status" in updates and updates["status"] != project.status:
            updated_data["last_status_change"] = datetime.now(timezone.utc)

        # Always set the last_updated timestamp on any modification
        updated_data["last_updated"] = datetime.now(timezone.utc)

        # Create a new Project instance from the updated data to run validation
        new_project = Project.model_validate(updated_data)

        data.projects[hostname] = new_project
        self._save_registry(data)
