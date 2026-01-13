"""Data models for the multi-agent TUI."""

import uuid as uuid_module
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


class AgentStatus(Enum):
    """Agent operational states for UI display.
    
    Consolidated from AgentStatus + AgentState.
    """
    IDLE = "idle"       # White - waiting for user input
    BUSY = "busy"       # Yellow - agent is working/processing
    BLOCKED = "blocked" # Red - waiting on user approval (e.g., tool permission)
    READY = "ready"     # Green - agent has output ready
    ERROR = "error"     # Error state


class AgentType(Enum):
    """Type of agent."""
    GENERIC = "generic"
    GEMINI = "gemini"
    CLAUDE = "claude"


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
    """Base agent with pane tracking."""
    id: str
    name: str
    agent_type: AgentType = AgentType.GENERIC
    pane_id: Optional[str] = None  # tmux pane ID
    _command: str = ""  # Command to launch this agent
    status: AgentStatus = AgentStatus.IDLE
    thinking: str = ""  # Current thinking stream
    context: list[ContextItem] = field(default_factory=list)
    error: Optional[str] = None
    last_updated: float = 0.0  # Inlined from AgentState

    @property
    def status_icon(self) -> str:
        """Return an icon for the current status."""
        icons = {
            AgentStatus.IDLE: "⚪",
            AgentStatus.BUSY: "🟡",
            AgentStatus.BLOCKED: "🔴",
            AgentStatus.READY: "🟢",
            AgentStatus.ERROR: "🔴",
        }
        return icons.get(self.status, "⚪")
    
    @property
    def socket_path(self) -> Path:
        """Path to this agent's Unix domain socket for hook IPC."""
        # Use self.id for base Agent, GeminiAgent overrides with uuid field
        agent_id = getattr(self, 'uuid', self.id)
        return Path(f"/tmp/impromptu_sockets/{agent_id}.sock")
    
    def handle_hook(self, message: dict) -> tuple[Optional[AgentStatus], Optional[tuple[str, str]]]:
        """Handle a hook message from Gemini CLI.
        
        Args:
            message: JSON message from hook (contains hook_event_name, etc.)
            
        Returns:
            Tuple of (new_status, message_tuple) where:
            - new_status: AgentStatus to set, or None if unchanged
            - message_tuple: (role, content) to add to messages, or None
            
        Override in subclasses for agent-specific handling.
        """
        return None, None
    
    def init(self, project_dir: str) -> None:
        """Initialize agent. Override in subclasses."""
        pass
    
    def get_cli_command(self) -> str:
        """Get command to launch this agent's CLI. Override in subclasses."""
        return ""
    
    @classmethod
    def from_config(cls, table: dict) -> "Agent":
        """Factory method to create an agent from a TOML config table.
        
        Args:
            table: Dict with keys: name, path, flags (optional), agent_type
            
        Returns:
            Appropriate Agent subclass based on agent_type
        """
        
        name = table.get("name", "unnamed")
        path = table.get("path", "bash")
        flags = table.get("flags", "")
        agent_type = table.get("agent_type", "shell")
        
        # Build command
        command = f"{path} {flags}".strip() if flags else path
        
        agent_id = str(uuid_module.uuid4())
        
        if agent_type == "gemini":
            agent = GeminiAgent(id=agent_id, name=name, pane_id=None)
            agent._command = command
            return agent
        else:
            # Generic shell agent
            agent = Agent(id=agent_id, name=name, pane_id=None)
            agent._command = command
            return agent




@dataclass
class GeminiAgent(Agent):
    """Gemini CLI agent with hook-based state tracking."""
    agent_type: AgentType = field(default=AgentType.GEMINI)
    
    # Unique identifier for this agent (used for socket IPC)
    uuid: str = field(default_factory=lambda: str(uuid_module.uuid4()))
    
    # Session ID from Gemini CLI (set via SessionStart hook)
    session_id: Optional[str] = None
    
    def handle_hook(self, message: dict) -> tuple[Optional[AgentStatus], Optional[tuple[str, str]]]:
        """Handle hook messages from Gemini CLI.
        
        Status transitions:
        - BeforeAgent: → BUSY (yellow) - stays yellow until AfterAgent
        - AfterAgent: → IDLE (white)
        - Notification(ToolPermission): → BLOCKED (red)
        - Other Notification: → IDLE (white, clears blocked)
        
        All events extract messages for display.
        
        Returns:
            Tuple of (new_status, message_tuple)
        """
        event = message.get('hook_event_name', '')
        new_status: Optional[AgentStatus] = None
        new_message: Optional[tuple[str, str]] = None
        
        if event == 'SessionStart':
            # Session started - extract session_id for correlation
            session_id = message.get('session_id')
            if session_id and not self.session_id:
                self.session_id = session_id
            # No status change, no message
        
        elif event == 'BeforeAgent':
            # User submitted a prompt - agent starts working (yellow)
            new_status = AgentStatus.BUSY
            prompt = message.get('prompt', '')
            if prompt:
                display_text = prompt[:50] + '...' if len(prompt) > 50 else prompt
                new_message = ('user', display_text)
        
        elif event == 'BeforeModel':
            # About to call LLM - no status change (stay yellow)
            new_message = ('gemini', '💭 Thinking...')
        
        elif event == 'AfterModel':
            # LLM response received - no status change (stay yellow, may loop)
            # Try to extract response text
            response = message.get('response', {})
            text = response.get('text', '')
            if not text:
                # Try alternate structure
                text = message.get('text', '')
            if text:
                display_text = text[:50] + '...' if len(text) > 50 else text
                new_message = ('gemini', display_text)
        
        elif event == 'BeforeTool':
            # Tool about to execute - no status change (stay yellow)
            tool_name = message.get('tool_name', '')
            if tool_name:
                new_message = ('tool', f'→ {tool_name}')
        
        elif event == 'AfterTool':
            # Tool completed - no status change (stay yellow)
            tool_name = message.get('tool_name', '')
            if tool_name:
                new_message = ('tool', f'✓ {tool_name}')
        
        elif event == 'AfterAgent':
            # Agent loop completed - back to idle (white)
            new_status = AgentStatus.IDLE
            # Debug: log the message contents
            with open("/tmp/impromptu_after_agent.log", "a") as f:
                import json
                f.write(f"AfterAgent message: {json.dumps(message, default=str)}\n")
            # Extract final response - field is prompt_response
            text = message.get('prompt_response', '')
            if text:
                # Get the last paragraph/line of the response (the final answer)
                lines = [l.strip() for l in text.strip().split('\n') if l.strip()]
                if lines:
                    # Use last non-empty line as the summary
                    display_text = lines[-1][:60] + '...' if len(lines[-1]) > 60 else lines[-1]
                    new_message = ('gemini', display_text)
        
        elif event == 'Notification':
            # Check notification type
            notification_type = message.get('notification_type', '')
            if notification_type == 'ToolPermission':
                # Permission required - blocked (red)
                new_status = AgentStatus.BLOCKED
                details = message.get('details', {})
                tool_name = details.get('tool_name', 'permission')
                new_message = ('blocked', f'⚠ Approval needed: {tool_name}')
            else:
                # Other notification (e.g., approval granted) - back to busy/idle
                # If we were blocked, go back to busy
                if self.status == AgentStatus.BLOCKED:
                    new_status = AgentStatus.BUSY
        
        return new_status, new_message
