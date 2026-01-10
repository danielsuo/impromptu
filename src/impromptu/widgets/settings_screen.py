"""Settings screen for configuring the TUI."""

from textual.app import ComposeResult
from textual.widgets import Static, Switch, Input, Label, Button
from textual.containers import Vertical, Horizontal
from textual.screen import Screen

from ..config import Config, get_config_path


class SettingsScreen(Screen):
    """Screen for editing app settings."""

    DEFAULT_CSS = """
    SettingsScreen {
        align: center middle;
    }

    #settings-container {
        width: 60;
        height: auto;
        background: $surface;
        border: heavy $primary;
        padding: 2;
    }

    #settings-title {
        text-style: bold;
        padding-bottom: 1;
        text-align: center;
    }

    .setting-row {
        height: 3;
        padding: 0 1;
    }

    .setting-label {
        width: 1fr;
    }

    .setting-control {
        width: auto;
    }

    #config-path {
        margin-top: 1;
        color: $text-muted;
        text-align: center;
    }

    #button-row {
        margin-top: 1;
        align: center middle;
    }

    Button {
        margin: 0 1;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("enter", "save", "Save"),
    ]

    def __init__(self, config: Config):
        super().__init__()
        self.config = config

    def compose(self) -> ComposeResult:
        with Vertical(id="settings-container"):
            yield Static("⚙️ Settings", id="settings-title")

            # Dark mode
            with Horizontal(classes="setting-row"):
                yield Label("Dark Mode", classes="setting-label")
                yield Switch(value=self.config.appearance.dark_mode, id="dark-mode")

            # Show header
            with Horizontal(classes="setting-row"):
                yield Label("Show Header", classes="setting-label")
                yield Switch(value=self.config.behavior.show_header, id="show-header")

            # Show footer
            with Horizontal(classes="setting-row"):
                yield Label("Show Footer", classes="setting-label")
                yield Switch(value=self.config.behavior.show_footer, id="show-footer")

            # Notifications enabled
            with Horizontal(classes="setting-row"):
                yield Label("Notifications", classes="setting-label")
                yield Switch(value=self.config.notifications.enabled, id="notifications")

            # Sound enabled
            with Horizontal(classes="setting-row"):
                yield Label("Sound", classes="setting-label")
                yield Switch(value=self.config.notifications.sound, id="sound")

            # Sidebar width
            with Horizontal(classes="setting-row"):
                yield Label("Sidebar Width", classes="setting-label")
                yield Input(
                    value=str(self.config.layout.sidebar_width),
                    id="sidebar-width",
                    type="integer",
                )

            yield Static(f"Config: {get_config_path()}", id="config-path")

            with Horizontal(id="button-row"):
                yield Button("Save", variant="primary", id="save-btn")
                yield Button("Cancel", variant="default", id="cancel-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "save-btn":
            self.action_save()
        elif event.button.id == "cancel-btn":
            self.action_cancel()

    def action_save(self) -> None:
        """Save settings and return to main screen."""
        # Update config values
        self.config.appearance.dark_mode = self.query_one("#dark-mode", Switch).value
        self.config.behavior.show_header = self.query_one("#show-header", Switch).value
        self.config.behavior.show_footer = self.query_one("#show-footer", Switch).value
        self.config.notifications.enabled = self.query_one("#notifications", Switch).value
        self.config.notifications.sound = self.query_one("#sound", Switch).value

        try:
            width = int(self.query_one("#sidebar-width", Input).value)
            self.config.layout.sidebar_width = max(20, min(60, width))
        except ValueError:
            pass

        # Write to config file
        self._save_config()

        self.app.notify("Settings saved! Restart to apply all changes.")
        self.app.pop_screen()

    def action_cancel(self) -> None:
        """Cancel and return to main screen."""
        self.app.pop_screen()

    def _save_config(self) -> None:
        """Write current config to file."""
        config_path = get_config_path()
        config_content = f"""\
# TUI App Configuration

[appearance]
dark_mode = {str(self.config.appearance.dark_mode).lower()}

[behavior]
show_header = {str(self.config.behavior.show_header).lower()}
show_footer = {str(self.config.behavior.show_footer).lower()}

[notifications]
enabled = {str(self.config.notifications.enabled).lower()}
sound = {str(self.config.notifications.sound).lower()}
duration_seconds = {self.config.notifications.duration_seconds}

[layout]
sidebar_width = {self.config.layout.sidebar_width}
default_focus = "{self.config.layout.default_focus}"

[tabs]
visible = {self.config.tabs.visible}
"""
        config_path.write_text(config_content)
