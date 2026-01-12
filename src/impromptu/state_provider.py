"""Agent state detection with abstract provider interface.

Supports multiple agent types (gemini, claude) via pluggable state providers.
"""

from enum import Enum
from pathlib import Path
from typing import Protocol, Optional
from abc import ABC, abstractmethod


class AgentState(Enum):
    """Agent operational states for UI display."""
    IDLE = "idle"       # White - waiting on user input, not blocked
    BUSY = "busy"       # Yellow - agent is working/processing
    BLOCKED = "blocked" # Red - waiting on user input to continue (e.g., tool approval)


class AgentStateProvider(Protocol):
    """Abstract interface for agent state detection.
    
    Implement this protocol for each agent type (gemini, claude, etc).
    """
    
    def get_state(self, agent_id: str) -> AgentState:
        """Get current agent state."""
        ...
    
    def update_state(self, agent_id: str, state: AgentState) -> None:
        """Update agent state (called by hooks or polling)."""
        ...


class FileBasedStateProvider(ABC):
    """Base class for state providers that use file-based communication.
    
    Hooks write state to files, polling reads from files.
    Uses caching to avoid excessive file I/O.
    """
    
    STATE_FILE = Path("/tmp/impromptu_agent_state.txt")
    CACHE_TTL = 0.05  # 50ms cache - fast enough for UI, reduces I/O
    
    def __init__(self):
        self._states: dict[str, AgentState] = {}
        self._last_load_time: float = 0.0
        self._last_mtime: float = 0.0
    
    def _load_states_if_changed(self) -> None:
        """Load states from file only if file changed."""
        import time
        
        # Check if enough time has passed since last load
        now = time.time()
        if now - self._last_load_time < self.CACHE_TTL:
            return
        
        self._last_load_time = now
        
        if not self.STATE_FILE.exists():
            return
        
        try:
            # Only reload if file actually changed
            stat = self.STATE_FILE.stat()
            if stat.st_mtime == self._last_mtime:
                return
            self._last_mtime = stat.st_mtime
            
            with open(self.STATE_FILE, 'r') as f:
                for line in f:
                    line = line.strip()
                    if '=' in line:
                        agent_id, state_str = line.split('=', 1)
                        try:
                            self._states[agent_id] = AgentState(state_str)
                        except ValueError:
                            pass
        except Exception:
            pass
    
    def get_state(self, agent_id: str) -> AgentState:
        """Get current agent state, using cached value when possible."""
        self._load_states_if_changed()
        return self._states.get(agent_id, AgentState.IDLE)
    
    def update_state(self, agent_id: str, state: AgentState) -> None:
        """Update agent state in memory and file."""
        self._states[agent_id] = state
        self._save_states()
    
    def _save_states(self) -> None:
        """Save states to file."""
        try:
            with open(self.STATE_FILE, 'w') as f:
                for agent_id, state in self._states.items():
                    f.write(f"{agent_id}={state.value}\n")
        except Exception:
            pass


class GeminiStateProvider(FileBasedStateProvider):
    """State provider for Gemini CLI agents.
    
    Uses gemini-cli hooks to detect state:
    - BeforeAgent → BUSY (agent starts processing)
    - AfterAgent → IDLE (agent finished)
    - Notification(ToolPermission) → BLOCKED (waiting for approval)
    """
    pass  # Uses base implementation


class ClaudeStateProvider(FileBasedStateProvider):
    """State provider for Claude Code agents.
    
    TODO: Implement when Claude Code integration is added.
    Could use similar hook mechanism or Claude's native state detection.
    """
    pass  # Uses base implementation for now


# Singleton instances
_gemini_provider: Optional[GeminiStateProvider] = None
_claude_provider: Optional[ClaudeStateProvider] = None


def get_gemini_state_provider() -> GeminiStateProvider:
    """Get singleton Gemini state provider."""
    global _gemini_provider
    if _gemini_provider is None:
        _gemini_provider = GeminiStateProvider()
    return _gemini_provider


def get_claude_state_provider() -> ClaudeStateProvider:
    """Get singleton Claude state provider."""
    global _claude_provider
    if _claude_provider is None:
        _claude_provider = ClaudeStateProvider()
    return _claude_provider
