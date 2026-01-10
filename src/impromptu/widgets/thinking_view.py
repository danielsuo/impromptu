"""Widget to display agent's thinking stream."""

from textual.app import ComposeResult
from textual.widgets import Static, RichLog
from textual.containers import Vertical
from rich.markdown import Markdown

from ..models import Agent
from ..agent_manager import AgentManager


class ThinkingView(Static):
    """Displays the thinking stream of the selected agent."""

    DEFAULT_CSS = """
    ThinkingView {
        height: 100%;
        background: $surface;
        padding: 1;
    }

    ThinkingView > #thinking-title {
        text-style: bold;
        padding-bottom: 1;
        color: $text;
    }

    ThinkingView > RichLog {
        height: 1fr;
        background: $background;
        border: solid $primary;
        padding: 1;
    }
    """

    def __init__(self, manager: AgentManager) -> None:
        super().__init__()
        self.manager = manager
        self._log: RichLog | None = None
        self._current_agent_id: str | None = None

    def compose(self) -> ComposeResult:
        yield Static("💭 Thinking", id="thinking-title")
        self._log = RichLog(highlight=True, markup=True)
        yield self._log

    def on_mount(self) -> None:
        """Subscribe to agent updates."""
        self.manager.subscribe(self._on_agent_update)

    def show_agent(self, agent: Agent) -> None:
        """Show the thinking for a specific agent."""
        self._current_agent_id = agent.id
        self._update_display(agent)

    def _on_agent_update(self, agent: Agent) -> None:
        """Handle agent updates."""
        if agent.id == self._current_agent_id:
            self._update_display(agent)

    def _update_display(self, agent: Agent) -> None:
        """Update the display with agent's thinking."""
        if not self._log:
            return

        self._log.clear()
        if agent.thinking:
            self._log.write(f"[bold]{agent.name}[/bold] ({agent.status.value})\n")
            self._log.write(agent.thinking)
        else:
            self._log.write(f"[dim]{agent.name} is idle...[/dim]")
