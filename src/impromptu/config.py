"""Configuration management for impromptu."""

import os
import tomllib
from pathlib import Path
from dataclasses import dataclass, field
from typing import Literal

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

[agents]
# Agent name = command to run
gemini = "gemini"
# claude = "claude --chat"

[keybindings]
# Key = pane index or tmux command
# M- = Alt, C- = Ctrl
switch_1 = "M-1"
switch_2 = "M-2"
switch_3 = "M-3"
sidebar = "M-i"
new_agent = "M-n"
"""


@dataclass
class AppearanceConfig:
    dark_mode: bool = True


@dataclass
class BehaviorConfig:
    show_header: bool = True
    show_footer: bool = True


@dataclass
class NotificationsConfig:
    enabled: bool = True
    sound: bool = False
    duration_seconds: int = 5


@dataclass
class LayoutConfig:
    sidebar_width: int = 25


@dataclass
class AgentsConfig:
    agents: dict[str, str] = field(default_factory=lambda: {"gemini": "gemini"})


@dataclass
class KeybindingsConfig:
    switch_1: str = "M-1"
    switch_2: str = "M-2"
    switch_3: str = "M-3"
    switch_4: str = "M-4"
    switch_5: str = "M-5"
    sidebar: str = "M-s"
    new_agent: str = "M-n"


@dataclass
class Config:
    appearance: AppearanceConfig = field(default_factory=AppearanceConfig)
    behavior: BehaviorConfig = field(default_factory=BehaviorConfig)
    notifications: NotificationsConfig = field(default_factory=NotificationsConfig)
    layout: LayoutConfig = field(default_factory=LayoutConfig)
    agents: AgentsConfig = field(default_factory=AgentsConfig)
    keybindings: KeybindingsConfig = field(default_factory=KeybindingsConfig)


def load_config() -> Config:
    """Load configuration from file, creating default if it doesn't exist."""
    config_file = _find_config_file()

    if not config_file.exists():
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text(DEFAULT_CONFIG)
        return Config()

    with open(config_file, "rb") as f:
        data = tomllib.load(f)

    appearance_data = data.get("appearance", {})
    behavior_data = data.get("behavior", {})
    notifications_data = data.get("notifications", {})
    layout_data = data.get("layout", {})
    agents_data = data.get("agents", {})
    keybindings_data = data.get("keybindings", {})

    return Config(
        appearance=AppearanceConfig(
            dark_mode=appearance_data.get("dark_mode", True),
        ),
        behavior=BehaviorConfig(
            show_header=behavior_data.get("show_header", True),
            show_footer=behavior_data.get("show_footer", True),
        ),
        notifications=NotificationsConfig(
            enabled=notifications_data.get("enabled", True),
            sound=notifications_data.get("sound", False),
            duration_seconds=notifications_data.get("duration_seconds", 5),
        ),
        layout=LayoutConfig(
            sidebar_width=layout_data.get("sidebar_width", 25),
        ),
        agents=AgentsConfig(
            agents=agents_data if agents_data else {"gemini": "gemini"},
        ),
        keybindings=KeybindingsConfig(
            switch_1=keybindings_data.get("switch_1", "M-1"),
            switch_2=keybindings_data.get("switch_2", "M-2"),
            switch_3=keybindings_data.get("switch_3", "M-3"),
            sidebar=keybindings_data.get("sidebar", "M-s"),
            new_agent=keybindings_data.get("new_agent", "M-n"),
        ),
    )


def get_config_path() -> Path:
    """Return the path to the config file."""
    return _find_config_file()
