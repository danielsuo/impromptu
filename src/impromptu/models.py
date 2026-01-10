"""Data models for the multi-agent TUI."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class AgentStatus(Enum):
    """Status of an agent."""
    IDLE = "idle"
    THINKING = "thinking"
    READY = "ready"  # Agent has output ready, triggers notification
    ERROR = "error"


class ContextType(Enum):
    """Type of context item."""
    MARKDOWN = "markdown"
    CODE = "code"
    IMAGE = "image"
    TEXT = "text"


@dataclass
class ContextItem:
    """A piece of context an agent is working with."""
    type: ContextType
    path: str
    content: str
    language: Optional[str] = None  # For code files


@dataclass
class Agent:
    """Represents an AI agent."""
    id: str
    name: str
    status: AgentStatus = AgentStatus.IDLE
    thinking: str = ""  # Current thinking stream
    context: list[ContextItem] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def status_icon(self) -> str:
        """Return an icon for the current status."""
        icons = {
            AgentStatus.IDLE: "⚪",
            AgentStatus.THINKING: "🟡",
            AgentStatus.READY: "🟢",
            AgentStatus.ERROR: "🔴",
        }
        return icons.get(self.status, "⚪")
