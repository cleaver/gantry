"""Main Textual application for Gantry TUI."""

from textual.app import App

from gantry.orchestrator import Orchestrator
from gantry.port_allocator import PortAllocator
from gantry.process_manager import ProcessManager
from gantry.registry import Registry
from gantry.tui.screens import MainScreen


class GantryApp(App):
    """Main Gantry TUI application."""

    TITLE = "Gantry Console"
    CSS_PATH = None  # Will be added in later phases

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Initialize core components
        self.registry = Registry()
        self.port_allocator = PortAllocator(self.registry)
        self.process_manager = ProcessManager(self.registry, self.port_allocator)
        self.orchestrator = Orchestrator(self.registry, self.process_manager)

    def on_mount(self) -> None:
        """Push the main screen when app is mounted."""
        self.push_screen(
            MainScreen(
                registry=self.registry,
                orchestrator=self.orchestrator,
                process_manager=self.process_manager,
            )
        )
