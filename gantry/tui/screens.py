"""Screen classes for different views in Gantry TUI."""

from textual.containers import Container, Header, Footer
from textual.screen import Screen
from textual.widgets import Select
from textual.worker import Worker, get_current_worker

from gantry.process_manager import ProcessManager
from gantry.registry import Project, Registry
from gantry.orchestrator import Orchestrator
from gantry.tui.widgets import LogViewer, ProjectTable


class LogScreen(Screen):
    """A screen to display logs for a project."""

    BINDINGS = [("escape", "close_screen", "Close")]

    def __init__(
        self,
        project: Project,
        process_manager: ProcessManager,
        *args,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.project = project
        self.process_manager = process_manager
        self.log_viewer = LogViewer(id="log_viewer")
        self.service_selector: Select | None = None
        self._log_worker: Worker | None = None

    def compose(self):
        """Compose the screen."""
        yield Header(show_clock=False)

        # Create a list of services for the dropdown
        services = self.project.services or []
        service_options = [("All Services", "all")] + [(s, s) for s in services]
        self.service_selector = Select(service_options, value="all")

        yield Container(
            self.service_selector,
            self.log_viewer,
            id="log_container",
        )
        yield Footer()

    def on_mount(self) -> None:
        """Start tailing logs when the screen is mounted."""
        self.tail_logs("all")

    def on_select_changed(self, event: Select.Changed) -> None:
        """Handle service selection change."""
        self.tail_logs(str(event.value))

    def tail_logs(self, service: str | None) -> None:
        """Start a worker to tail logs for the selected service."""
        if self._log_worker is not None:
            self._log_worker.cancel()

        self.log_viewer.log_display.clear()
        self.log_viewer.log_display.write(
            f"Tailing logs for '{self.project.hostname}'..."
        )

        service_name = service if service != "all" else None
        self._log_worker = self.run_worker(
            self._log_tail_worker(service_name), exclusive=True
        )

    async def _log_tail_worker(self, service: str | None) -> None:
        """The worker coroutine to tail logs."""
        worker = get_current_worker()
        try:
            log_generator = self.process_manager.get_logs(
                self.project.hostname, service=service, follow=True
            )
            for line in log_generator:
                if worker.is_cancelled:
                    return
                self.call_from_thread(self.log_viewer.log_display.write, line)
        except Exception as e:
            self.call_from_thread(
                self.log_viewer.log_display.write, f"Error tailing logs: {e}"
            )

    def action_close_screen(self) -> None:
        """Close the log screen."""
        if self._log_worker is not None:
            self._log_worker.cancel()
        self.app.pop_screen()


class MainScreen(Screen):
    """Main screen displaying the project table."""

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("l", "logs", "Logs"),
        ("?", "help", "Help"),
    ]

    def __init__(
        self,
        registry: Registry,
        orchestrator: Orchestrator,
        process_manager: ProcessManager,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.registry = registry
        self.orchestrator = orchestrator
        self.process_manager = process_manager
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

    def action_logs(self) -> None:
        """Open the log viewer for the selected project."""
        if self.project_table:
            project = self.project_table.get_selected_project_details()
            if project:
                self.app.push_screen(
                    LogScreen(project=project, process_manager=self.process_manager)
                )

    def action_help(self) -> None:
        """Handle help action (placeholder for now)."""
        pass
