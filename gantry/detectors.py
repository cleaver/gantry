from pathlib import Path
from typing import Dict, List, Literal, Optional, TypedDict

import yaml

from .registry import Project

ProjectType = Literal["docker-compose", "dockerfile", "native"]


class ProjectChanges(TypedDict, total=False):
    services_added: List[str]
    services_removed: List[str]
    ports_changed: Dict[str, int]  # service -> new_port
    ports_added: Dict[str, int]  # service -> port
    ports_removed: List[str]  # service name
    docker_compose_removed: bool


def detect_project_type(path: Path) -> ProjectType:
    """Detects the type of project based on the files present."""
    if (path / "docker-compose.yml").exists() or (
        path / "docker-compose.yaml"
    ).exists():
        return "docker-compose"
    if (path / "Dockerfile").exists():
        return "dockerfile"
    return "native"


def _get_compose_file(path: Path) -> Optional[Path]:
    """Finds the docker-compose file in a directory."""
    if (compose_file := path / "docker-compose.yml").exists():
        return compose_file
    if (compose_file := path / "docker-compose.yaml").exists():
        return compose_file
    return None


def detect_services(compose_file_path: Path) -> List[str]:
    """Detects the service names from a docker-compose file."""
    if not compose_file_path.is_file():
        return []

    with open(compose_file_path, "r", encoding="utf-8") as f:
        try:
            compose_data = yaml.safe_load(f)
            if (
                compose_data
                and "services" in compose_data
                and isinstance(compose_data["services"], dict)
            ):
                return list(compose_data["services"].keys())
        except yaml.YAMLError:
            return []
    return []


def detect_service_ports(compose_file_path: Path) -> Dict[str, int]:
    """
    Parse a docker-compose.yml file and extract exposed host ports.
    """
    if not compose_file_path.is_file():
        return {}

    with open(compose_file_path, "r", encoding="utf-8") as f:
        try:
            compose_data = yaml.safe_load(f)
        except yaml.YAMLError:
            return {}

    if not compose_data or "services" not in compose_data:
        return {}

    service_ports: Dict[str, int] = {}
    for service_name, service_config in compose_data.get("services", {}).items():
        if not service_config or "ports" not in service_config:
            continue

        for port_mapping in service_config["ports"]:
            # Check for long syntax first (dict with 'published' field)
            if isinstance(port_mapping, dict) and "published" in port_mapping:
                if str(port_mapping["published"]).isdigit():
                    host_port = int(port_mapping["published"])
                    if service_name not in service_ports:
                        service_ports[service_name] = host_port
                        break  # Use the first port found for a service
            else:
                # Short syntax "HOST:CONTAINER"
                try:
                    host_port_str = str(port_mapping).split(":")[0]
                    if host_port_str.isdigit():
                        host_port = int(host_port_str)
                        if service_name not in service_ports:
                            service_ports[service_name] = host_port
                            break  # Use the first port found for a service
                except (ValueError, IndexError):
                    pass
    return service_ports


def rescan_project(path: Path, existing_metadata: Project) -> ProjectChanges:
    """
    Re-scans a project directory and returns a diff of changes compared to
    existing metadata.
    """
    changes: ProjectChanges = {}
    if not path.is_dir():
        # Edge case: project directory was removed
        changes["docker_compose_removed"] = True
        changes["services_removed"] = existing_metadata.services
        changes["ports_removed"] = list(existing_metadata.service_ports.keys())
        return changes

    compose_file = _get_compose_file(path)
    if not compose_file:
        if existing_metadata.docker_compose:
            changes["docker_compose_removed"] = True
            changes["services_removed"] = existing_metadata.services
            changes["ports_removed"] = list(existing_metadata.service_ports.keys())
        return changes

    # --- Compare Services ---
    detected_services = detect_services(compose_file)
    existing_services = set(existing_metadata.services)
    new_services = set(detected_services)

    if services_added := sorted(list(new_services - existing_services)):
        changes["services_added"] = services_added
    if services_removed := sorted(list(existing_services - new_services)):
        changes["services_removed"] = services_removed

    # --- Compare Ports ---
    detected_ports = detect_service_ports(compose_file)
    existing_ports = existing_metadata.service_ports

    ports_added = {s: p for s, p in detected_ports.items() if s not in existing_ports}
    if ports_added:
        changes["ports_added"] = ports_added

    ports_removed = [s for s in existing_ports if s not in detected_ports]
    if ports_removed:
        changes["ports_removed"] = sorted(ports_removed)

    ports_changed = {
        s: p
        for s, p in detected_ports.items()
        if s in existing_ports and p != existing_ports[s]
    }
    if ports_changed:
        changes["ports_changed"] = ports_changed

    return changes
