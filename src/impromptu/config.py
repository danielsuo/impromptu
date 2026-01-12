"""Configuration management for impromptu."""

import os
import tomllib
from pathlib import Path
from dataclasses import dataclass, field

from platformdirs import user_config_dir

APP_NAME = "impromptu"


def _find_config_file() -> Path:
    """Find config file, checking platformdirs location first, then XDG fallback."""
    platformdirs_config = Path(user_config_dir(APP_NAME)) / "config.toml"
    if platformdirs_config.exists():
        return platformdirs_config

    xdg_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    xdg_config = xdg_home / APP_NAME / "config.toml"
    if xdg_config.exists():
        return xdg_config

    return xdg_config


DEFAULT_CONFIG = """\
# Impromptu Configuration

[appearance]
dark_mode = true

[behavior]
show_header = true
show_footer = true

[notifications]
enabled = true
sound = false
duration_seconds = 5

[layout]
sidebar_width = 25

[[agents]]
name = "gemini"
path = "/google/bin/releases/gemini-cli/tools/gemini"
flags = "--yolo"
agent_type = "gemini"

[keybindings]
switch_1 = "M-1"
switch_2 = "M-2"
switch_3 = "M-3"
sidebar = "M-i"
new_agent = "M-n"
"""


@dataclass
class Config:
    """Flat configuration holding all settings."""
    # Appearance
    dark_mode: bool = True
    
    # Behavior
    show_header: bool = True
    show_footer: bool = True
    
    # Notifications
    notifications_enabled: bool = True
    notifications_sound: bool = False
    notifications_duration: int = 5
    
    # Layout
    sidebar_width: int = 25
    
    # Agents - list of raw TOML tables (dicts)
    agents: list[dict] = field(default_factory=list)
    
    # Keybindings
    keybindings: dict[str, str] = field(default_factory=dict)
    
    def get_agent_names(self) -> list[str]:
        """Get list of configured agent names."""
        return [a.get("name", "unnamed") for a in self.agents]
    
    def get_agent_table(self, name: str) -> dict | None:
        """Get agent config table by name."""
        for agent in self.agents:
            if agent.get("name") == name:
                return agent
        return None


def load_config() -> Config:
    """Load configuration from file, creating default if it doesn't exist."""
    config_file = _find_config_file()

    if not config_file.exists():
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text(DEFAULT_CONFIG)
        return Config()

    with open(config_file, "rb") as f:
        data = tomllib.load(f)

    appearance = data.get("appearance", {})
    behavior = data.get("behavior", {})
    notifications = data.get("notifications", {})
    layout = data.get("layout", {})
    agents = data.get("agents", [])
    keybindings = data.get("keybindings", {})
    
    # Ensure agents is a list (handles old format)
    if isinstance(agents, dict):
        # Convert old {name: cmd} format to new format
        agents = [{"name": k, "path": v, "agent_type": "shell"} for k, v in agents.items()]
    
    # Default agent if none configured
    if not agents:
        agents = [{
            "name": "gemini",
            "path": "/google/bin/releases/gemini-cli/tools/gemini",
            "flags": "--yolo",
            "agent_type": "gemini"
        }]

    return Config(
        dark_mode=appearance.get("dark_mode", True),
        show_header=behavior.get("show_header", True),
        show_footer=behavior.get("show_footer", True),
        notifications_enabled=notifications.get("enabled", True),
        notifications_sound=notifications.get("sound", False),
        notifications_duration=notifications.get("duration_seconds", 5),
        sidebar_width=layout.get("sidebar_width", 25),
        agents=agents,
        keybindings=keybindings,
    )


def get_config_path() -> Path:
    """Return the path to the config file."""
    return _find_config_file()
