"""Impromptu: Multi-agent TUI with tmux orchestration."""

import os
import sys
import subprocess
from pathlib import Path
from typing import Optional
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Static, ListView, ListItem, Label, Button
from textual.containers import Vertical, Center
from textual.timer import Timer
from textual.screen import ModalScreen

from .config import load_config, Config
from . import tmux
from .agents import SessionWatcher, LogWatcher
from .models import AgentType, GeminiAgent
from .state import StateStore, UIState
from .theme import get_colors, DEFAULT_THEME
from .hooks import install_hooks
from .file_watcher import get_session_watcher, SessionDirectoryWatcher


class AgentSelectItem(ListItem):
    """A list item for agent selection in the modal."""

    def __init__(self, name: str, command: str) -> None:
        super().__init__()
        self.agent_name = name
        self.command = command

    def compose(self) -> ComposeResult:
        yield Label(f"  {self.agent_name}")


class AgentSelectModal(ModalScreen[tuple[str, str] | None]):
    """Modal for selecting which agent to start in a new pane."""
    
    # CSS will be generated dynamically with theme colors
    @property
    def CSS(self) -> str:
        c = get_colors()
        return f"""
    AgentSelectModal {{
        align: center middle;
        background: rgba(0, 0, 0, 0.6);
    }}
    
    #modal-container {{
        width: 40;
        height: auto;
        max-height: 20;
        background: {c.surface};
        border: thick {c.primary};
        padding: 1 2;
    }}
    
    #modal-title {{
        text-style: bold;
        text-align: center;
        padding-bottom: 1;
        color: {c.text};
    }}
    
    #agent-select-list {{
        height: auto;
        max-height: 12;
        background: {c.surface};
    }}
    
    #agent-select-list > ListItem {{
        padding: 0 1;
        color: {c.text};
    }}
    
    #agent-select-list > ListItem:hover {{
        background: {c.primary_dim};
    }}
    
    #agent-select-list > ListItem.--highlight {{
        background: {c.selection_bg};
    }}
    
    .cancel-item {{
        color: {c.text_muted};
    }}
    """
    
    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("j", "cursor_down", "Down"),
        ("k", "cursor_up", "Up"),
        ("ctrl+n", "cursor_down", "Down"),
        ("ctrl+p", "cursor_up", "Up"),
    ]
    
    def __init__(self, agents: list[tuple[str, str]]) -> None:
        super().__init__()
        self.agents = agents  # List of (name, command) tuples
    
    def compose(self) -> ComposeResult:
        with Vertical(id="modal-container"):
            yield Static("Select Agent", id="modal-title")
            with ListView(id="agent-select-list"):
                # Add configured agents first
                for name, cmd in self.agents:
                    yield AgentSelectItem(name, cmd)
                # Add empty shell option
                yield AgentSelectItem("Empty Shell", "")
                # Add cancel option
                item = AgentSelectItem("[Cancel]", "__CANCEL__")
                item.add_class("cancel-item")
                yield item
    
    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle agent selection."""
        if isinstance(event.item, AgentSelectItem):
            if event.item.command == "__CANCEL__":
                self.dismiss(None)
            else:
                self.dismiss((event.item.agent_name, event.item.command))
    
    def action_cancel(self) -> None:
        """Cancel the modal."""
        self.dismiss(None)
    
    def action_cursor_down(self) -> None:
        """Move cursor down in list."""
        list_view = self.query_one("#agent-select-list", ListView)
        list_view.action_cursor_down()
    
    def action_cursor_up(self) -> None:
        """Move cursor up in list."""
        list_view = self.query_one("#agent-select-list", ListView)
        list_view.action_cursor_up()


class ShortcutsModal(ModalScreen[None]):
    """Modal showing keyboard shortcuts."""
    
    @property
    def CSS(self) -> str:
        c = get_colors()
        return f"""
    ShortcutsModal {{
        align: center middle;
        background: rgba(0, 0, 0, 0.6);
    }}
    
    #shortcuts-container {{
        width: 50;
        height: auto;
        max-height: 24;
        background: {c.surface};
        border: thick {c.primary};
        padding: 1 2;
    }}
    
    #shortcuts-title {{
        text-style: bold;
        text-align: center;
        padding-bottom: 1;
        color: {c.primary};
    }}
    
    .shortcut-section {{
        padding-top: 1;
        color: {c.text_muted};
        text-style: bold;
    }}
    
    .shortcut-row {{
        color: {c.text};
    }}
    
    .shortcut-key {{
        color: {c.primary};
        text-style: bold;
    }}
    
    #close-hint {{
        padding-top: 1;
        text-align: center;
        color: {c.text_dim};
    }}
    """
    
    BINDINGS = [
        ("escape", "close", "Close"),
        ("question_mark", "close", "Close"),
    ]
    
    def compose(self) -> ComposeResult:
        with Vertical(id="shortcuts-container"):
            yield Static("⌨ Keyboard Shortcuts", id="shortcuts-title")
            
            yield Static("Navigation", classes="shortcut-section")
            yield Static("j / ↓         Down      Enter   Select", classes="shortcut-row")
            yield Static("k / ↑         Up        Tab     Focus pane", classes="shortcut-row")
            
            yield Static("Agents", classes="shortcut-section")
            yield Static("n             New       r       Rename", classes="shortcut-row")
            yield Static("Alt+i         Impromptu Alt+r   Rename (global)", classes="shortcut-row")
            
            yield Static("Other", classes="shortcut-section")
            yield Static("1-5           Switch    ?       Help", classes="shortcut-row")
            yield Static("Esc           Close", classes="shortcut-row")
            
            yield Static("─────────────────────────────────", id="close-hint")
    
    def action_close(self) -> None:
        """Close the modal."""
        self.dismiss(None)


class RenameModal(ModalScreen[str | None]):
    """Modal for renaming an agent pane."""
    
    @property
    def CSS(self) -> str:
        c = get_colors()
        return f"""
    RenameModal {{
        align: center middle;
        background: rgba(0, 0, 0, 0.6);
    }}
    
    #rename-container {{
        width: 40;
        height: auto;
        background: {c.surface};
        border: thick {c.primary};
        padding: 1 2;
    }}
    
    #rename-title {{
        text-style: bold;
        text-align: center;
        padding-bottom: 1;
        color: {c.primary};
    }}
    
    #rename-input {{
        margin: 1 0;
    }}
    
    #rename-hint {{
        text-align: center;
        color: {c.text_muted};
    }}
    """
    
    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]
    
    def __init__(self, current_name: str) -> None:
        super().__init__()
        self.current_name = current_name
    
    def compose(self) -> ComposeResult:
        from textual.widgets import Input
        with Vertical(id="rename-container"):
            yield Static("✏ Rename Agent", id="rename-title")
            yield Input(value=self.current_name, placeholder="Enter new name", id="rename-input")
            yield Static("Enter to confirm, Escape to cancel", id="rename-hint")
    
    def on_input_submitted(self, event) -> None:
        """Handle input submission."""
        new_name = event.value.strip()
        if new_name:
            self.dismiss(new_name)
        else:
            self.dismiss(None)
    
    def action_cancel(self) -> None:
        """Cancel the rename."""
        self.dismiss(None)


class NotificationArea(Static):
    """Custom notification area that shows history of messages."""
    
    MAX_MESSAGES = 3
    CHECK_INTERVAL = 0.5  # Check for expired messages every 0.5s
    
    def __init__(self) -> None:
        super().__init__("", id="notification-area")
        self._messages: dict[int, tuple[str, float]] = {}  # {id: (message, expire_time)}
        self._next_id = 0
        self._check_timer = None
    
    def on_mount(self) -> None:
        """Start the expiration check timer."""
        self._check_timer = self.set_interval(self.CHECK_INTERVAL, self._check_expired)
    
    def show_message(self, message: str, duration: float = 5.0) -> None:
        """Show a notification message that expires after duration."""
        import time
        msg_id = self._next_id
        self._next_id += 1
        expire_time = time.time() + duration
        self._messages[msg_id] = (message, expire_time)
        
        # Keep only the last MAX_MESSAGES
        while len(self._messages) > self.MAX_MESSAGES:
            oldest_id = min(self._messages.keys())
            del self._messages[oldest_id]
        
        # Display immediately
        self._update_display()
    
    def _check_expired(self) -> None:
        """Check for and remove expired messages."""
        import time
        now = time.time()
        expired = [msg_id for msg_id, (_, expire_time) in self._messages.items() if now >= expire_time]
        if expired:
            for msg_id in expired:
                del self._messages[msg_id]
            self._update_display()
    
    def _update_display(self) -> None:
        """Update the displayed text independently of other UI updates."""
        if self._messages:
            # Show messages newest at top (highest ID first)
            sorted_msgs = sorted(self._messages.items(), reverse=True)
            text = "\n".join(msg for _, (msg, _) in sorted_msgs)
            self.update(text)
            self.add_class("notification")
        else:
            self.update("")
            self.remove_class("notification")
        # Force refresh to ensure independent redraw
        self.refresh()


class AgentItem(ListItem):
    """A list item representing an agent with message preview."""

    # Status icons: green=active, white=idle, yellow=busy, red=blocked
    STATUS_ICONS = {
        "active": "🟢",    # Green - visible and selected
        "idle": "⚪",      # White - waiting on user input, not blocked
        "busy": "🟡",      # Yellow - agent is processing
        "blocked": "🔴",   # Red - blocked, needs user input to continue
    }

    def __init__(self, name: str, index: int, status: str = "idle", 
                 active: bool = False, messages: list[str] | None = None) -> None:
        super().__init__()
        self.agent_name = name
        self.agent_index = index
        self.status = status
        self.is_active = active
        self.messages = messages or []
        # Add class for styling
        if active:
            self.add_class("active-agent")

    def compose(self) -> ComposeResult:
        icon = self.STATUS_ICONS.get(self.status, "⚪")
        # Header line: [number] icon name
        yield Label(f"[{self.agent_index + 1}] {icon} {self.agent_name}", classes="agent-header")
        # Always create 2 message label slots (even if empty) so they can be updated later
        for i in range(2):
            msg = self.messages[i] if i < len(self.messages) else ""
            yield Label(msg, classes="agent-message")


class Sidebar(App):
    """Textual sidebar that manages agents in a single pane."""

    # Generate CSS dynamically using theme colors
    @property
    def CSS(self) -> str:
        c = get_colors()
        return f"""
    Screen {{
        background: {c.background};
    }}

    #title {{
        text-style: bold;
        background: {c.primary};
        color: {c.background};
        padding: 0 1;
        height: 1;
    }}

    #agents-header {{
        text-style: bold;
        padding: 1 1 0 1;
        color: {c.text_muted};
    }}

    ListView {{
        height: 1fr;
        padding: 0 1;
        background: {c.background};
    }}

    ListItem {{
        padding: 0 1;
        color: {c.text};
    }}

    ListItem:hover {{
        background: {c.surface_light};
    }}

    /* Cursor highlight when focused */
    ListItem.--highlight {{
        background: {c.selection_bg};
    }}
    
    /* Active/visible agent pane - use selection background for visibility */
    ListItem.active-agent {{
        background: {c.selection_bg};
        color: {c.primary};
    }}
    
    /* When both highlighted and active, show brighter selection */
    ListItem.active-agent.--highlight {{
        background: {c.primary_dim};
    }}
    
    /* Agent item expanded layout */
    .agent-header {{
        color: {c.text};
    }}
    
    .agent-message {{
        color: {c.text_muted};
        padding-left: 3;
        text-style: italic;
    }}
    
    ListItem.active-agent .agent-header {{
        color: {c.primary};
    }}

    #current-agent {{
        padding: 0 1;
        background: {c.surface};
        color: {c.primary};
        height: 1;
        dock: bottom;
    }}

    #shortcuts {{
        height: 1;
        padding: 0 1;
        background: {c.surface};
        color: {c.text_muted};
        dock: bottom;
    }}
    
    /* Custom notification area - only visible when has content */
    #notification-area {{
        height: 0;
        width: 100%;
        dock: bottom;
    }}
    
    #notification-area.notification {{
        height: auto;
        max-height: 5;
        padding: 0 1;
        background: {c.surface_light};
        color: {c.text};
        border-left: wide {c.primary};
    }}
    """

    BINDINGS = [
        ("n", "new_agent", "New"),
        ("r", "rename_agent", "Rename"),
        ("i", "import_agent", "Import"),
        ("question_mark", "show_shortcuts", "Help"),
        ("1", "switch_agent(0)", "1"),
        ("2", "switch_agent(1)", "2"),
        ("3", "switch_agent(2)", "3"),
        ("4", "switch_agent(3)", "4"),
        ("5", "switch_agent(4)", "5"),
        ("tab", "focus_agent_pane", "Focus"),
        ("R", "refresh", "Refresh"),
        ("d", "debug", "Debug"),
        # Navigation bindings (hidden from footer)
        ("j", "cursor_down"),
        ("k", "cursor_up"),
        ("ctrl+n", "cursor_down"),
        ("ctrl+p", "cursor_up"),
    ]

    def __init__(self, config: Config):
        super().__init__()
        self.config = config
        self._agents: list[tuple[str, str]] = []  # (name, command) pairs from config
        self._tracked_panes: list[tmux.TrackedPane] = []  # Tracked agent panes
        self._sidebar_pane: tmux.TrackedPane | None = None  # Sidebar pane (always visible)
        self._poll_timer: Timer | None = None
        self._agents_by_pane: dict[str, BaseAgent] = {}  # pane_id -> agent instance
        self._polling_paused: bool = False  # Temporarily pause polling during operations
        self._log_watcher = LogWatcher()  # Watches logs.json for session matching
        
        # Centralized state store
        self._store = StateStore()
        self._store.subscribe(self._on_state_change)
    
    def _pause_polling(self, duration: float = 3.0) -> None:
        """Pause status polling for a duration after pane operations."""
        self._polling_paused = True
        self.set_timer(duration, self._resume_polling)
    
    def _resume_polling(self) -> None:
        """Resume status polling."""
        self._polling_paused = False
    
    def _show_notification(self, message: str, duration: float = 5.0) -> None:
        """Show a notification via the state store."""
        self._store.add_notification(message, duration)
    
    def _on_state_change(self, old_state: UIState, new_state: UIState) -> None:
        """React to state changes by updating UI.
        
        This is called whenever any part of the state changes.
        """
        # Update agent list if agents changed
        if old_state.agents != new_state.agents or old_state.active_index != new_state.active_index:
            self._render_agent_list()
        
        # Update current agent label if changed
        if old_state.current_agent_name != new_state.current_agent_name:
            try:
                current_label = self.query_one("#current-agent", Static)
                current_label.update(f"▶ {new_state.current_agent_name}")
            except Exception:
                pass
        
        # Update notifications if changed
        if old_state.notifications != new_state.notifications:
            self._render_notifications()

    def compose(self) -> ComposeResult:
        yield Static("IMPROMPTU", id="title")
        yield Static("AGENTS", id="agents-header")
        yield ListView(id="agent-list")
        # Docked bottom elements
        yield Static("Current: gemini", id="current-agent")
        yield NotificationArea()
        # Rich markup: highlight key letters with different style
        yield Static("[bold #7aa2f7 on #3b4261]n[/]ew  [bold #7aa2f7 on #3b4261]r[/]ename  [bold #7aa2f7 on #3b4261]i[/]mport  [bold #7aa2f7 on #3b4261]?[/]help", id="shortcuts")

    def on_mount(self) -> None:
        """Initialize agent list and start polling."""
        # Install Gemini hooks globally if ~/.gemini exists
        install_hooks()
        
        self.dark = self.config.appearance.dark_mode

        # Build agent list from config
        agents = self.config.agents.agents
        self._agents = list(agents.items())
        
        # Get sidebar pane ID
        sidebar_id = tmux.get_pane_id("0")
        if sidebar_id:
            self._sidebar_pane = tmux.TrackedPane(pane_id=sidebar_id, name="sidebar")
        
        # Kill any existing pane 1 (from startup script) - we'll create our own
        existing_pane = tmux.get_pane_id("1")
        if existing_pane:
            tmux.run_command(f'kill-pane -t {existing_pane}')
        
        # Create initial agent
        first_name = self._agents[0][0] if self._agents else "IMPROMPTU_AGENT_ID={agent.uuid} gemini"
        self._create_agent(first_name, is_first=True)
        
        # Start file watcher for instant updates on file changes
        self._file_watcher = get_session_watcher(self._on_file_change)
        self._file_watcher.start()
        
        # Watch for state files in /tmp (already done in watcher init)
        # Also need to watch session directories - done when agents are created
        
        # Polling needed for session matching and initial discovery (0.3s)
        # File watcher supplements this with instant updates on changes
        self.set_interval(0.3, self._poll_status)
        self.set_interval(0.5, self._expire_notifications)
    
    def _on_file_change(self, path: Path) -> None:
        """Called when a session or state file changes - triggers immediate update."""
        # Use call_from_thread to safely update UI from watchdog thread
        self.call_from_thread(self._poll_status)
    
    def _create_agent(self, name: str, is_first: bool = False) -> Optional[GeminiAgent]:
        """Create a new agent with proper session tracking.
        
        Args:
            name: Display name for the agent
            is_first: If True, this is the first agent (uses split-window -h)
        
        Returns:
            The created GeminiAgent, or None if creation failed
        """
        import time
        import uuid as uuid_module
        
        # Create agent
        agent_uuid = str(uuid_module.uuid4())
        project_dir = os.getcwd()
        agent = GeminiAgent(id=agent_uuid, name=name, pane_id=None)
        agent.init(project_dir)
        # Note: agent.created_at is set automatically for session matching
        
        # Create the pane with gemini
        if is_first:
            tmux.run_command(
                f'split-window -h -t 0 "IMPROMPTU_AGENT_ID={agent.uuid} gemini" \\; '
                f'resize-pane -t 0 -x 20%'
            )
        else:
            visible_pane = self._get_visible_pane()
            if not visible_pane:
                return None
            tmux.run_command(
                f'split-window -v -t {visible_pane.pane_id} "IMPROMPTU_AGENT_ID={agent.uuid} gemini" \\; '
                f'break-pane -d -s {visible_pane.pane_id} \\; '
                f'resize-pane -t 0 -x 20% \\; '
                f'select-pane -t 1'
            )
        
        # Get the new pane's ID
        new_pane_id = tmux.get_pane_id("1")
        
        if new_pane_id:
            agent.pane_id = new_pane_id
            
            new_pane = tmux.TrackedPane(pane_id=new_pane_id, name=name)
            
            # Capture pane PID for session matching
            agent.pane_pid = new_pane.get_pane_pid()
            
            if is_first:
                self._tracked_panes = [new_pane]
            else:
                self._tracked_panes.append(new_pane)
            
            self._agents_by_pane[new_pane_id] = agent
            
            # Add to state store
            status = agent._watcher.status if hasattr(agent, '_watcher') and agent._watcher else "idle"
            messages = agent._watcher.last_messages if hasattr(agent, '_watcher') and agent._watcher else []
            self._store.add_agent(new_pane_id, name, status=status, messages=messages)
            
            if is_first:
                self._store.set_active_agent(0)
            else:
                new_index = len(self._store.state.agents) - 1
                self._store.set_active_agent(new_index)
                new_pane.select()
            
            return agent
        
        return None
    
    def _poll_status(self) -> None:
        """Poll pane status and update state store."""
        # Skip polling if paused (during pane operations)
        if self._polling_paused:
            return
        
        # Match agents to sessions (try hook-based, fallback to PID-based)
        for pane in self._tracked_panes:
            agent = self._agents_by_pane.get(pane.pane_id)
            if not agent or not isinstance(agent, GeminiAgent):
                continue
            
            # Skip if agent already has a session
            if agent.session_path:
                continue
            
            # Try hook-based matching first (most reliable when hooks are enabled)
            session_file = agent.find_session_by_hook()
            
            # Fallback to PID-based matching if hook isn't working
            if not session_file:
                session_file = agent.find_session_by_pid()
            
            # Final fallback: find newest unclaimed session
            if not session_file:
                session_file = agent.find_new_session()
            
            if session_file:
                agent.claim_session(session_file)
                agent._watcher = SessionWatcher(session_file, agent_id=agent.uuid)
                agent._watcher.check_and_update()
                # Watch the session directory for instant updates
                if hasattr(self, '_file_watcher') and session_file.parent:
                    self._file_watcher.watch_session_dir(session_file.parent)
        
        # Update status/messages for agents that have watchers
        for pane in self._tracked_panes:
            agent = self._agents_by_pane.get(pane.pane_id)
            if agent and hasattr(agent, '_watcher') and agent._watcher:
                agent._watcher.check_and_update()
                
                status = agent._watcher.status
                messages = agent._watcher.last_messages
                
                self._store.update_agent(
                    pane.pane_id,
                    status=status,
                    messages=messages
                )
    
    def _expire_notifications(self) -> None:
        """Check and expire old notifications."""
        self._store.expire_notifications()

    def _get_visible_pane(self) -> tmux.TrackedPane | None:
        """Get the agent pane that's currently in the main window (visible).
        
        Excludes the sidebar pane.
        """
        for pane in self._tracked_panes:
            # Skip if this is the sidebar
            if self._sidebar_pane and pane.pane_id == self._sidebar_pane.pane_id:
                continue
            if pane.is_in_main_window():
                return pane
        return None
    
    def _debug_panes(self) -> str:
        """Return debug info about tracked panes."""
        lines = [f"Sidebar: {self._sidebar_pane.pane_id if self._sidebar_pane else 'None'}"]
        for i, pane in enumerate(self._tracked_panes):
            window = pane.get_window()
            lines.append(f"  [{i+1}] {pane.name}: {pane.pane_id} (window {window})")
        return "\n".join(lines)

    def _refresh_list(self) -> None:
        """DEPRECATED: Use _render_agent_list instead. Kept for compatibility."""
        self._render_agent_list()
    
    def _render_agent_list(self) -> None:
        """Render agent list from state store."""
        list_view = self.query_one("#agent-list", ListView)
        state = self._store.state
        
        # Get current items count
        current_count = len(list_view)
        target_count = len(state.agents)
        
        # Update existing items in place, add new ones, or remove extras
        for i, agent_state in enumerate(state.agents):
            is_active = (i == state.active_index)
            
            if i < current_count:
                # Update existing item's labels
                existing_item = list(list_view.children)[i]
                if existing_item:
                    try:
                        # Update header label
                        labels = list(existing_item.query(Label))
                        if labels:
                            # Active agent: green if idle, otherwise show busy/blocked
                            # Non-active: show their real status
                            if is_active and agent_state.status == "idle":
                                status = "active"
                            else:
                                status = agent_state.status
                            icon = AgentItem.STATUS_ICONS.get(status, "⚪")
                            labels[0].update(f"[{i + 1}] {icon} {agent_state.name}")
                        
                        # Update message labels
                        for j, msg in enumerate(agent_state.messages[:2]):
                            if j + 1 < len(labels):
                                labels[j + 1].update(msg)
                    except Exception:
                        pass
                    # Update active class
                    if is_active:
                        existing_item.add_class("active-agent")
                    else:
                        existing_item.remove_class("active-agent")
            else:
                # Add new item with messages
                # Active agent: green if idle, otherwise show busy/blocked
                if is_active and agent_state.status == "idle":
                    status = "active"
                else:
                    status = agent_state.status
                item = AgentItem(agent_state.name, i, status=status, 
                                active=is_active, messages=agent_state.messages)
                list_view.append(item)
        
        # Remove extra items if we have fewer agents now
        while len(list_view) > target_count:
            list_view.pop()
        
        # Set cursor position
        if 0 <= state.active_index < len(list_view):
            list_view.index = state.active_index
    
    def _render_notifications(self) -> None:
        """Render notifications from state store."""
        try:
            notification_area = self.query_one(NotificationArea)
            state = self._store.state
            
            if state.notifications:
                # Show newest at top
                text = "\n".join(n.message for n in reversed(state.notifications))
                notification_area.update(text)
                notification_area.add_class("notification")
            else:
                notification_area.update("")
                notification_area.remove_class("notification")
            notification_area.refresh()
        except Exception:
            pass
    
    def _update_active_highlight(self) -> None:
        """Update only the active-agent class, cursor, and status icons.
        
        Sets active pane to 'active' (green), others to 'idle' immediately.
        CPU-based busy detection is paused during this time.
        """
        # Just use the store - it will trigger UI update via _on_state_change
        state = self._store.state
        if 0 <= state.active_index < len(state.agents):
            self._store.set_active_agent(state.active_index)

    def action_import_agent(self) -> None:
        """Import an agent from a file or URL (placeholder)."""
        self._show_notification("Import agent not yet implemented")

    def action_new_agent(self) -> None:
        """Show modal to select agent, then create new pane."""
        # Push the modal to select an agent
        self.push_screen(AgentSelectModal(self._agents), self._on_agent_selected)
    
    def _on_agent_selected(self, result: tuple[str, str] | None) -> None:
        """Handle agent selection from modal."""
        if result is None:
            # User cancelled
            return
        
        agent_name, agent_command = result
        self._create_agent_pane(agent_name, agent_command)
    
    def _create_agent_pane(self, agent_name: str, agent_command: str) -> None:
        """Create a new agent pane with the given command."""
        try:
            # Determine display name for new agent
            if agent_name == "Empty Shell":
                display_name = f"shell-{len(self._tracked_panes) + 1}"
            else:
                count = sum(1 for p in self._tracked_panes if p.name.startswith(agent_name))
                display_name = f"{agent_name}-{count + 1}" if count > 0 else agent_name
            
            agent = self._create_agent(display_name, is_first=False)
            
            if agent:
                self._pause_polling(3.0)
                self._show_notification(f"Started: {display_name}")
            else:
                self._show_notification("Failed to create agent")
        except Exception as e:
            self._show_notification(f"Failed: {e}")

    def action_switch_agent(self, index: int) -> None:
        """Switch to a different agent using break/join-pane."""
        if index >= len(self._tracked_panes):
            self._show_notification(f"No agent {index + 1}")
            return
        
        state = self._store.state

        # Already on this agent?
        if index == state.active_index:
            target_pane = self._tracked_panes[index]
            target_pane.select()
            self._show_notification(f"Already on {target_pane.name}")
            return
        
        target_pane = self._tracked_panes[index]

        try:
            # Get the currently active pane (from store)
            current_pane = self._tracked_panes[state.active_index] if 0 <= state.active_index < len(self._tracked_panes) else None
            
            # Check if target pane still exists
            if not target_pane.pane_exists():
                self._show_notification(f"Pane {target_pane.name} no longer exists")
                return
            
            # Check if target is already in main window (nothing to do)
            if target_pane.is_in_main_window():
                target_pane.select()
                self._store.set_active_agent(index)
                self._show_notification(f"Focused {target_pane.name}")
                return
            
            # Only break current if it's in main window (visible)
            should_break_current = current_pane and current_pane.is_in_main_window()
            
            if should_break_current and self._sidebar_pane:
                # Batch: break current, join target, resize, focus
                tmux.run_command(
                    f'break-pane -d -s {current_pane.pane_id} \\; '
                    f'join-pane -h -s {target_pane.pane_id} -t {self._sidebar_pane.pane_id} \\; '
                    f'resize-pane -t 0 -x 20% \\; '
                    f'select-pane -t 1'
                )
            elif self._sidebar_pane:
                # Just join target (nothing visible to break)
                tmux.run_command(
                    f'join-pane -h -s {target_pane.pane_id} -t {self._sidebar_pane.pane_id} \\; '
                    f'resize-pane -t 0 -x 20% \\; '
                    f'select-pane -t 1'
                )
            
            # Update active via store (triggers UI update)
            self._store.set_active_agent(index)
            self._pause_polling(3.0)
            self._show_notification(f"Switched to {target_pane.name}")
        except Exception as e:
            self._show_notification(f"Failed: {e}")

    def action_focus_agent_pane(self) -> None:
        """Switch focus to the visible agent pane."""
        try:
            state = self._store.state
            if 0 <= state.active_index < len(self._tracked_panes):
                active_pane = self._tracked_panes[state.active_index]
                active_pane.select()
        except Exception:
            pass

    def action_refresh(self) -> None:
        """Manually refresh the list."""
        self._refresh_list()
        self._show_notification("Refreshed")
    
    def action_debug(self) -> None:
        """Show debug info about tracked panes."""
        info = self._debug_panes()
        self._show_notification(info)
    
    def action_show_shortcuts(self) -> None:
        """Show the keyboard shortcuts modal."""
        self.push_screen(ShortcutsModal())
    
    def action_rename_agent(self) -> None:
        """Show modal to rename the currently highlighted agent."""
        list_view = self.query_one("#agent-list", ListView)
        current_index = list_view.index
        
        if current_index is None or current_index >= len(self._tracked_panes):
            self._show_notification("No agent selected")
            return
        
        current_pane = self._tracked_panes[current_index]
        self.push_screen(RenameModal(current_pane.name), self._on_rename_complete)
    
    def _on_rename_complete(self, new_name: str | None) -> None:
        """Handle rename modal result."""
        if new_name is None:
            return
        
        list_view = self.query_one("#agent-list", ListView)
        current_index = list_view.index
        
        if current_index is None or current_index >= len(self._tracked_panes):
            return
        
        # Update the pane name
        self._tracked_panes[current_index].name = new_name
        # Update UI immediately, then pause status polling
        self._refresh_list()
        self._pause_polling(2.0)
        self._show_notification(f"Renamed to: {new_name}")
        
        # Focus the agent pane
        tmux.run_command("select-pane -t 1")
    
    def action_cursor_down(self) -> None:
        """Move cursor down in agent list."""
        list_view = self.query_one("#agent-list", ListView)
        list_view.action_cursor_down()
    
    def action_cursor_up(self) -> None:
        """Move cursor up in agent list."""
        list_view = self.query_one("#agent-list", ListView)
        list_view.action_cursor_up()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle selection in the list view - switch to agent and focus it."""
        if isinstance(event.item, AgentItem):
            self.action_switch_agent(event.item.agent_index)
            # Focus the agent pane after switching
            self.action_focus_agent_pane()


def main():
    """Main entry point - orchestrates tmux and runs sidebar."""
    config = load_config()

    # Check if tmux is available
    if not tmux.is_tmux_available():
        print("Error: tmux is not installed. Please install tmux first.")
        print("  brew install tmux  (macOS)")
        print("  apt install tmux   (Linux)")
        sys.exit(1)

    # If not inside tmux, create session and re-run inside it
    if not tmux.is_inside_tmux():
        session_name = tmux.SESSION_NAME

        # Kill existing session if any
        tmux.kill_session(session_name)

        # Create new session running this script
        subprocess.run([
            "tmux", "new-session", "-s", session_name, "-d",
            sys.executable, "-m", "impromptu.main", "--inside-tmux"
        ], check=True)
        
        # Small delay to let session initialize
        import time
        time.sleep(0.3)

        # Attach to the session
        subprocess.run(["tmux", "attach-session", "-t", session_name])
        return

    # We're inside tmux - set up layout and run sidebar
    if "--inside-tmux" in sys.argv:
        try:
            # Get first agent command
            agents = config.agents.agents
            first_agent_cmd = list(agents.values())[0] if agents else "bash"

            # Small delay to let window settle at full size
            import time
            time.sleep(0.2)
            
            # Create agent pane on the right (85% of full window)
            tmux.run_command(f'split-window -h -f -l 85% "{first_agent_cmd}"')
            
            # Resize sidebar to 20% of current window
            tmux.resize_pane("0", width="20%")

            # Register keybindings
            kb = config.keybindings
            
            # Alt+s focuses sidebar (pane 0) - main way to get back to sidebar
            tmux.bind_key(kb.sidebar, "select-pane -t 0")
            
            # Alt+n sends 'n' key to sidebar (creating new agent via sidebar)
            tmux.run_command(f'bind-key -n {kb.new_agent} "select-pane -t 0 ; send-keys n"')
            
            # Alt+1/2/3/4/5 switch to agents and focus agent pane
            for i in range(1, 6):
                key = getattr(kb, f"switch_{i}", f"M-{i}")
                # Send number to sidebar to switch, then focus agent pane
                tmux.run_command(f'bind-key -n {key} "select-pane -t 0 ; send-keys {i} ; select-pane -t 1"')
            
            # Alt+r sends 'r' key to sidebar (rename agent via sidebar)
            tmux.run_command('bind-key -n M-r "select-pane -t 0 ; send-keys r"')

            # Focus agent pane (pane 1) to start in agent view
            tmux.select_pane("1")
        except Exception as e:
            # Layout setup failed, continue with just sidebar
            print(f"Layout setup warning: {e}", file=sys.stderr)

    # Run the sidebar app
    app = Sidebar(config)
    app.run()


if __name__ == "__main__":
    main()
