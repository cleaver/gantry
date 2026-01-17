"""Main Textual application for Gantry TUI."""

from textual.app import App, ComposeResult
from textual.containers import Container


class GantryApp(App):
    """Main Gantry TUI application."""

    TITLE = "Gantry Console"
    CSS_PATH = None  # Will be added in later phases

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield Container()

    def on_mount(self) -> None:
        """Called when app is mounted."""
        pass
