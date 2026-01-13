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

def _get_default_config() -> str:
    """Load default config from configs/default.toml."""
    default_path = Path(__file__).parent / "configs" / "default.toml"
    return default_path.read_text()


@dataclass
class Config:
    """Flat configuration holding all settings."""
    # Appearance
    dark_mode: bool = True
    
    # Behavior
    show_header: bool = True
    show_footer: bool = True
    confirm_on_quit: bool = True  # Show confirmation modal before quitting
    confirm_on_close: bool = False  # Show confirmation modal before closing agent
    
    # Notifications
    notifications_enabled: bool = True
    notifications_sound: bool = False
    notifications_duration: int = 5
    
    # Layout
    sidebar_width: int = 25
    
    # Agents - list of raw TOML tables (dicts)
    agents: list[dict] = field(default_factory=list)
    
    # Unified bindings - both tmux (M-key) and sidebar bindings
    bindings: dict | list = field(default_factory=dict)
    
    # Runtime options
    debug_mode: bool = False
    
    def get_tmux_bindings(self) -> dict[str, str]:
        """Extract tmux bindings (M-key) from bindings.
        
        Returns dict mapping key -> action for keys starting with M-.
        """
        result = {}
        if isinstance(self.bindings, dict):
            for key, value in self.bindings.items():
                if key.startswith("M-"):
                    if isinstance(value, list) and len(value) >= 1:
                        result[key] = value[0]
        return result
    
    def get_agent_names(self) -> list[str]:
        """Get list of configured agent names."""
        return [a.get("name", "unnamed") for a in self.agents]
    
    def get_agent_table(self, name: str) -> dict | None:
        """Get agent config table by name."""
        for agent in self.agents:
            if agent.get("name") == name:
                return agent
        return None
    
    def get_textual_bindings(self) -> list[tuple]:
        """Convert bindings config to Textual BINDINGS format.
        
        Supports two formats:
        - Old: list of dicts [{key, action, label}, ...]
        - New: dict {key: [action, label], ...} or {key: [action], ...}
        
        Returns list of tuples: (key, action, label) or (key, action)
        """
        result = []
        
        if isinstance(self.bindings, dict):
            # New compact format: key = [action, label] or key = [action]
            for key, value in self.bindings.items():
                if isinstance(value, list) and len(value) >= 1:
                    action = value[0]
                    label = value[1] if len(value) > 1 else None
                    if label:
                        result.append((key, action, label))
                    else:
                        result.append((key, action))
        else:
            # Old list format: [{key, action, label}, ...]
            for b in self.bindings:
                key = b.get("key", "")
                action = b.get("action", "")
                label = b.get("label")
                if key and action:
                    if label:
                        result.append((key, action, label))
                    else:
                        result.append((key, action))
        return result


def _deep_merge(base: dict, override: dict) -> dict:
    """Deep merge override into base, returning a new dict.
    
    Lists are replaced entirely (not merged).
    """
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _merge_agents(default_agents: list[dict], user_agents: list[dict]) -> list[dict]:
    """Merge user agents with defaults, preserving default fields not overridden.
    
    For each user agent, find matching default by name and merge.
    User values take precedence, but missing fields come from defaults.
    """
    if not user_agents:
        return default_agents
    
    # Build lookup of default agents by name
    defaults_by_name = {a.get("name"): a for a in default_agents}
    
    result = []
    for user_agent in user_agents:
        name = user_agent.get("name")
        if name and name in defaults_by_name:
            # Merge: start with defaults, override with user values
            merged = defaults_by_name[name].copy()
            merged.update(user_agent)
            result.append(merged)
        else:
            # No matching default, use user agent as-is
            result.append(user_agent)
    
    return result


def load_config() -> Config:
    """Load configuration, merging user config over defaults.
    
    1. Load defaults from configs/default.toml
    2. If user config exists, merge it over defaults
    3. User config only needs to specify overrides
    """
    # Load defaults
    default_path = Path(__file__).parent / "configs" / "default.toml"
    with open(default_path, "rb") as f:
        defaults = tomllib.load(f)
    
    # Find and load user config if exists
    config_file = _find_config_file()
    if config_file.exists():
        with open(config_file, "rb") as f:
            user_config = tomllib.load(f)
        data = _deep_merge(defaults, user_config)
        # Special handling for agents: merge by name to preserve default fields
        default_agents = defaults.get("agents", [])
        user_agents = user_config.get("agents", [])
        if user_agents:
            data["agents"] = _merge_agents(default_agents, user_agents)
    else:
        # Create user config from defaults
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text(_get_default_config())
        data = defaults

    appearance = data.get("appearance", {})
    behavior = data.get("behavior", {})
    notifications = data.get("notifications", {})
    layout = data.get("layout", {})
    agents = data.get("agents", [])
    bindings = data.get("bindings", {})
    
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
        confirm_on_quit=behavior.get("confirm_on_quit", True),
        confirm_on_close=behavior.get("confirm_on_close", True),
        notifications_enabled=notifications.get("enabled", True),
        notifications_sound=notifications.get("sound", False),
        notifications_duration=notifications.get("duration_seconds", 5),
        sidebar_width=layout.get("sidebar_width", 25),
        agents=agents,
        bindings=bindings,
    )


def get_config_path() -> Path:
    """Return the path to the config file."""
    return _find_config_file()
