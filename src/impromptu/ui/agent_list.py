"""Agent list item components for Impromptu UI."""

from textual.app import ComposeResult
from textual.widgets import ListItem, Label


class AgentItem(ListItem):
    """A list item representing an agent with message preview."""

    STATUS_ICONS = {
        "idle": "🟢",
        "busy": "🟡",
        "blocked": "🔴",
    }

    def __init__(self, name: str, index: int, status: str = "idle", 
                 active: bool = False, messages: list | None = None,
                 num_lines: int = 2) -> None:
        super().__init__()
        self.agent_name = name
        self.agent_index = index
        self.status = status
        self.is_active = active
        self.messages = messages or []
        self.num_lines = num_lines
        if active:
            self.add_class("active-agent")

    def compose(self) -> ComposeResult:
        icon = self.STATUS_ICONS.get(self.status, "⚪")
        yield Label(f"[{self.agent_index + 1}] {icon} {self.agent_name}", classes="agent-header")
        for i in range(self.num_lines):
            msg = self.messages[i] if i < len(self.messages) else ""
            # Messages are (role, content) tuples - extract content with role indicator
            if isinstance(msg, tuple):
                role, content = msg[0], msg[1]
                # continuation = wrapped line, just indentation
                if role == "continuation":
                    text = f"  {content}"
                else:
                    prefix = "› " if role == "user" else "‹ " if role == "gemini" else "  "
                    text = f"{prefix}{content}"
            else:
                text = msg
            yield Label(text, classes="agent-message")

