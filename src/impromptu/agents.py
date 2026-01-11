"""Session file watching utilities."""

import json
import time
from pathlib import Path
from typing import Optional, Callable


class SessionWatcher:
    """Watches a session file for changes and fetches last messages efficiently.
    
    Only re-reads the file when it changes (based on size/mtime).
    Does not store message history - just fetches last N on demand.
    """
    
    def __init__(self, session_path: Path, on_change: Optional[Callable[[], None]] = None):
        self.session_path = session_path
        self.on_change = on_change
        self._last_size = 0
        self._last_mtime = 0.0
        self._cached_last_messages: list[str] = []
        self._cached_status: str = "idle"
    
    def has_changed(self) -> bool:
        """Check if file has changed since last check."""
        if not self.session_path.exists():
            return False
        
        try:
            stat = self.session_path.stat()
            if stat.st_size != self._last_size or stat.st_mtime != self._last_mtime:
                self._last_size = stat.st_size
                self._last_mtime = stat.st_mtime
                return True
        except OSError:
            pass
        return False
    
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
        """Parse file and update cached last messages and status."""
        try:
            with open(self.session_path, 'r') as f:
                data = json.load(f)
            
            messages = data.get("messages", [])
            last_updated = data.get("lastUpdated", "")
            
            # Parse session age for status detection
            session_age = 9999
            if last_updated:
                try:
                    from datetime import datetime
                    if last_updated.endswith('Z'):
                        last_updated_parsed = last_updated[:-1] + '+00:00'
                    else:
                        last_updated_parsed = last_updated
                    dt = datetime.fromisoformat(last_updated_parsed)
                    session_age = time.time() - dt.timestamp()
                except Exception:
                    pass
            
            # Get last 2 messages with content (for UI preview)
            self._cached_last_messages = []
            for msg in reversed(messages):
                if len(self._cached_last_messages) >= 2:
                    break
                content = msg.get("content", "")
                if content and content.strip():
                    msg_type = msg.get("type", "unknown")
                    # Truncate
                    if len(content) > 40:
                        content = content[:37] + "..."
                    content = content.replace("\n", " ").strip()
                    prefix = "▸" if msg_type == "user" else "◂"
                    self._cached_last_messages.insert(0, f"{prefix} {content}")
            
            # Determine status from last message and activity
            if messages:
                last_msg = messages[-1]
                last_type = last_msg.get("type", "")
                
                # Check for pending tool calls (gemini is executing tools)
                tool_calls = last_msg.get("toolCalls", [])
                has_pending_tools = any(
                    tc.get("status") == "pending" for tc in tool_calls
                )
                
                # Check for recent thoughts (within 30s = actively thinking)
                thoughts = last_msg.get("thoughts", [])
                has_recent_thoughts = False
                if thoughts:
                    try:
                        from datetime import datetime
                        for thought in thoughts:
                            ts = thought.get("timestamp", "")
                            if ts:
                                if ts.endswith('Z'):
                                    ts = ts[:-1] + '+00:00'
                                thought_time = datetime.fromisoformat(ts)
                                thought_age = time.time() - thought_time.timestamp()
                                if thought_age < 30:
                                    has_recent_thoughts = True
                                    break
                    except Exception:
                        pass
                
                # Status logic:
                # - "thinking": user sent message OR pending tools OR recent thoughts
                # - "ready": gemini responded and waiting for user (within 30s)
                # - "idle": no recent activity
                if session_age < 30:
                    if last_type == "user" or has_pending_tools or has_recent_thoughts:
                        self._cached_status = "thinking"
                    elif last_type == "gemini":
                        self._cached_status = "ready"
                    else:
                        self._cached_status = "idle"
                else:
                    self._cached_status = "idle"
            else:
                self._cached_status = "idle"
                
        except Exception:
            pass
    
    @property
    def last_messages(self) -> list[str]:
        """Get cached last messages (no file I/O)."""
        return self._cached_last_messages
    
    @property
    def status(self) -> str:
        """Get cached status (no file I/O)."""
        return self._cached_status
