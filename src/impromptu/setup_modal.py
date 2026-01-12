"""Setup command modal for impromptu."""
from textual.screen import ModalScreen
from textual.widgets import Static, Input
from textual.containers import Vertical
from textual.app import ComposeResult
from .theme import get_colors


class SetupCommandModal(ModalScreen[str]):
    """Modal for entering an optional setup command before launching agent."""
    
    @property
    def CSS(self) -> str:
        c = get_colors()
        return f"""
    SetupCommandModal {{
        align: center middle;
        background: rgba(0, 0, 0, 0.6);
    }}
    #setup-container {{
        width: 90%;
        height: auto;
        background: {c.surface};
        border: thick {c.primary};
        padding: 1 1;
    }}
    #setup-title {{
        text-style: bold;
        text-align: center;
        padding-bottom: 1;
        color: {c.text};
    }}
    #setup-hint {{
        color: {c.text_muted};
        padding-bottom: 1;
        width: 100%;
        overflow: hidden;
    }}
    #setup-input {{
        width: 100%;
    }}
    """
    
    BINDINGS = [("escape", "skip", "Skip")]
    
    def __init__(self, agent_name: str) -> None:
        super().__init__()
        self.agent_name = agent_name
    
    def compose(self) -> ComposeResult:
        with Vertical(id="setup-container"):
            yield Static(f"Setup for {self.agent_name}", id="setup-title")
            yield Static("Setup cmd (optional):", id="setup-hint")
            yield Input(placeholder="Enter to skip", id="setup-input")
    
    def action_skip(self) -> None:
        self.dismiss("")
    
    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)
