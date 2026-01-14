"""Theme configuration for Impromptu.

Provides a configurable color palette for the sidebar and UI components.
Colors can be customized via the config file.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ColorPalette:
    """Color palette for the UI theme.
    
    Catppuccin Mocha-inspired palette with warm, muted tones.
    """
    # Background colors (warm dark)
    background: str = "#1e1e2e"     # Base background
    surface: str = "#313244"        # Cards/panels (surface0)
    surface_light: str = "#45475a"  # Elevated surfaces (surface1)
    
    # Border colors (subtle)
    border: str = "#45475a"         # surface1
    border_light: str = "#585b70"   # surface2
    
    # Text colors
    text: str = "#cdd6f4"           # Primary text (soft lavender-white)
    text_muted: str = "#6c7086"     # Secondary/muted (overlay1)
    text_dim: str = "#45475a"       # Very dim (surface1)
    
    # Accent colors (muted pastels)
    primary: str = "#b4befe"        # Lavender - main accent
    primary_dim: str = "#585b70"    # Dimmed primary
    secondary: str = "#cba6f7"      # Mauve - secondary accent
    
    # Status colors (gentle pastels)
    success: str = "#a6e3a1"        # Green
    success_dim: str = "#4a6a47"
    warning: str = "#f9e2af"        # Yellow
    warning_dim: str = "#7a7048"
    error: str = "#f38ba8"          # Red/rose
    error_dim: str = "#764354"
    
    # Agent status indicators
    agent_active: str = "#a6e3a1"    # Green - visible/ready
    agent_background: str = "#45475a" # Surface - in background
    agent_busy: str = "#f9e2af"       # Yellow - processing
    agent_blocked: str = "#f38ba8"    # Rose - needs attention
    
    # Selection/highlight colors
    selection: str = "#b4befe"        # Lavender
    selection_bg: str = "#313244"     # Surface0 for selection bg
    highlight: str = "#89dceb"        # Sky - accent highlight


@dataclass
class Spacing:
    """Spacing constants for consistent layout."""
    xs: int = 1
    sm: int = 2
    md: int = 3
    lg: int = 4
    xl: int = 6


@dataclass
class Theme:
    """Complete theme configuration."""
    name: str = "default"
    colors: ColorPalette = field(default_factory=ColorPalette)
    spacing: Spacing = field(default_factory=Spacing)
    
    # Border radius (in characters, for box drawing)
    border_radius: int = 1
    
    def get_css_variables(self) -> str:
        """Generate CSS variable definitions for the theme."""
        c = self.colors
        return f"""
        /* Background colors */
        --background: {c.background};
        --surface: {c.surface};
        --surface-light: {c.surface_light};
        
        /* Border colors */
        --border: {c.border};
        --border-light: {c.border_light};
        
        /* Text colors */
        --text: {c.text};
        --text-muted: {c.text_muted};
        --text-dim: {c.text_dim};
        
        /* Accent colors */
        --primary: {c.primary};
        --primary-dim: {c.primary_dim};
        --secondary: {c.secondary};
        
        /* Status colors */
        --success: {c.success};
        --success-dim: {c.success_dim};
        --warning: {c.warning};
        --warning-dim: {c.warning_dim};
        --error: {c.error};
        --error-dim: {c.error_dim};
        
        /* Selection */
        --selection: {c.selection};
        --selection-bg: {c.selection_bg};
        --highlight: {c.highlight};
        """


# Default theme instance
DEFAULT_THEME = Theme()


def load_theme(config: Optional[dict] = None) -> Theme:
    """Load theme from config or return default.
    
    Args:
        config: Optional config dict with theme overrides
        
    Returns:
        Theme instance with config values applied
    """
    theme = Theme()
    
    if config and "theme" in config:
        theme_config = config["theme"]
        
        # Apply name
        if "name" in theme_config:
            theme.name = theme_config["name"]
        
        # Apply color overrides
        if "colors" in theme_config:
            colors = theme_config["colors"]
            for key, value in colors.items():
                if hasattr(theme.colors, key):
                    setattr(theme.colors, key, value)
        
        # Apply spacing overrides
        if "spacing" in theme_config:
            spacing = theme_config["spacing"]
            for key, value in spacing.items():
                if hasattr(theme.spacing, key):
                    setattr(theme.spacing, key, value)
    
    return theme


# Convenience access to current theme colors
def get_colors() -> ColorPalette:
    """Get the default color palette."""
    return DEFAULT_THEME.colors
