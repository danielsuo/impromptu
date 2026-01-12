"""Session file watching utilities."""

import json
import time
from pathlib import Path
from typing import Optional, Callable

from .state_provider import AgentState, get_gemini_state_provider


class SessionWatcher:
    """Watches a session file for changes and fetches last messages efficiently.
    
    Only re-reads the file when it changes (based on size/mtime).
    Does not store message history - just fetches last N on demand.
    
    Uses hook-based state provider for accurate status detection,
    with fallback to message-based detection if hooks aren't enabled.
    """
    def __init__(self, session_path: Path, agent_id: Optional[str] = None, on_change: Optional[Callable[[], None]] = None):
        self.session_path = session_path
        self.agent_id = agent_id
        self.on_change = on_change
        self._last_size = 0
        self._last_mtime = 0.0
        self._last_logs_mtime = 0.0  # Track logs.json separately for instant user messages
        self._cached_last_messages: list[str] = []
        self._cached_status: str = "idle"
        self._state_provider = get_gemini_state_provider()
    
    def has_changed(self) -> bool:
        """Check if file has changed since last check.
        
        Checks both session JSON and logs.json for changes.
        """
        changed = False
        
        # Check session file
        if self.session_path.exists():
            try:
                stat = self.session_path.stat()
                if stat.st_size != self._last_size or stat.st_mtime != self._last_mtime:
                    self._last_size = stat.st_size
                    self._last_mtime = stat.st_mtime
                    changed = True
            except OSError:
                pass
        
        # Also check logs.json for instant user message updates
        logs_path = self.session_path.parent.parent / "logs.json"
        if logs_path.exists():
            try:
                logs_mtime = logs_path.stat().st_mtime
                if logs_mtime != self._last_logs_mtime:
                    self._last_logs_mtime = logs_mtime
                    changed = True
            except OSError:
                pass
        
        return changed
    
    def check_and_update(self) -> bool:
        """Check for changes and update cached data if changed.
        
        Returns True if file changed and was updated.
        """
        if not self.has_changed():
            return False
        
        # File changed - fetch latest data
        self._update_from_file()
        
        if self.on_change:
            self.on_change()
        
        return True
    
    def _update_from_file(self) -> None:
        """Parse files and update cached last messages.
        
        Reads user messages from logs.json (fast, small file) 
        and gemini messages from session tail (4KB).
        """
        import re
        messages = []
        
        try:
            # 1. Get user messages from logs.json (small, updates instantly)
            logs_path = self.session_path.parent.parent / "logs.json"
            if logs_path.exists():
                # Read last 2KB of logs.json
                file_size = logs_path.stat().st_size
                read_size = min(file_size, 2048)
                with open(logs_path, 'rb') as f:
                    if file_size > read_size:
                        f.seek(file_size - read_size)
                    logs_tail = f.read().decode('utf-8', errors='ignore')
                
                # Get session ID from our session path (e.g., session-...-5c1b4d66.json)
                session_id_prefix = self.session_path.stem.split('-')[-1]  # e.g., "5c1b4d66"
                
                # Find user messages for this session
                pattern = rf'"sessionId":\s*"{session_id_prefix}[^"]*"[^}}]*?"message":\s*"((?:[^"\\]|\\.)*)"'
                for m in re.findall(pattern, logs_tail):
                    content = m.replace('\\n', ' ').replace('\\t', ' ')[:40]
                    if content.strip():
                        messages.append(("user", content.strip()))
            
            # 2. Get gemini messages from session tail (4KB)
            file_size = self.session_path.stat().st_size
            read_size = min(file_size, 4096)
            with open(self.session_path, 'rb') as f:
                if file_size > read_size:
                    f.seek(file_size - read_size)
                tail_data = f.read().decode('utf-8', errors='ignore')
            
            # Pattern for gemini messages only
            pattern = r'"type":\s*"gemini",\s*"content":\s*"((?:[^"\\]|\\.)*)"'
            for content in re.findall(pattern, tail_data):
                content = content.replace('\\n', ' ').replace('\\t', ' ')[:40]
                if content.strip():
                    messages.append(("gemini", content.strip()))
        
        except Exception:
            pass
        
        # Build last 2 messages (prefer recent)
        self._cached_last_messages = []
        for msg_type, content in reversed(messages[-4:]):
            if len(self._cached_last_messages) >= 2:
                break
            if len(content) > 40:
                content = content[:37] + "..."
            prefix = "▸" if msg_type == "user" else "◂"
            self._cached_last_messages.append(f"{prefix} {content}")
    
    @property
    def last_messages(self) -> list[str]:
        """Get cached last messages (no file I/O)."""
        return self._cached_last_messages
    
    @property
    def status(self) -> str:
        """Get agent status from hooks only.
        
        Returns:
            - "busy": Agent is processing (yellow)
            - "blocked": Waiting for user input to continue (red)
            - "idle": Waiting for user, not blocked (white)
        """
        # Hook-based state only - no fallback
        if self.agent_id:
            hook_state = self._state_provider.get_state(self.agent_id)
            if hook_state == AgentState.BUSY:
                return "busy"
            elif hook_state == AgentState.BLOCKED:
                return "blocked"
        return "idle"


class LogWatcher:
    """Watches ~/.gemini/tmp/*/logs.json to correlate agents with their sessions.
    
    logs.json contains user inputs with sessionId + timestamp, logged immediately.
    We use this to match agents (created at known times) to their session files.
    """
    
    GEMINI_TMP_DIR = Path.home() / ".gemini" / "tmp"
    
    def __init__(self):
        # Map: sessionId -> (project_hash, session_file_path)
        self._session_map: dict[str, tuple[str, Path]] = {}
        # Track last log file sizes/mtimes for change detection
        self._log_file_states: dict[Path, tuple[int, float]] = {}
        # Track log entries we've already processed (sessionId, messageId)
        self._processed_entries: set[tuple[str, int]] = set()
    
    def get_new_log_entries(self) -> list[dict]:
        """Scan all logs.json files for new entries.
        
        Returns list of new entries with keys: sessionId, message, timestamp, project_hash
        """
        new_entries = []
        
        if not self.GEMINI_TMP_DIR.exists():
            return new_entries
        
        # Scan all project directories
        for project_dir in self.GEMINI_TMP_DIR.iterdir():
            if not project_dir.is_dir():
                continue
            
            project_hash = project_dir.name
            log_file = project_dir / "logs.json"
            
            if not log_file.exists():
                continue
            
            # Check if log file changed
            try:
                stat = log_file.stat()
                last_state = self._log_file_states.get(log_file, (0, 0.0))
                
                if stat.st_size == last_state[0] and stat.st_mtime == last_state[1]:
                    continue  # No change
                
                self._log_file_states[log_file] = (stat.st_size, stat.st_mtime)
                
                # Parse log file
                with open(log_file, 'r') as f:
                    logs = json.load(f)
                
                for entry in logs:
                    session_id = entry.get("sessionId", "")
                    message_id = entry.get("messageId", 0)
                    entry_key = (session_id, message_id)
                    
                    if entry_key not in self._processed_entries:
                        self._processed_entries.add(entry_key)
                        new_entries.append({
                            "sessionId": session_id,
                            "message": entry.get("message", ""),
                            "timestamp": entry.get("timestamp", ""),
                            "project_hash": project_hash,
                        })
                        
            except Exception:
                pass
        
        return new_entries
    
    def find_session_file(self, session_id: str, project_hash: str) -> Optional[Path]:
        """Find the session file for a given sessionId in a project."""
        chats_dir = self.GEMINI_TMP_DIR / project_hash / "chats"
        if not chats_dir.exists():
            return None
        
        # Session files are named: session-{date}-{session_id_prefix}.json
        # The prefix is the first 8 chars of the sessionId
        session_prefix = session_id[:8]
        
        for f in chats_dir.glob(f"session-*-{session_prefix}.json"):
            return f
        
        return None
    
    def parse_timestamp(self, timestamp: str) -> float:
        """Convert ISO timestamp to Unix timestamp."""
        try:
            from datetime import datetime
            if timestamp.endswith('Z'):
                timestamp = timestamp[:-1] + '+00:00'
            dt = datetime.fromisoformat(timestamp)
            return dt.timestamp()
        except Exception:
            return 0.0
    
    def find_session_by_probe(self, probe_id: str) -> tuple[Optional[str], Optional[str]]:
        """Search logs.json for a probe message and return (sessionId, project_hash).
        
        Args:
            probe_id: The unique probe string to search for
            
        Returns:
            (sessionId, project_hash) if found, (None, None) otherwise
        """
        if not self.GEMINI_TMP_DIR.exists():
            return None, None
        
        for project_dir in self.GEMINI_TMP_DIR.iterdir():
            if not project_dir.is_dir():
                continue
            
            project_hash = project_dir.name
            log_file = project_dir / "logs.json"
            
            if not log_file.exists():
                continue
            
            try:
                with open(log_file, 'r') as f:
                    logs = json.load(f)
                
                for entry in logs:
                    message = entry.get("message", "")
                    if probe_id in message:
                        return entry.get("sessionId"), project_hash
            except Exception:
                pass
        
        return None, None
