"""Custom Textual widgets for Gantry TUI."""

from typing import Optional

from textual.widgets import DataTable

from gantry.registry import Project, Registry
from gantry.orchestrator import Orchestrator


def get_status_color(status: str) -> str:
    """Get color for a project status."""
    if status == "running":
        return "green"
    elif status == "stopped":
        return "grey70"
    elif status == "error":
        return "red"
    return "white"


class ProjectTable(DataTable):
    """Table widget displaying all registered projects."""

    def __init__(
        self,
        registry: Registry,
        orchestrator: Orchestrator,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.registry = registry
        self.orchestrator = orchestrator
        self._project_rows: dict[str, str] = {}  # Maps row_key to hostname

    def on_mount(self) -> None:
        """Set up table columns when widget is mounted."""
        self.add_columns("Name", "Status", "Port", "Actions")
        self.cursor_type = "row"
        self.populate_table()

    def populate_table(self) -> None:
        """Load projects from registry and populate the table."""
        projects = self.registry.list_projects()
        # Clear existing rows
        self.clear()
        self._project_rows.clear()

        # Sort projects by hostname
        sorted_projects = sorted(projects, key=lambda p: p.hostname)

        for project in sorted_projects:
            row_key = self._add_project_row(project)
            self._project_rows[row_key] = project.hostname

    def _add_project_row(self, project: Project) -> str:
        """Add a single project row to the table."""
        status = project.status
        color = get_status_color(status)
        status_text = f"[{color}]{status.capitalize()}[/{color}]"
        port_text = str(project.port) if project.port else "N/A"
        actions_text = ""  # Placeholder for actions (will be implemented in 5.5)

        row_key = self.add_row(
            project.hostname,
            status_text,
            port_text,
            actions_text,
            key=project.hostname,
        )
        return row_key

    def update_statuses(self) -> None:
        """Refresh project statuses and update the table."""
        # Get fresh statuses from orchestrator (triggers live checks)
        statuses = self.orchestrator.get_all_status()

        # Update status column for each project
        for row_key, hostname in self._project_rows.items():
            if hostname in statuses:
                new_status = statuses[hostname]
                color = get_status_color(new_status)
                status_text = f"[{color}]{new_status.capitalize()}[/{color}]"

                # Update the status cell
                self.update_cell(row_key, "Status", status_text)

    def get_selected_project(self) -> Optional[str]:
        """Get the hostname of the currently selected project."""
        cursor_row = self.cursor_row
        if cursor_row is not None:
            try:
                # Get hostname from the Name column (column 0)
                cell_value = self.get_cell_at(cursor_row, 0)
                if cell_value:
                    return str(cell_value)
            except (IndexError, KeyError):
                pass
        return None
