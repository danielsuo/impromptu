"""File watching for instant session updates.

Uses watchdog (FSEvents on macOS, inotify on Linux) for instant file change detection.
"""

import threading
from pathlib import Path
from typing import Callable, Optional
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileModifiedEvent, FileCreatedEvent


class SessionFileHandler(FileSystemEventHandler):
    """Handles file system events for session files."""
    
    def __init__(self, on_change: Callable[[Path], None]):
        super().__init__()
        self.on_change = on_change
    
    def on_modified(self, event):
        if event.is_directory:
            return
        # Watch session files and logs.json for instant updates
        if event.src_path.endswith('.json'):
            if 'session-' in event.src_path or event.src_path.endswith('logs.json'):
                self.on_change(Path(event.src_path))
    
    def on_created(self, event):
        if event.is_directory:
            return
        if event.src_path.endswith('.json'):
            if 'session-' in event.src_path or event.src_path.endswith('logs.json'):
                self.on_change(Path(event.src_path))


class StateFileHandler(FileSystemEventHandler):
    """Handles file system events for state files (hook output)."""
    
    def __init__(self, on_change: Callable[[Path], None]):
        super().__init__()
        self.on_change = on_change
    
    def on_modified(self, event):
        if event.is_directory:
            return
        # Watch for our state files
        if 'impromptu_' in event.src_path and event.src_path.endswith('.txt'):
            self.on_change(Path(event.src_path))
    
    def on_created(self, event):
        if event.is_directory:
            return
        if 'impromptu_' in event.src_path and event.src_path.endswith('.txt'):
            self.on_change(Path(event.src_path))


class SessionDirectoryWatcher:
    """Watches session directories for file changes.
    
    Triggers callbacks immediately when session files are created/modified,
    enabling instant UI updates without polling.
    """
    
    def __init__(self, on_session_change: Callable[[Path], None]):
        self.on_session_change = on_session_change
        self._observer: Optional[Observer] = None
        self._watched_dirs: set[str] = set()
        self._lock = threading.Lock()
    
    def start(self) -> None:
        """Start the file watcher."""
        if self._observer is not None:
            return
        
        # Use PollingObserver for guaranteed low latency on macOS
        # FSEvents has unpredictable latency (can be 1-5 seconds)
        from watchdog.observers.polling import PollingObserver
        self._observer = PollingObserver(timeout=0.5)
        
        # Watch /tmp for state files (resolve symlink for macOS: /tmp -> /private/tmp)
        tmp_path = Path("/tmp").resolve()
        tmp_handler = StateFileHandler(self.on_session_change)
        self._observer.schedule(tmp_handler, str(tmp_path), recursive=False)
        
        self._observer.start()
    
    def watch_session_dir(self, session_dir: Path) -> None:
        """Add a session directory to watch."""
        if not session_dir.exists():
            return
        
        dir_str = str(session_dir)
        with self._lock:
            if dir_str in self._watched_dirs:
                return
            self._watched_dirs.add(dir_str)
        
        if self._observer:
            handler = SessionFileHandler(self.on_session_change)
            self._observer.schedule(handler, dir_str, recursive=False)
    
    def stop(self) -> None:
        """Stop the file watcher."""
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=1.0)
            self._observer = None
            self._watched_dirs.clear()


# Singleton instance
_watcher: Optional[SessionDirectoryWatcher] = None


def get_session_watcher(on_change: Callable[[Path], None]) -> SessionDirectoryWatcher:
    """Get or create the singleton session watcher."""
    global _watcher
    if _watcher is None:
        _watcher = SessionDirectoryWatcher(on_change)
    return _watcher
