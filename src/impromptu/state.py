"""Centralized UI state management with reactive pub/sub pattern."""

from dataclasses import dataclass, field
from typing import Callable
import time


@dataclass
class AgentUIState:
    """UI state for a single agent."""
    pane_id: str
    name: str
    status: str = "idle"  # "idle", "busy", "thinking", "ready"
    messages: list[tuple[str, str]] = field(default_factory=list)  # (role, content) tuples
    pinned_message: tuple[str, str] | None = None  # User prompt pinned to first line
    num_lines: int = 2  # Number of message lines to display
    
    def copy(self) -> "AgentUIState":
        """Create a shallow copy."""
        return AgentUIState(
            pane_id=self.pane_id,
            name=self.name,
            status=self.status,
            messages=list(self.messages),
            pinned_message=self.pinned_message,
            num_lines=self.num_lines
        )


@dataclass 
class Notification:
    """A notification with expiration time."""
    message: str
    expire_time: float  # Unix timestamp
    id: int


@dataclass
class UIState:
    """Complete UI state - single source of truth."""
    agents: list[AgentUIState] = field(default_factory=list)
    active_index: int = 0
    notifications: list[Notification] = field(default_factory=list)
    current_agent_name: str = ""

    def copy(self) -> "UIState":
        """Create a deep copy of state."""
        return UIState(
            agents=[a.copy() for a in self.agents],
            active_index=self.active_index,
            notifications=list(self.notifications),
            current_agent_name=self.current_agent_name
        )


# Type alias for state change callback
StateCallback = Callable[["UIState", "UIState"], None]


class StateStore:
    """Reactive state store with pub/sub pattern.
    
    The store is the single source of truth for all UI components.
    """
    
    def __init__(self):
        self._state = UIState()
        self._subscribers: list[StateCallback] = []
        self._notification_id = 0
    
    @property
    def state(self) -> UIState:
        """Get CURRENT state."""
        return self._state
    
    def subscribe(self, callback: StateCallback) -> Callable[[], None]:
        """Subscribe to state changes. Returns unsubscribe function."""
        self._subscribers.append(callback)
        return lambda: self._subscribers.remove(callback)
    
    def _notify(self, old_state: UIState) -> None:
        """Notify all subscribers of state change."""
        # Use debug logging to track hangs
        log_file = "/tmp/state_store.log"
        try:
            with open(log_file, "a") as f:
                f.write(f"[{time.time()}] _notify start\n")
            for i, callback in enumerate(self._subscribers):
                try:
                    callback(old_state, self._state)
                except Exception as e:
                    with open(log_file, "a") as f:
                        f.write(f"[{time.time()}] subscriber {i} failed: {e}\n")
            with open(log_file, "a") as f:
                f.write(f"[{time.time()}] _notify end\n")
        except Exception:
            pass
            
    def update(self, **changes) -> None:
        """Update top-level state fields."""
        old_state = self._state.copy()
        for key, value in changes.items():
            if hasattr(self._state, key):
                setattr(self._state, key, value)
        self._notify(old_state)

    def add_agent(self, pane_id: str, name: str, status: str = "idle", 
                  messages: list = None, num_lines: int = 2) -> None:
        """Add a new agent to state."""
        old_state = self._state.copy()
        new_agent = AgentUIState(
            pane_id=pane_id, name=name, status=status, 
            messages=messages or [], num_lines=num_lines
        )
        self._state.agents.append(new_agent)
        # Set new agent as active if it's the first or we want it active
        self._state.active_index = len(self._state.agents) - 1
        self._notify(old_state)

    def remove_agent(self, pane_id: str) -> None:
        """Remove an agent from state."""
        old_state = self._state.copy()
        self._state.agents = [a for a in self._state.agents if a.pane_id != pane_id]
        
        # Adjust active_index
        if self._state.active_index >= len(self._state.agents):
            self._state.active_index = max(0, len(self._state.agents) - 1)
        
        self._notify(old_state)

    def set_active_agent(self, index: int) -> None:
        """Change the active agent index."""
        if 0 <= index < len(self._state.agents):
            old_state = self._state.copy()
            self._state.active_index = index
            self._notify(old_state)

    def update_agent(self, pane_id: str, **changes) -> None:
        """Update a specific agent's state."""
        old_state = self._state.copy()
        found = False
        for agent in self._state.agents:
            if agent.pane_id == pane_id:
                for key, value in changes.items():
                    if hasattr(agent, key):
                        setattr(agent, key, value)
                found = True
                break
        if found:
            self._notify(old_state)

    def add_notification(self, message: str, duration: float = 3.0) -> None:
        """Add a temporary notification."""
        old_state = self._state.copy()
        
        n_id = self._notification_id
        self._notification_id += 1
        
        notif = Notification(
            message=message,
            expire_time=time.time() + duration,
            id=n_id
        )
        self._state.notifications.append(notif)
        self._notify(old_state)

    def clean_notifications(self) -> None:
        """Remove expired notifications."""
        old_state = self._state.copy()
        now = time.time()
        initial_len = len(self._state.notifications)
        self._state.notifications = [n for n in self._state.notifications if n.expire_time > now]
        
        if len(self._state.notifications) != initial_len:
            self._notify(old_state)
