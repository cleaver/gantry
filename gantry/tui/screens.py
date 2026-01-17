"""Screen classes for different views in Gantry TUI."""

import asyncio
from time import sleep
from typing import Any, Callable, TypedDict

from textual.app import App, ComposeResult
from textual.containers import Container, Grid, Horizontal
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Label, Select, Static
from textual.worker import Worker, get_current_worker

from gantry.process_manager import ProcessManager
from gantry.registry import Project, Registry
from gantry.orchestrator import Orchestrator
from gantry.tui.widgets import LogViewer, ProjectTable
from gantry.detectors import rescan_project


class Changes(TypedDict, total=False):
    services_added: list[str]
    services_removed: list[str]
    ports_changed: dict[str, dict[str, int]]
    ports_added: dict[str, int]
    ports_removed: dict[str, int]


class ConfirmDialog(Screen[bool]):
    """A modal dialog to ask for confirmation."""

    def __init__(self, message: str, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.message = message

    def compose(self) -> ComposeResult:
        yield Grid(
            Label(self.message, id="question"),
            Horizontal(
                Button("Yes", variant="primary", id="yes"),
                Button("No", variant="default", id="no"),
            ),
            id="dialog",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")


class UpdateScreen(Screen[bool]):
    """A screen to show project updates and ask for confirmation."""

    def __init__(self, project: Project, changes: Changes, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.project = project
        self.changes = changes

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Label(f"Update '{self.project.hostname}'?")
        yield Static(self._format_changes(), id="changes")
        yield Horizontal(
            Button("Apply", variant="success", id="apply"),
            Button("Cancel", variant="error", id="cancel"),
            id="update-buttons",
        )
        yield Footer()

    def _format_changes(self) -> str:
        """Format the changes into a readable string."""
        if not self.changes:
            return "No changes detected."

        lines = []
        if added := self.changes.get("services_added"):
            lines.append(f"[green]Services Added: {', '.join(added)}[/green]")
        if removed := self.changes.get("services_removed"):
            lines.append(f"[red]Services Removed: {', '.join(removed)}[/red]")
        if added_ports := self.changes.get("ports_added"):
            lines.append(f"[green]Ports Added: {added_ports}[/green]")
        if removed_ports := self.changes.get("ports_removed"):
            lines.append(f"[red]Ports Removed: {removed_ports}[/red]")
        if changed_ports := self.changes.get("ports_changed"):
            lines.append(f"[yellow]Ports Changed: {changed_ports}[/yellow]")

        return "\n".join(lines)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "apply")


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
        self.tail_logs("all")

    def on_select_changed(self, event: Select.Changed) -> None:
        self.tail_logs(str(event.value))

    def tail_logs(self, service: str | None) -> None:
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
        worker = get_current_worker()
        try:
            log_generator = self.process_manager.get_logs(
                self.project.hostname, service=service, follow=True
            )
            for line in log_generator:
                if worker.is_cancelled:
                    return
                self.app.call_from_thread(self.log_viewer.log_display.write, line)
        except Exception as e:
            self.app.call_from_thread(
                self.log_viewer.log_display.write, f"Error tailing logs: {e}"
            )

    def action_close_screen(self) -> None:
        if self._log_worker is not None:
            self._log_worker.cancel()
        self.app.pop_screen()


class MainScreen(Screen):
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("l", "logs", "Logs"),
        ("r", "restart", "Restart"),
        ("u", "update", "Update"),
        ("enter", "toggle_start_stop", "Start/Stop"),
        ("A", "stop_all", "Stop All"),
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
        yield Header(show_clock=False)
        yield Container(
            ProjectTable(self.registry, self.orchestrator, id="project_table"),
            id="main_container",
        )
        yield Footer()

    def on_mount(self) -> None:
        self.project_table = self.query_one(ProjectTable)
        self.set_interval(0.5, self._update_statuses)

    def _update_statuses(self) -> None:
        if self.project_table and not self.project_table.disabled:
            self.project_table.update_statuses()

    def on_project_table_action(self, message: ProjectTable.Action) -> None:
        if message.action == "start-stop":
            self.action_toggle_start_stop(message.hostname)
        elif message.action == "restart":
            self.action_restart(message.hostname)
        elif message.action == "update":
            self.action_update(message.hostname)

    def _execute_action(
        self, hostname: str, action: Callable[..., Any], *args: Any
    ) -> None:
        async def worker():
            if self.project_table:
                self.project_table.disabled = True
            try:
                action(hostname, *args)
                await asyncio.sleep(0.5)
            finally:
                if self.project_table:
                    self.project_table.disabled = False
                    self.app.call_from_thread(self.project_table.update_statuses)

        self.run_worker(worker)

    def action_toggle_start_stop(self, hostname: str | None = None) -> None:
        if not hostname:
            project = self.project_table.get_selected_project_details()
            if not project:
                return
            hostname = project.hostname
        else:
            project = self.registry.get_project(hostname)

        if project:
            action = (
                self.orchestrator.stop_project
                if project.status == "running"
                else self.orchestrator.start_project
            )
            self._execute_action(hostname, action)

    def action_restart(self, hostname: str | None = None) -> None:
        if not hostname:
            hostname = self.project_table.get_selected_project_hostname()
        if hostname:
            self._execute_action(hostname, self.orchestrator.restart_project)

    def action_stop_all(self) -> None:
        def on_confirm(do_stop: bool) -> None:
            if do_stop:
                self._execute_action("all", lambda *args: self.orchestrator.stop_all())

        self.app.push_screen(ConfirmDialog("Stop all running projects?"), on_confirm)

    def action_update(self, hostname: str | None = None) -> None:
        if not hostname:
            hostname = self.project_table.get_selected_project_hostname()
        if not hostname:
            return

        project = self.registry.get_project(hostname)
        if not project:
            return

        changes = rescan_project(project.path, project.model_dump(exclude_none=True))

        def on_confirm(do_update: bool) -> None:
            if do_update and changes:
                self.registry.update_project_metadata(hostname, **changes)
                if self.project_table:
                    self.project_table.populate_table()

        self.app.push_screen(UpdateScreen(project, changes), on_confirm)

    def action_quit(self) -> None:
        self.app.exit()

    def action_logs(self) -> None:
        if self.project_table:
            project = self.project_table.get_selected_project_details()
            if project:
                self.app.push_screen(
                    LogScreen(project=project, process_manager=self.process_manager)
                )

    def action_help(self) -> None:
        pass
