"""Modal screens for Impromptu UI."""

from textual.app import ComposeResult
from textual.widgets import Static, ListView, ListItem, Label, Button, Input
from textual.containers import Vertical, Horizontal
from textual.screen import ModalScreen


class AgentSelectItem(ListItem):
    """A list item for agent selection in the modal."""

    def __init__(self, name: str, command: str) -> None:
        super().__init__()
        self.agent_name = name
        self.command = command

    def compose(self) -> ComposeResult:
        yield Label(f"  {self.agent_name}")


class AgentSelectModal(ModalScreen[tuple[str, str] | None]):
    """Modal for selecting which agent to start in a new pane."""
    
    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("j", "cursor_down", "Down"),
        ("k", "cursor_up", "Up"),
        ("ctrl+n", "cursor_down", "Down"),
        ("ctrl+p", "cursor_up", "Up"),
    ]
    
    def __init__(self, agents: list[tuple[str, str]]) -> None:
        super().__init__()
        self.agents = agents
    
    def compose(self) -> ComposeResult:
        with Vertical(id="modal-container"):
            yield Static("Select Agent", id="modal-title")
            with ListView(id="agent-select-list"):
                for agent in self.agents:
                    # Handle both (name, cmd) and (name, cmd, num_lines) formats
                    name = agent[0]
                    cmd = agent[1]
                    yield AgentSelectItem(name, cmd)
                yield AgentSelectItem("Empty Shell", "")
                item = AgentSelectItem("[Cancel]", "__CANCEL__")
                item.add_class("cancel-item")
                yield item
    
    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if isinstance(event.item, AgentSelectItem):
            if event.item.command == "__CANCEL__":
                self.dismiss(None)
            else:
                self.dismiss((event.item.agent_name, event.item.command))
    
    def action_cancel(self) -> None:
        self.dismiss(None)
    
    def action_cursor_down(self) -> None:
        list_view = self.query_one("#agent-select-list", ListView)
        list_view.action_cursor_down()
    
    def action_cursor_up(self) -> None:
        list_view = self.query_one("#agent-select-list", ListView)
        list_view.action_cursor_up()


class ShortcutsModal(ModalScreen[None]):
    """Modal showing keyboard shortcuts."""
    
    BINDINGS = [
        ("escape", "close", "Close"),
        ("question_mark", "close", "Close"),
    ]
    
    ACTION_DESCRIPTIONS = {
        "new_agent": "New agent",
        "rename_agent": "Rename",
        "import_agent": "Import pane",
        "close_agent": "Close agent",
        "focus_agent_pane": "Focus pane",
        "refresh": "Refresh",
        "show_shortcuts": "Help",
        "cursor_down": "Move down",
        "cursor_up": "Move up",
    }
    
    def compose(self) -> ComposeResult:
        with Vertical(id="shortcuts-container"):
            yield Static("⌨ Keyboard Shortcuts", id="shortcuts-title")
            
            from .. import main as main_module
            bindings = getattr(main_module.Sidebar, 'BINDINGS', [])
            
            nav_keys = []
            agent_keys = []
            for binding in bindings:
                if len(binding) < 3:
                    continue
                key, action, desc = binding[0], binding[1], binding[2]
                display_key = key.replace("question_mark", "?")
                action_name = action.split("(")[0]
                display_desc = self.ACTION_DESCRIPTIONS.get(action_name, desc)
                
                if action_name in ("cursor_down", "cursor_up", "focus_agent_pane"):
                    nav_keys.append((display_key, display_desc))
                elif action_name.startswith("switch_agent"):
                    continue
                else:
                    agent_keys.append((display_key, display_desc))
            
            yield Static("Navigation", classes="shortcut-section")
            yield Static("j/k      Move up/down", classes="shortcut-row")
            yield Static("Tab      Focus pane", classes="shortcut-row")
            yield Static("Enter    Select agent", classes="shortcut-row")
            
            yield Static("Agents", classes="shortcut-section")
            for key, desc in agent_keys:
                yield Static(f"{key:<8} {desc}", classes="shortcut-row")
            yield Static("1-5      Switch to #", classes="shortcut-row")
            
            yield Static("", classes="shortcut-section")
            yield Static("Esc/?    Close help", classes="shortcut-row")
    
    def action_close(self) -> None:
        self.dismiss(None)


class RenameModal(ModalScreen[str | None]):
    """Modal for renaming an agent pane."""
    
    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]
    
    def __init__(self, current_name: str) -> None:
        super().__init__()
        self.current_name = current_name
    
    def compose(self) -> ComposeResult:
        with Vertical(id="rename-container"):
            yield Static("✏ Rename Agent", id="rename-title")
            yield Input(value=self.current_name, placeholder="Enter new name", id="rename-input")
            yield Static("Enter to confirm, Escape to cancel", id="rename-hint")
    
    def on_input_submitted(self, event: Input.Submitted) -> None:
        new_name = event.value.strip()
        if new_name:
            self.dismiss(new_name)
        else:
            self.dismiss(None)
    
    def action_cancel(self) -> None:
        self.dismiss(None)


class QuitConfirmModal(ModalScreen[bool]):
    """Modal to confirm quitting impromptu."""
    
    BINDINGS = [
        ("y", "confirm", "Yes"),
        ("n", "cancel", "No"),
        ("escape", "cancel", "Cancel"),
        ("left", "focus_previous", "Left"),
        ("right", "focus_next", "Right"),
        ("h", "focus_previous", "Left"),
        ("l", "focus_next", "Right"),
    ]
    
    def compose(self) -> ComposeResult:
        with Vertical(id="quit-container"):
            yield Static("⚠ Quit Impromptu?", id="quit-title")
            yield Static("This will kill all agent panes.", id="quit-message")
            with Horizontal(id="button-row"):
                yield Button("Yes", id="btn-yes", classes="quit-button")
                yield Button("No", id="btn-no", classes="quit-button")
    
    def on_mount(self) -> None:
        self.query_one("#btn-no").focus()
    
    def on_button_pressed(self, event) -> None:
        if event.button.id == "btn-yes":
            self.dismiss(True)
        else:
            self.dismiss(False)
    
    def action_confirm(self) -> None:
        self.dismiss(True)
    
    def action_cancel(self) -> None:
        self.dismiss(False)
    
    def action_focus_previous(self) -> None:
        self.focus_previous()
    
    def action_focus_next(self) -> None:
        self.focus_next()


class SetupCommandModal(ModalScreen[str]):
    """Modal for entering an optional setup command before launching agent."""
    
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


class CloseAgentModal(ModalScreen[bool]):
    """Modal to confirm closing an agent pane."""
    
    def __init__(self, agent_name: str) -> None:
        super().__init__()
        self.agent_name = agent_name
    
    BINDINGS = [
        ("y", "confirm", "Yes"),
        ("n", "cancel", "No"),
        ("escape", "cancel", "Cancel"),
        ("left", "focus_previous", "Left"),
        ("right", "focus_next", "Right"),
        ("h", "focus_previous", "Left"),
        ("l", "focus_next", "Right"),
    ]
    
    def compose(self) -> ComposeResult:
        with Vertical(id="close-container"):
            yield Static(f"⚠ Close {self.agent_name}?", id="close-title")
            yield Static("This will terminate the agent process.", id="close-message")
            with Horizontal(id="button-row"):
                yield Button("Yes", id="btn-yes", classes="close-button")
                yield Button("No", id="btn-no", classes="close-button")
    
    def on_mount(self) -> None:
        self.query_one("#btn-no").focus()
    
    def on_button_pressed(self, event) -> None:
        if event.button.id == "btn-yes":
            self.dismiss(True)
        else:
            self.dismiss(False)
    
    def action_confirm(self) -> None:
        self.dismiss(True)
    
    def action_cancel(self) -> None:
        self.dismiss(False)
    
    def action_focus_previous(self) -> None:
        self.focus_previous()
    
    def action_focus_next(self) -> None:
        self.focus_next()
