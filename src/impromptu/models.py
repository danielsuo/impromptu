"""Data models for the multi-agent TUI."""

import hashlib
import time
import uuid as uuid_module
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


class AgentStatus(Enum):
    """Status of an agent."""
    IDLE = "idle"
    THINKING = "thinking"
    READY = "ready"  # Agent has output ready, triggers notification
    ERROR = "error"


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
            AgentStatus.THINKING: "🟡",
            AgentStatus.READY: "🟢",
            AgentStatus.ERROR: "🔴",
        }
        return icons.get(self.status, "⚪")
    
    def init(self, project_dir: str) -> None:
        """Initialize agent. Override in subclasses."""
        pass
    
    def get_cli_command(self) -> str:
        """Get command to launch this agent's CLI. Override in subclasses."""
        return ""


# Module-level set of claimed session paths (to prevent duplicates)
_claimed_sessions: set[str] = set()


@dataclass
class GeminiAgent(Agent):
    """Gemini CLI agent with session tracking."""
    agent_type: AgentType = field(default=AgentType.GEMINI)
    
    # Unique identifier for this agent's workspace
    uuid: str = field(default_factory=lambda: str(uuid_module.uuid4()))
    
    # Session tracking
    session_id: Optional[str] = None
    session_path: Optional[Path] = None
    project_hash: Optional[str] = None
    symlink_path: Optional[Path] = None
    
    # Process tracking - pane PID for session correlation
    pane_pid: Optional[int] = None
    
    # Timestamp when agent was created (for session matching)
    created_at: float = field(default_factory=time.time)
    
    # Message preview (last 2 messages for UI)
    last_messages: list[str] = field(default_factory=list)
    
    # Gemini-specific state
    last_message_type: Optional[str] = None  # "user" or "gemini"
    is_thinking: bool = False
    message_count: int = 0
    
    GEMINI_TMP_DIR: Path = field(default=Path.home() / ".gemini" / "tmp", repr=False)
    
    def init(self, project_dir: str) -> None:
        """Initialize agent with project directory.
        
        Note: Symlink approach doesn't work because Gemini resolves symlinks
        to physical paths. All agents in the same project share sessions.
        """
        # Resolve to physical path (what Gemini sees)
        self.symlink_path = None  # Not using symlinks anymore
        physical_path = str(Path(project_dir).resolve())
        
        # Compute project hash from physical path (same as Gemini CLI)
        self.project_hash = hashlib.sha256(physical_path.encode()).hexdigest()
    
    def get_cli_command(self) -> str:
        """Get command to launch Gemini CLI from the symlink path."""
        if self.symlink_path:
            return f"cd {self.symlink_path} && gemini"
        return "gemini"
    
    def get_session_dir(self) -> Optional[Path]:
        """Get the directory containing this agent's session files."""
        if self.project_hash:
            return self.GEMINI_TMP_DIR / self.project_hash / "chats"
        return None
    
    def find_latest_session(self) -> Optional[Path]:
        """Find the most recently modified session file for this agent."""
        session_dir = self.get_session_dir()
        if not session_dir or not session_dir.exists():
            return None
        
        session_files = list(session_dir.glob("session-*.json"))
        if not session_files:
            return None
        
        return max(session_files, key=lambda p: p.stat().st_mtime)
    
    def find_new_session(self) -> Optional[Path]:
        """Find an unclaimed session file created after this agent was created."""
        import time as time_module
        
        session_dir = self.get_session_dir()
        if not session_dir or not session_dir.exists():
            return None
        
        # Grace period: wait 0.5s after agent creation before claiming
        # This reduces race conditions when multiple agents are created quickly
        if time_module.time() - self.created_at < 0.5:
            return None
        
        # Find unclaimed sessions with mtime >= created_at
        new_sessions = []
        for f in session_dir.glob("session-*.json"):
            mtime = f.stat().st_mtime
            if mtime >= self.created_at and str(f) not in _claimed_sessions:
                new_sessions.append((f, mtime))
        
        if not new_sessions:
            return None
        
        # Return the session closest to this agent's creation time
        # (the first one created after created_at)
        return min(new_sessions, key=lambda x: x[1])[0]
    
    def find_session_by_hook(self) -> Optional[Path]:
        """Find session by reading mapping from gemini-cli hook.
        
        The SessionStart hook writes {agent_uuid}={session_id} to a mapping file.
        We read this mapping to find the session ID for this agent.
        
        This is the most reliable approach as it uses gemini-cli's hook system.
        """
        mapping_file = Path("/tmp/impromptu_session_mapping.txt")
        
        if not mapping_file.exists():
            return None
        
        session_id = None
        try:
            with open(mapping_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith(f"{self.uuid}="):
                        session_id = line.split("=", 1)[1]
                        break  # 1:1 mapping, only one entry per agent
        except Exception:
            return None
        
        if not session_id:
            return None
        
        # Find session file by session ID prefix
        session_dir = self.get_session_dir()
        if not session_dir or not session_dir.exists():
            return None
        
        session_prefix = session_id[:8]
        for f in session_dir.glob(f"session-*-{session_prefix}.json"):
            return f  # Return even if claimed since this is hook-based (most reliable)
        
        return None
    
    def find_session_by_custom_id(self) -> Optional[Path]:
        """Find session file by matching agent UUID prefix in filename.
        
        When gemini is launched with GEMINI_SESSION_ID={uuid}, it creates
        session files named session-{timestamp}-{session_id[:8]}.json.
        This method finds the session file matching our agent's UUID.
        
        This is cross-platform and doesn't require reading process env vars.
        """
        session_dir = self.get_session_dir()
        if not session_dir or not session_dir.exists():
            return None
        
        # Session files are named: session-{date}-{session_id[:8]}.json
        session_prefix = self.uuid[:8]
        
        for f in session_dir.glob(f"session-*-{session_prefix}.json"):
            if str(f) not in _claimed_sessions:
                return f
        
        return None
    
    def find_session_by_pid(self) -> Optional[Path]:
        """Find session by correlating process start time with session startTime.
        
        This is more reliable than timestamp-based matching because it uses
        the actual process start time to find which session belongs to this agent.
        """
        import subprocess
        import json
        from datetime import datetime
        
        if not self.pane_pid:
            return None
        
        session_dir = self.get_session_dir()
        if not session_dir or not session_dir.exists():
            return None
        
        # Get process start time via ps
        try:
            result = subprocess.run(
                ["ps", "-p", str(self.pane_pid), "-o", "lstart="],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0 or not result.stdout.strip():
                return None
            
            # Parse process start time (e.g., "Sat Jan 10 20:34:00 2026")
            proc_start_str = result.stdout.strip()
            proc_start = datetime.strptime(proc_start_str, "%a %b %d %H:%M:%S %Y")
            proc_start_ts = proc_start.timestamp()
        except Exception:
            return None
        
        # Find session whose startTime is closest to (but after) process start
        best_session = None
        best_delta = float('inf')
        
        for f in session_dir.glob("session-*.json"):
            if str(f) in _claimed_sessions:
                continue
            
            try:
                with open(f, 'r') as fp:
                    data = json.load(fp)
                
                start_time_str = data.get("startTime", "")
                if not start_time_str:
                    continue
                
                # Parse ISO timestamp (e.g., "2026-01-11T01:34:11.756Z")
                if start_time_str.endswith('Z'):
                    start_time_str = start_time_str[:-1] + '+00:00'
                session_start = datetime.fromisoformat(start_time_str)
                session_start_ts = session_start.timestamp()
                
                # Session must start after process (with some tolerance)
                delta = session_start_ts - proc_start_ts
                if 0 <= delta < best_delta:
                    best_session = f
                    best_delta = delta
            except Exception:
                continue
        
        return best_session
    
    def claim_session(self, session_path: Path) -> None:
        """Claim a session file so other agents won't use it."""
        _claimed_sessions.add(str(session_path))
        self.session_path = session_path
    
    def cleanup(self) -> None:
        """Clean up the symlink when agent is destroyed."""
        if self.symlink_path and self.symlink_path.exists():
            try:
                self.symlink_path.unlink()
            except OSError:
                pass
