"""Modal screens for Impromptu UI."""

from textual.app import ComposeResult
from textual.widgets import Static, ListView, ListItem, Label, Input
from textual.containers import Vertical, Horizontal
from textual.screen import ModalScreen


class AgentSelectItem(ListItem):
    """A list item for agent selection in the modal."""

    def __init__(self, name: str, command: str) -> None:
        super().__init__()
        self.agent_name = name
        self.command = command

    def compose(self) -> ComposeResult:
        yield Label(f"{self.agent_name}")


class AgentSelectModal(ModalScreen[tuple[str, str] | None]):
    """Modal for selecting which agent to start in a new pane."""
    
    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("j", "cursor_down", "Down"),
        ("k", "cursor_up", "Up"),
    ]
    
    def __init__(self, agents: list[tuple[str, str]]) -> None:
        super().__init__()
        self.agents = agents
    
    def compose(self) -> ComposeResult:
        with Vertical(id="modal-box"):
            yield Static("Select Agent", id="modal-title")
            with ListView(id="agent-list"):
                for agent in self.agents:
                    yield AgentSelectItem(agent[0], agent[1])
                yield AgentSelectItem("Empty Shell", "")
                item = AgentSelectItem("[Cancel]", "__CANCEL__")
                item.add_class("muted")
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
        self.query_one("#agent-list", ListView).action_cursor_down()
    
    def action_cursor_up(self) -> None:
        self.query_one("#agent-list", ListView).action_cursor_up()


class ShortcutsModal(ModalScreen[None]):
    """Modal showing keyboard shortcuts."""
    
    BINDINGS = [("escape", "close", "Close")]
    
    def compose(self) -> ComposeResult:
        with Vertical(id="modal-box"):
            yield Static("Keyboard Shortcuts", id="modal-title")
            yield Static("")
            yield Static("[b]Navigation[/]")
            yield Static("[cyan]j/k[/]       Move up/down")
            yield Static("[cyan]Tab[/]       Focus agent pane")
            yield Static("[cyan]Enter[/]     Select agent")
            yield Static("")
            yield Static("[b]Agents[/]")
            yield Static("[cyan]n[/]         New agent")
            yield Static("[cyan]r[/]         Rename agent")
            yield Static("[cyan]i[/]         Import pane")
            yield Static("[cyan]w[/]         Close agent")
            yield Static("[cyan]1-9[/]       Switch to agent")
            yield Static("")
            yield Static("[b]Other[/]")
            yield Static("[cyan]q[/]         Quit")
            yield Static("[cyan]?[/]         This help")
            yield Static("[cyan]Esc[/]       Close")
    
    def action_close(self) -> None:
        self.dismiss(None)


class RenameModal(ModalScreen[str | None]):
    """Modal for renaming an agent pane."""
    
    BINDINGS = [("escape", "cancel", "Cancel")]
    
    def __init__(self, current_name: str) -> None:
        super().__init__()
        self.current_name = current_name
    
    def compose(self) -> ComposeResult:
        with Vertical(id="modal-box"):
            yield Static("Rename Agent", id="modal-title")
            yield Static("")
            yield Input(value=self.current_name, id="modal-input")
            yield Static("")
            yield Static("[dim]Enter to confirm, Esc to cancel[/]", id="modal-hint")
    
    def on_input_submitted(self, event: Input.Submitted) -> None:
        new_name = event.value.strip()
        self.dismiss(new_name if new_name else None)
    
    def action_cancel(self) -> None:
        self.dismiss(None)


class QuitConfirmModal(ModalScreen[bool]):
    """Modal to confirm quitting impromptu."""
    
    BINDINGS = [
        ("enter", "confirm", "Confirm"),
        ("escape", "cancel", "Cancel"),
    ]
    
    def compose(self) -> ComposeResult:
        with Vertical(id="modal-box"):
            yield Static("Quit Impromptu?", id="modal-title")
            yield Static("")
            yield Static("This will close all agent panes.")
            yield Static("")
            yield Static("[dim]Enter[/] yes  [dim]Esc[/] no", id="modal-hint")
    
    def action_confirm(self) -> None:
        self.dismiss(True)
    
    def action_cancel(self) -> None:
        self.dismiss(False)
    
    def action_focus_previous(self) -> None:
        self.focus_previous()
    
    def action_focus_next(self) -> None:
        self.focus_next()


class SetupCommandModal(ModalScreen[str]):
    """Modal for entering an optional setup command."""
    
    BINDINGS = [("escape", "skip", "Skip")]
    
    def __init__(self, agent_name: str) -> None:
        super().__init__()
        self.agent_name = agent_name
    
    def compose(self) -> ComposeResult:
        with Vertical(id="modal-box"):
            yield Static(f"Setup: {self.agent_name}", id="modal-title")
            yield Static("")
            yield Input(placeholder="Setup command (optional)", id="modal-input")
            yield Static("")
            yield Static("[dim]Enter to continue, Esc to skip[/]", id="modal-hint")
    
    def action_skip(self) -> None:
        self.dismiss("")
    
    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)


class CloseAgentModal(ModalScreen[bool]):
    """Modal to confirm closing an agent."""
    
    def __init__(self, agent_name: str) -> None:
        super().__init__()
        self.agent_name = agent_name
    
    BINDINGS = [
        ("enter", "confirm", "Confirm"),
        ("escape", "cancel", "Cancel"),
    ]
    
    def compose(self) -> ComposeResult:
        with Vertical(id="modal-box"):
            yield Static(f"Close {self.agent_name}?", id="modal-title")
            yield Static("")
            yield Static("This will terminate the agent.")
            yield Static("")
            yield Static("[dim]Enter[/] yes  [dim]Esc[/] no", id="modal-hint")
    
    def action_confirm(self) -> None:
        self.dismiss(True)
    
    def action_cancel(self) -> None:
        self.dismiss(False)
    
    def action_focus_previous(self) -> None:
        self.focus_previous()
    
    def action_focus_next(self) -> None:
        self.focus_next()
