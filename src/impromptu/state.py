"""Centralized UI state management with reactive pub/sub pattern."""

from dataclasses import dataclass, field
from typing import Callable, Optional
import time
import copy


@dataclass
class AgentUIState:
    """UI state for a single agent."""
    pane_id: str
    name: str
    status: str = "idle"  # "idle", "thinking", "ready", "active"
    messages: list[str] = field(default_factory=list)  # Recent message previews
    
    def copy(self) -> "AgentUIState":
        """Create a shallow copy."""
        return AgentUIState(
            pane_id=self.pane_id,
            name=self.name,
            status=self.status,
            messages=list(self.messages)
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
    
    Usage:
        store = StateStore()
        
        # Subscribe to changes
        store.subscribe(lambda old, new: print(f"State changed"))
        
        # Update state
        store.update(active_index=1)
        store.update_agent("pane-123", status="thinking")
        store.add_notification("Hello!")
    """
    
    def __init__(self):
        self._state = UIState()
        self._subscribers: list[StateCallback] = []
        self._notification_id = 0
    
    @property
    def state(self) -> UIState:
        """Get current state (read-only view)."""
        return self._state
    

    def subscribe(self, callback: StateCallback) -> Callable[[], None]:
        """Subscribe to state changes.
        
        Args:
            callback: Function called with (old_state, new_state) on changes
            
        Returns:
            Unsubscribe function
        """
        self._subscribers.append(callback)
        return lambda: self._subscribers.remove(callback)
    
    def _notify(self, old_state: UIState) -> None:
        """Notify all subscribers of state change."""
        for callback in self._subscribers:
            try:
                callback(old_state, self._state)
            except Exception:
                pass  # Don't let one subscriber break others
    
    def update(self, **changes) -> None:
        """Update top-level state fields.
        
        Args:
            **changes: Fields to update (active_index, current_agent_name, etc.)
        """
        old_state = self._state.copy()
        
        for key, value in changes.items():
            if hasattr(self._state, key):
                setattr(self._state, key, value)
        
        self._notify(old_state)
    
    def add_agent(self, pane_id: str, name: str, status: str = "idle", 
                  messages: list[str] | None = None) -> None:
        """Add a new agent to state."""
        old_state = self._state.copy()
        
        agent = AgentUIState(
            pane_id=pane_id,
            name=name,
            status=status,
            messages=messages or []
        )
        self._state.agents.append(agent)
        
        self._notify(old_state)
    
    def remove_agent(self, pane_id: str) -> None:
        """Remove an agent from state."""
        old_state = self._state.copy()
        
        self._state.agents = [a for a in self._state.agents if a.pane_id != pane_id]
        
        # Adjust active_index if needed
        if self._state.active_index >= len(self._state.agents):
            self._state.active_index = max(0, len(self._state.agents) - 1)
        
        self._notify(old_state)
    
    def update_agent(self, pane_id: str, **changes) -> None:
        """Update a specific agent's state.
        
        Args:
            pane_id: The agent's pane ID
            **changes: Fields to update (status, messages, name, etc.)
        """
        old_state = self._state.copy()
        
        for agent in self._state.agents:
            if agent.pane_id == pane_id:
                for key, value in changes.items():
                    if hasattr(agent, key):
                        setattr(agent, key, value)
                break
        
        self._notify(old_state)
    
    def get_agent(self, pane_id: str) -> Optional[AgentUIState]:
        """Get agent state by pane ID."""
        for agent in self._state.agents:
            if agent.pane_id == pane_id:
                return agent
        return None
    
    def get_agent_by_index(self, index: int) -> Optional[AgentUIState]:
        """Get agent state by index."""
        if 0 <= index < len(self._state.agents):
            return self._state.agents[index]
        return None
    
    def add_notification(self, message: str, duration: float = 5.0) -> None:
        """Add a notification that expires after duration seconds."""
        old_state = self._state.copy()
        
        notification = Notification(
            message=message,
            expire_time=time.time() + duration,
            id=self._notification_id
        )
        self._notification_id += 1
        self._state.notifications.append(notification)
        
        # Keep only last 3 notifications
        if len(self._state.notifications) > 3:
            self._state.notifications = self._state.notifications[-3:]
        
        self._notify(old_state)
    
    def expire_notifications(self) -> bool:
        """Remove expired notifications. Returns True if any were removed."""
        now = time.time()
        before_count = len(self._state.notifications)
        
        expired = [n for n in self._state.notifications if now >= n.expire_time]
        if expired:
            old_state = self._state.copy()
            self._state.notifications = [n for n in self._state.notifications 
                                         if now < n.expire_time]
            self._notify(old_state)
            return True
        return False
    
    def set_active_agent(self, index: int) -> None:
        """Set the active agent by index."""
        if 0 <= index < len(self._state.agents):
            old_state = self._state.copy()
            self._state.active_index = index
            
            # Update current agent name
            self._state.current_agent_name = self._state.agents[index].name
            
            # Mark active agent's status
            for i, agent in enumerate(self._state.agents):
                if i == index:
                    agent.status = "active"
                elif agent.status == "active":
                    agent.status = "idle"
            
            self._notify(old_state)
