"""
Manages the generation of routing configurations for projects.

This module is responsible for interpreting a project's services and ports
to generate the appropriate routing rules for the reverse proxy. It also
includes logic for identifying special service types like databases or
mail servers, allowing for more intelligent routing in the future.
"""

from typing import Dict, List, Optional

from .registry import Project

# A mapping of common service name patterns to a canonical service type.
# This can be expanded to support more services and used to provide
# special handling (e.g., auto-instrumenting with Adminer for databases).
SERVICE_PATTERNS: Dict[str, str] = {
    "postgres": "database",
    "postgresql": "database",
    "mysql": "database",
    "mariadb": "database",
    "redis": "cache",
    "mailhog": "mail",
    "mailcatcher": "mail",
    "adminer": "db-admin",
}


def get_service_type(service_name: str) -> Optional[str]:
    """
    Identifies the type of a service based on its name.

    Args:
        service_name: The name of the service from docker-compose.

    Returns:
        The canonical service type (e.g., 'database') or None if not recognized.
    """
    for pattern, service_type in SERVICE_PATTERNS.items():
        if pattern in service_name.lower():
            return service_type
    return None


def generate_routes_for_project(project: Project) -> List[Dict[str, any]]:
    """
    Generates all reverse proxy routes for a given project.

    Args:
        project: The project model from the registry.

    Returns:
        A list of dictionaries, where each dictionary represents a route
        with 'domain' and 'port' keys.
    """
    routes: List[Dict[str, any]] = []

    # 1. Add the main route for the project's primary port
    if project.port:
        routes.append({"domain": f"{project.hostname}.test", "port": project.port})

    # 2. Add routes for all additional services
    for service_name, service_port in project.service_ports.items():
        # Skip if the service port is the same as the main project port,
        # as it's already covered.
        if service_port == project.port:
            continue

        domain = f"{service_name}.{project.hostname}.test"
        routes.append({"domain": domain, "port": service_port})

        # Future home for special service handling.
        # For example, if get_service_type(service_name) returns 'database',
        # we could check for an associated 'adminer' service and create a
        # more user-friendly route like 'db.project.test'.
        # For now, we just map services directly to subdomains.

    return routes
