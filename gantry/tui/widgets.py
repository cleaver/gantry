"""Custom Textual widgets for Gantry TUI."""

from typing import Optional

from textual.containers import Container, Horizontal
from textual.widgets import Button, DataTable, RichLog
from textual.message import Message

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


class LogViewer(Container):
    """A widget to display logs and a clear button."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.log_display = RichLog(wrap=True, highlight=True, id="log_display")
        self.clear_button = Button("Clear Logs", id="clear_logs")

    def compose(self):
        """Compose the widget."""
        yield self.log_display
        yield self.clear_button

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press."""
        if event.button.id == "clear_logs":
            self.log_display.clear()


class ProjectTable(DataTable):
    """Table widget displaying all registered projects."""

    class Action(Message):
        """Message to notify parent of an action."""

        def __init__(self, hostname: str, action: str) -> None:
            self.hostname = hostname
            self.action = action
            super().__init__()

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
        self.clear()
        self._project_rows.clear()
        sorted_projects = sorted(projects, key=lambda p: p.hostname)

        for project in sorted_projects:
            # Create buttons for actions. The row will be populated with a placeholder
            # and then updated with the actual button widgets.
            row_key = self.add_row(
                project.hostname,
                "...",
                str(project.port) if project.port else "N/A",
                "",
                key=project.hostname,
            )
            self._project_rows[str(row_key)] = project.hostname
            self.update_row(project.hostname, project)

    def update_row(self, hostname: str, project: Project) -> None:
        """Update a row in the table with fresh project data."""
        status = project.status
        color = get_status_color(status)
        status_text = f"[{color}]{status.capitalize()}[/{color}]"

        start_stop_label = "Stop" if status == "running" else "Start"
        start_stop_variant = "error" if status == "running" else "success"

        actions = Horizontal(
            Button(
                start_stop_label,
                variant=start_stop_variant,
                id=f"start-stop-{hostname}",
            ),
            Button("Restart", id=f"restart-{hostname}", disabled=status != "running"),
            Button("Update", id=f"update-{hostname}"),
        )
        self.update_cell(hostname, "Status", status_text)
        self.update_cell(hostname, "Actions", actions)

    def update_statuses(self) -> None:
        """Refresh project statuses and update the table."""
        statuses = self.orchestrator.get_all_status()

        for hostname, new_status in statuses.items():
            project = self.registry.get_project(hostname)
            if project and project.status != new_status:
                project.status = new_status
                self.update_row(hostname, project)

    def get_selected_project_hostname(self) -> Optional[str]:
        """Get the hostname of the currently selected project."""
        if self.cursor_row >= 0:
            return self.get_row_at(self.cursor_row)[0]
        return None

    def get_selected_project_details(self) -> Optional[Project]:
        """Get the full project object for the currently selected project."""
        hostname = self.get_selected_project_hostname()
        if hostname:
            return self.registry.get_project(hostname)
        return None

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses and emit an action message."""
        if event.button.id:
            action, hostname = event.button.id.split("-", 1)
            self.post_message(self.Action(hostname, action))
