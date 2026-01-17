"""Screen classes for different views in Gantry TUI."""

from textual.containers import Container, Header, Footer
from textual.screen import Screen

from gantry.registry import Registry
from gantry.orchestrator import Orchestrator
from gantry.tui.widgets import ProjectTable


class MainScreen(Screen):
    """Main screen displaying the project table."""

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("?", "help", "Help"),
    ]

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
        self.project_table: ProjectTable | None = None

    def compose(self):
        """Create child widgets for the screen."""
        yield Header(show_clock=False)
        yield Container(
            ProjectTable(
                self.registry,
                self.orchestrator,
                id="project_table",
            ),
            id="main_container",
        )
        yield Footer()

    def on_mount(self) -> None:
        """Set up the screen when mounted."""
        # Get reference to the project table
        self.project_table = self.query_one(ProjectTable)

        # Set up periodic status updates (500ms interval as per spec)
        self.set_interval(0.5, self._update_statuses)

    def _update_statuses(self) -> None:
        """Callback for periodic status updates."""
        if self.project_table:
            self.project_table.update_statuses()

    def action_quit(self) -> None:
        """Handle quit action."""
        self.app.exit()

    def action_help(self) -> None:
        """Handle help action (placeholder for now)."""
        pass
