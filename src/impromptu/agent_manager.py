"""Agent manager service for the multi-agent TUI."""

import asyncio
import random
from typing import Callable, Optional

from .models import Agent, AgentStatus, ContextItem, ContextType


class AgentManager:
    """Manages multiple agents and their state."""

    def __init__(self):
        self._agents: dict[str, Agent] = {}
        self._subscribers: list[Callable[[Agent], None]] = []
        self._selected_agent_id: Optional[str] = None

    def register_agent(self, agent: Agent) -> None:
        """Register a new agent."""
        self._agents[agent.id] = agent
        self._notify_subscribers(agent)

    def get_agents(self) -> list[Agent]:
        """Get all registered agents."""
        return list(self._agents.values())

    def get_agent(self, agent_id: str) -> Optional[Agent]:
        """Get a specific agent by ID."""
        return self._agents.get(agent_id)

    def select_agent(self, agent_id: str) -> None:
        """Select an agent as the active one."""
        if agent_id in self._agents:
            self._selected_agent_id = agent_id
            self._notify_subscribers(self._agents[agent_id])

    def get_selected_agent(self) -> Optional[Agent]:
        """Get the currently selected agent."""
        if self._selected_agent_id:
            return self._agents.get(self._selected_agent_id)
        return None

    def update_agent_status(self, agent_id: str, status: AgentStatus) -> None:
        """Update an agent's status."""
        if agent := self._agents.get(agent_id):
            agent.status = status
            self._notify_subscribers(agent)

    def update_agent_thinking(self, agent_id: str, thinking: str) -> None:
        """Update an agent's thinking stream."""
        if agent := self._agents.get(agent_id):
            agent.thinking = thinking
            self._notify_subscribers(agent)

    def subscribe(self, callback: Callable[[Agent], None]) -> None:
        """Subscribe to agent updates."""
        self._subscribers.append(callback)

    def _notify_subscribers(self, agent: Agent) -> None:
        """Notify all subscribers of an agent update."""
        for callback in self._subscribers:
            callback(agent)


def create_mock_agents() -> list[Agent]:
    """Create mock agents for development."""
    return [
        Agent(
            id="gemini",
            name="Gemini CLI",
            status=AgentStatus.IDLE,
            thinking="Ready to assist. Send a message to start.",
            context=[],
        ),
        Agent(
            id="agent-1",
            name="Code Assistant",
            status=AgentStatus.IDLE,
            thinking="",
            context=[
                ContextItem(
                    type=ContextType.CODE,
                    path="main.py",
                    content="def hello():\n    print('Hello, World!')",
                    language="python",
                )
            ],
        ),
        Agent(
            id="agent-2",
            name="Research Agent",
            status=AgentStatus.THINKING,
            thinking="Analyzing the codebase structure...\n\nFound 3 Python files in src/tui/:\n- main.py\n- config.py\n- models.py",
            context=[
                ContextItem(
                    type=ContextType.MARKDOWN,
                    path="README.md",
                    content="# TUI Project\n\nA multi-agent management interface.",
                )
            ],
        ),
        Agent(
            id="agent-3",
            name="Documentation Writer",
            status=AgentStatus.READY,
            thinking="Documentation complete! Ready for review.",
            context=[],
        ),
    ]


async def simulate_agent_activity(manager: AgentManager) -> None:
    """Simulate agent activity for demo purposes."""
    thinking_phrases = [
        "Analyzing the request...",
        "Searching through files...",
        "Found relevant code...",
        "Generating response...",
        "Almost done...",
    ]

    while True:
        await asyncio.sleep(random.uniform(2, 5))

        agents = manager.get_agents()
        if not agents:
            continue

        agent = random.choice(agents)

        # Simulate status changes
        if agent.status == AgentStatus.IDLE:
            manager.update_agent_status(agent.id, AgentStatus.THINKING)
            manager.update_agent_thinking(agent.id, random.choice(thinking_phrases))
        elif agent.status == AgentStatus.THINKING:
            # Add more thinking
            new_thinking = agent.thinking + "\n" + random.choice(thinking_phrases)
            manager.update_agent_thinking(agent.id, new_thinking)

            # Sometimes become ready
            if random.random() > 0.7:
                manager.update_agent_status(agent.id, AgentStatus.READY)
        elif agent.status == AgentStatus.READY:
            # Go back to idle after a while
            manager.update_agent_status(agent.id, AgentStatus.IDLE)
            manager.update_agent_thinking(agent.id, "")
