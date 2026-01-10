"""Chat input widget for sending messages to agents."""

from textual.app import ComposeResult
from textual.widgets import Static, Input
from textual.containers import Horizontal
from textual.message import Message


class ChatInput(Static):
    """Input widget for sending messages to the selected agent."""

    DEFAULT_CSS = """
    ChatInput {
        height: 3;
        dock: bottom;
        background: $surface;
        border-top: solid $primary;
        padding: 0 1;
    }

    ChatInput > #prompt-label {
        width: 3;
        padding-top: 1;
    }

    ChatInput > Input {
        width: 1fr;
    }
    """

    class MessageSubmitted(Message):
        """Message sent when user submits input."""

        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    def compose(self) -> ComposeResult:
        yield Static("❯ ", id="prompt-label")
        yield Input(placeholder="Send a message to the agent...", id="chat-input")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle input submission."""
        text = event.value.strip()
        if text:
            self.post_message(self.MessageSubmitted(text))
            event.input.value = ""

    def focus_input(self) -> None:
        """Focus the input field."""
        self.query_one("#chat-input", Input).focus()
