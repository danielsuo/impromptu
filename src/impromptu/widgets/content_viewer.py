"""Widget to display agent's context (files, code, etc.)."""

from textual.app import ComposeResult
from textual.widgets import Static, TabbedContent, TabPane, Markdown, TextArea
from textual.containers import Vertical

from ..models import Agent, ContextItem, ContextType
from ..agent_manager import AgentManager


class ContentViewer(Static):
    """Displays the context items of the selected agent."""

    DEFAULT_CSS = """
    ContentViewer {
        height: 100%;
        background: $surface;
        padding: 1;
    }

    ContentViewer > #content-title {
        text-style: bold;
        padding-bottom: 1;
        color: $text;
    }

    ContentViewer > TabbedContent {
        height: 1fr;
    }

    ContentViewer TabPane {
        padding: 1;
    }

    ContentViewer .empty-state {
        color: $text-muted;
        text-align: center;
        padding: 2;
    }
    """

    def __init__(self, manager: AgentManager) -> None:
        super().__init__()
        self.manager = manager
        self._tabbed_content: TabbedContent | None = None
        self._current_agent_id: str | None = None

    def compose(self) -> ComposeResult:
        yield Static("📁 Context", id="content-title")
        yield Static("Select an agent to view context", classes="empty-state")

    def show_agent(self, agent: Agent) -> None:
        """Show the context for a specific agent."""
        self._current_agent_id = agent.id
        self._update_display(agent)

    def _update_display(self, agent: Agent) -> None:
        """Update the display with agent's context."""
        # Remove existing content
        for child in list(self.children):
            if child.id != "content-title":
                child.remove()

        if not agent.context:
            self.mount(Static("No context items", classes="empty-state"))
            return

        # Create tabbed content for context items
        tabbed = TabbedContent()
        self.mount(tabbed)

        for i, item in enumerate(agent.context):
            pane = TabPane(item.path, id=f"context-{i}")

            if item.type == ContextType.MARKDOWN:
                pane.compose_add_child(Markdown(item.content))
            elif item.type == ContextType.CODE:
                text_area = TextArea(
                    item.content,
                    language=item.language or "python",
                    read_only=True,
                    show_line_numbers=True,
                )
                pane.compose_add_child(text_area)
            else:
                pane.compose_add_child(Static(item.content))

            tabbed.add_pane(pane)
