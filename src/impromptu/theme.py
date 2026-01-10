"""Theme configuration for Impromptu.

Provides a configurable color palette for the sidebar and UI components.
Colors can be customized via the config file.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ColorPalette:
    """Color palette for the UI theme.
    
    Based on a gentle dark dashboard aesthetic with muted pastel accents.
    """
    # Background colors (dark navy)
    background: str = "#1a1b26"     # Darkest background
    surface: str = "#1f2335"        # Cards/panels
    surface_light: str = "#292e42" # Slightly lighter surface
    
    # Border colors
    border: str = "#3b4261"
    border_light: str = "#545c7e"
    
    # Text colors
    text: str = "#c0caf5"          # Primary text (soft blue-white)
    text_muted: str = "#565f89"    # Secondary/muted text
    text_dim: str = "#3b4261"      # Very dim text
    
    # Accent colors (muted pastels)
    primary: str = "#7aa2f7"       # Soft blue
    primary_dim: str = "#3d59a1"   # Dimmed primary
    secondary: str = "#bb9af7"     # Soft purple
    
    # Status colors (gentle pastels)
    success: str = "#9ece6a"       # Soft green
    success_dim: str = "#4d6c36"
    warning: str = "#e0af68"       # Soft amber/gold
    warning_dim: str = "#8a6622"
    error: str = "#f7768e"         # Soft pink/coral
    error_dim: str = "#914c5b"
    
    # Agent status indicators
    agent_active: str = "#9ece6a"    # Soft green - visible/ready
    agent_background: str = "#565f89" # Muted gray - in background
    agent_busy: str = "#e0af68"       # Soft amber - processing
    
    # Selection/highlight colors
    selection: str = "#7aa2f7"
    selection_bg: str = "#283457"   # Selection background
    highlight: str = "#7dcfff"      # Soft cyan highlight


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
