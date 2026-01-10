"""Agent sidebar widget showing all agents with status."""

from textual.app import ComposeResult
from textual.widgets import Static, ListView, ListItem, Label
from textual.containers import Vertical
from textual.reactive import reactive
from textual.message import Message

from ..models import Agent, AgentStatus
from ..agent_manager import AgentManager


class AgentListItem(ListItem):
    """A list item representing an agent."""

    def __init__(self, agent: Agent) -> None:
        super().__init__()
        self.agent = agent

    def compose(self) -> ComposeResult:
        yield Label(f"{self.agent.status_icon} {self.agent.name}")


class AgentSidebar(Static):
    """Sidebar showing all agents with their status."""

    DEFAULT_CSS = """
    AgentSidebar {
        width: 30;
        height: 100%;
        background: $surface;
        border-right: solid $primary;
        padding: 1;
    }

    AgentSidebar > #sidebar-title {
        text-style: bold;
        padding-bottom: 1;
        color: $text;
    }

    AgentSidebar ListView {
        height: auto;
        background: transparent;
    }

    AgentSidebar ListItem {
        padding: 0 1;
        height: 3;
    }

    AgentSidebar ListItem:hover {
        background: $primary 20%;
    }

    AgentSidebar ListItem.-selected {
        background: $primary 40%;
    }
    """

    class AgentSelected(Message):
        """Message sent when an agent is selected."""

        def __init__(self, agent: Agent) -> None:
            super().__init__()
            self.agent = agent

    def __init__(self, manager: AgentManager) -> None:
        super().__init__()
        self.manager = manager
        self._list_view: ListView | None = None

    def compose(self) -> ComposeResult:
        yield Label("🤖 Agents", id="sidebar-title")
        self._list_view = ListView()
        yield self._list_view

    def on_mount(self) -> None:
        """Populate the list when mounted."""
        self._refresh_agents()
        self.manager.subscribe(self._on_agent_update)

    def _refresh_agents(self) -> None:
        """Refresh the agent list."""
        if not self._list_view:
            return

        self._list_view.clear()
        for agent in self.manager.get_agents():
            self._list_view.append(AgentListItem(agent))

    def _on_agent_update(self, agent: Agent) -> None:
        """Handle agent updates by refreshing the list."""
        self._refresh_agents()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle agent selection."""
        if isinstance(event.item, AgentListItem):
            self.manager.select_agent(event.item.agent.id)
            self.post_message(self.AgentSelected(event.item.agent))
