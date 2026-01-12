"""Impromptu: Multi-agent TUI with tmux orchestration."""

import os
import sys
import subprocess
import shutil
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
from .setup_modal import SetupCommandModal
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
        width: 90%;
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
        width: 90%;
        height: auto;
        max-height: 28;
        background: {c.surface};
        border: thick {c.primary};
        padding: 2 3;
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
    
    # Human-readable descriptions for actions
    ACTION_DESCRIPTIONS = {
        "new_agent": "New agent",
        "rename_agent": "Rename",
        "import_agent": "Import pane",
        "close_agent": "Close agent",
        "focus_agent_pane": "Focus pane",
        "refresh": "Refresh",
        "show_shortcuts": "Help",
        "cursor_down": "Move down",
        "cursor_up": "Move up",
    }
    
    def compose(self) -> ComposeResult:
        with Vertical(id="shortcuts-container"):
            yield Static("⌨ Keyboard Shortcuts", id="shortcuts-title")
            
            # Get bindings from Sidebar class
            from . import main as main_module
            bindings = getattr(main_module.Sidebar, 'BINDINGS', [])
            
            # Group bindings by category
            nav_keys = []
            agent_keys = []
            for binding in bindings:
                if len(binding) < 3:
                    continue  # Skip hidden bindings without description
                key, action, desc = binding[0], binding[1], binding[2]
                # Clean up key names
                display_key = key.replace("question_mark", "?")
                # Get action name (strip parameters)
                action_name = action.split("(")[0]
                # Use our descriptions or fallback to provided desc
                display_desc = self.ACTION_DESCRIPTIONS.get(action_name, desc)
                
                # Categorize
                if action_name in ("cursor_down", "cursor_up", "focus_agent_pane"):
                    nav_keys.append((display_key, display_desc))
                elif action_name.startswith("switch_agent"):
                    continue  # Handle separately
                else:
                    agent_keys.append((display_key, display_desc))
            
            yield Static("Navigation", classes="shortcut-section")
            yield Static("j/k      Move up/down", classes="shortcut-row")
            yield Static("Tab      Focus pane", classes="shortcut-row")
            yield Static("Enter    Select agent", classes="shortcut-row")
            
            yield Static("Agents", classes="shortcut-section")
            for key, desc in agent_keys:
                yield Static(f"{key:<8} {desc}", classes="shortcut-row")
            yield Static("1-5      Switch to #", classes="shortcut-row")
            
            yield Static("", classes="shortcut-section")
            yield Static("Esc/?    Close help", classes="shortcut-row")
    
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
        width: 90%;
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


class QuitConfirmModal(ModalScreen[bool]):
    """Modal to confirm quitting impromptu."""
    
    @property
    def CSS(self) -> str:
        c = get_colors()
        return f"""
    QuitConfirmModal {{
        align: center middle;
        background: rgba(0, 0, 0, 0.6);
    }}
    
    #quit-container {{
        width: 90%;
        height: auto;
        background: {c.surface};
        border: thick {c.warning};
        padding: 1 2;
    }}
    
    #quit-title {{
        text-style: bold;
        text-align: center;
        padding-bottom: 1;
        color: {c.warning};
    }}
    
    #quit-message {{
        text-align: center;
        padding: 1 0;
        color: {c.text};
    }}
    
    #button-row {{
        height: auto;
        width: 100%;
        align: center middle;
        padding-top: 1;
    }}
    
    .quit-button {{
        width: 40%;
        min-width: 6;
        margin: 0 1;
    }}
    
    #btn-no {{
        background: {c.primary};
    }}
    
    #btn-yes {{
        background: {c.surface};
        border: solid {c.warning};
    }}
    
    .quit-button:focus {{
        background: {c.selection_bg};
    }}
    """
    
    BINDINGS = [
        ("y", "confirm", "Yes"),
        ("n", "cancel", "No"),
        ("escape", "cancel", "Cancel"),
        ("left", "focus_previous", "Left"),
        ("right", "focus_next", "Right"),
        ("h", "focus_previous", "Left"),
        ("l", "focus_next", "Right"),
    ]
    
    def compose(self) -> ComposeResult:
        from textual.widgets import Button
        from textual.containers import Horizontal
        with Vertical(id="quit-container"):
            yield Static("⚠ Quit Impromptu?", id="quit-title")
            yield Static("This will kill all agent panes.", id="quit-message")
            with Horizontal(id="button-row"):
                yield Button("Yes", id="btn-yes", classes="quit-button")
                yield Button("No", id="btn-no", classes="quit-button")
    
    def on_mount(self) -> None:
        """Focus No button by default."""
        self.query_one("#btn-no").focus()
    
    def on_button_pressed(self, event) -> None:
        """Handle button press."""
        if event.button.id == "btn-yes":
            self.dismiss(True)
        else:
            self.dismiss(False)
    
    def action_confirm(self) -> None:
        """Confirm quit."""
        self.dismiss(True)
    
    def action_cancel(self) -> None:
        """Cancel quit."""
        self.dismiss(False)
    
    def action_focus_previous(self) -> None:
        """Focus previous button."""
        self.focus_previous()
    
    def action_focus_next(self) -> None:
        """Focus next button."""
        self.focus_next()


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

    # Status icons: green=idle, yellow=busy, red=blocked
    STATUS_ICONS = {
        "idle": "🟢",      # Green - ready for input
        "busy": "🟡",      # Yellow - agent is processing
        "blocked": "🔴",   # Red - needs user approval to continue
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
        color: {c.text};
        padding-left: 2;
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
        ("d", "detach", "Detach"),
        ("alt+d", "detach", "Detach"),
        ("q", "quit_app", "Quit"),
        ("alt+q", "quit_app", "Quit"),
        ("w", "close_agent", "Close"),
        # Navigation bindings (hidden from footer)
        ("j", "cursor_down"),
        ("k", "cursor_up"),
        ("ctrl+n", "cursor_down"),
        ("ctrl+p", "cursor_up"),
    ]

    def __init__(self, config: Config):
        super().__init__()
        self.config = config
        self._agents: list[tuple[str, str]] = []  # (name, command) pairs for modal
        self._tracked_panes: list[tmux.TrackedPane] = []  # Tracked agent panes
        self._sidebar_pane: tmux.TrackedPane | None = None  # Sidebar pane (always visible)
        self._poll_timer: Timer | None = None
        self._agents_by_pane: dict[str, BaseAgent] = {}  # pane_id -> agent instance
        self._polling_paused: bool = False  # Temporarily pause polling during operations
        self._log_watcher = LogWatcher()  # Watches logs.json for session matching
        
        # Centralized state store
        self._store = StateStore()
        self._store.subscribe(self._on_state_change)
    
    def _get_agent_command(self, name: str) -> str:
        """Get the command for an agent name from config."""
        base_name = name.split('-')[0] if '-' in name else name
        table = self.config.get_agent_table(base_name)
        return self._build_command(table) if table else "bash"
    
    def _build_command(self, table: dict) -> str:
        """Build command string from agent config table."""
        path = table.get("path", "bash")
        flags = table.get("flags", "")
        return f"{path} {flags}".strip() if flags else path

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
        
        self.dark = self.config.dark_mode

        # Build agent list from config (list of dicts)
        self._agents = [(a.get("name", "unnamed"), self._build_command(a)) for a in self.config.agents]
        
        # Get sidebar pane ID
        sidebar_id = tmux.get_pane_id("0")
        if sidebar_id:
            self._sidebar_pane = tmux.TrackedPane(pane_id=sidebar_id, name="sidebar")
        
        # Clear stale session mappings from previous runs
        # This prevents off-by-one matching with old agent UUIDs
        from pathlib import Path
        for f in [Path("/tmp/impromptu_session_mapping.txt"), Path("/tmp/impromptu_agent_state.txt")]:
            if f.exists():
                f.unlink()
        
        # Kill any existing pane 1 (from startup script) - we'll create our own
        existing_pane = tmux.get_pane_id("1")
        if existing_pane:
            tmux.run_command(f'kill-pane -t {existing_pane}')
        
        # Create initial agent
        if self._agents:
            first_name, first_cmd = self._agents[0]
        else:
            first_name, first_cmd = "gemini", "bash"
        self._create_agent(first_name, first_cmd, is_first=True)
        
        # Register tmux keybindings
        self._register_keybindings()
        
        # Start file watcher for instant updates on file changes
        self._file_watcher = get_session_watcher(self._on_file_change)
        self._file_watcher.start()
        
        # Watch for state files in /tmp (already done in watcher init)
        # Also watch session chats directory AND project dir for logs.json
        import hashlib
        gemini_tmp = Path.home() / ".gemini" / "tmp"
        cwd_physical = Path.cwd().resolve()
        project_hash = hashlib.sha256(str(cwd_physical).encode()).hexdigest()
        project_dir = gemini_tmp / project_hash
        session_dir = project_dir / "chats"
        # Watch project dir for logs.json (instant user message detection)
        if project_dir.exists():
            self._file_watcher.watch_session_dir(project_dir)
        # Watch chats dir for session JSON updates
        if session_dir.exists():
            self._file_watcher.watch_session_dir(session_dir)
        
        # 50ms fast poll for instant message updates (file is tiny, read is <1ms)
        self.set_interval(0.05, lambda: self._update_all_agents(force=True))
        # Slow poll for session matching
        self.set_interval(1.0, self._match_sessions)
        self.set_interval(0.5, self._expire_notifications)
    
    def _on_file_change(self, path: Path) -> None:
        """Called when a session or state file changes - triggers immediate update."""
        # Use call_from_thread to safely update UI from watchdog thread
        # force=True skips mtime check since we know file just changed
        self.call_from_thread(lambda: self._update_all_agents(force=True))
    
    def _register_keybindings(self) -> None:
        """Register tmux keybindings for this session."""
        kb = self.config.keybindings
        
        # Alt+i focuses sidebar (pane 0)
        tmux.run_command(f'bind-key -n {kb.get("sidebar", "M-i")} select-pane -t 0')
        
        # Alt+n sends 'n' key to sidebar (creating new agent)
        tmux.run_command(f'bind-key -n {kb.get("new_agent", "M-n")} "select-pane -t 0 ; send-keys n"')
        
        # Alt+1/2/3/4/5 switch to agents and focus agent pane
        for i in range(1, 6):
            key = kb.get(f"switch_{i}", f"M-{i}")
            tmux.run_command(f'bind-key -n {key} "select-pane -t 0 ; send-keys {i} ; select-pane -t 1"')
        
        # Alt+r sends 'r' key to sidebar (rename agent)
        tmux.run_command('bind-key -n M-r "select-pane -t 0 ; send-keys r"')
        
        # Alt+d detaches from tmux session (global)
        tmux.run_command('bind-key -n M-d detach-client')
        
        # Alt+q sends 'q' to sidebar for quit confirmation
        tmux.run_command('bind-key -n M-q "select-pane -t 0 ; send-keys q"')
    
    def _create_agent(self, name: str, command: str, is_first: bool = False, setup_cmd: str = "") -> Optional[GeminiAgent]:
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
        # Check if command exists (skip for empty command - uses default shell)
        if command and not shutil.which(command.split()[0]):
            self._show_notification(f"Error: Command not found: {command}")
            return None

        # Note: agent.created_at is set automatically for session matching
        
        # Create the pane and run command via shell to inherit environment
        if is_first:
            # Build command with proper escaping via list-based subprocess
            if command:
                # Use exec so interactive commands replace the shell
                full_cmd = f"{setup_cmd} && exec {command}" if setup_cmd else command
            else:
                full_cmd = f"{setup_cmd}; exec $SHELL" if setup_cmd else ""
            
            tmux.split_window_with_command(
                direction="-h",
                target="0",
                command=full_cmd,
                env={"IMPROMPTU_AGENT_ID": agent.uuid},

            )
            tmux.run_command('resize-pane -t 0 -x 20%')
        else:
            visible_pane = self._get_visible_pane()
            if not visible_pane:
                return None
            # Build command with proper escaping via list-based subprocess
            if command:
                # Use exec so interactive commands replace the shell
                full_cmd = f"{setup_cmd} && exec {command}" if setup_cmd else command
            else:
                full_cmd = f"{setup_cmd}; exec $SHELL" if setup_cmd else ""
            
            # Create new pane by splitting from current visible one
            tmux.split_window_with_command(
                direction="-v",
                target=visible_pane.pane_id,
                command=full_cmd,
                env={"IMPROMPTU_AGENT_ID": agent.uuid}
            )
            # Break the OLD visible pane to a hidden window, leaving new pane as main
            tmux.run_command(f'break-pane -d -s {visible_pane.pane_id}')
            tmux.run_command('resize-pane -t 0 -x 20%')
            tmux.run_command('select-pane -t 1')
        
        # Get the new pane's ID (it's always index 1 in window 0 now)
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
    
    def _match_sessions(self) -> None:
        """Match agents to sessions (slow poll, 1s)."""
        if self._polling_paused:
            return
        
        for pane in self._tracked_panes:
            agent = self._agents_by_pane.get(pane.pane_id)
            if not agent or not isinstance(agent, GeminiAgent):
                continue
            
            # Skip if agent already has a session
            if agent.session_path:
                continue
            
            # Hook-based matching ONLY
            session_file = agent.find_session_by_hook()
            
            if session_file:
                agent.claim_session(session_file)
                agent._watcher = SessionWatcher(session_file, agent_id=agent.uuid)
                agent._watcher.check_and_update()
                # Watch the session directory for instant updates
                if hasattr(self, '_file_watcher') and session_file.parent:
                    self._file_watcher.watch_session_dir(session_file.parent)
                # Trigger immediate UI update
                self._update_all_agents()
    
    def _update_all_agents(self, force: bool = False) -> None:
        """Update status/messages for all agents.
        
        Args:
            force: If True, skip has_changed check (used by file watcher)
        """
        for pane in self._tracked_panes:
            agent = self._agents_by_pane.get(pane.pane_id)
            if agent and hasattr(agent, '_watcher') and agent._watcher:
                if force:
                    # File watcher triggered - force read without mtime check
                    agent._watcher._update_from_file()
                else:
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
        agents = state.agents
        
        # Get current items count
        current_count = len(list_view)
        target_count = len(agents)
        
        # Update existing items in place, add new ones, or remove extras
        for i, agent_state in enumerate(agents):
            is_active = (i == state.active_index)
            
            if i < current_count:
                # Update existing item's labels
                existing_item = list(list_view.children)[i]
                if existing_item:
                    try:
                        # Update header label
                        labels = list(existing_item.query(Label))
                        if labels:
                            # Use actual status (green=idle, yellow=busy, red=blocked)
                            icon = AgentItem.STATUS_ICONS.get(agent_state.status, "🟢")
                            labels[0].update(f"[{i + 1}] {icon} {agent_state.name}")
                        
                        # Update message labels
                        for j, msg in enumerate(agent_state.messages[:2]):
                            if j + 1 < len(labels):
                                labels[j + 1].update(msg)
                    except Exception:
                        pass
                    # Update active class (for highlighting)
                    if is_active:
                        existing_item.add_class("active-agent")
                    else:
                        existing_item.remove_class("active-agent")
            else:
                # Add new item with messages
                item = AgentItem(agent_state.name, i, status=agent_state.status, 
                                active=is_active, messages=agent_state.messages)
                list_view.append(item)
        
        # Remove extra items if we have fewer agents now
        while len(list_view) > target_count:
            list_view.pop()
        
        # Set cursor position to active agent's current position in sorted list
        if active_pane_id:
            for i, agent in enumerate(sorted_agents):
                if agent.pane_id == active_pane_id:
                    list_view.index = i
                    break
    
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
            return
        
        agent_name, agent_command = result
        self._pending_agent = (agent_name, agent_command)
        self.push_screen(SetupCommandModal(agent_name), self._on_setup_command)
    
    def _on_setup_command(self, setup_cmd: str) -> None:
        """Handle setup command from modal, then create agent."""
        if not hasattr(self, "_pending_agent"):
            return
        agent_name, agent_command = self._pending_agent
        del self._pending_agent
        self._create_agent_pane(agent_name, agent_command, setup_cmd)
    
    def _create_agent_pane(self, agent_name: str, agent_command: str, setup_cmd: str = "") -> None:
        """Create a new agent pane with the given command."""
        try:
            # Determine display name for new agent
            if agent_name == "Empty Shell":
                display_name = f"shell-{len(self._tracked_panes) + 1}"
            else:
                count = sum(1 for p in self._tracked_panes if p.name.startswith(agent_name))
                display_name = f"{agent_name}-{count + 1}" if count > 0 else agent_name
            
            agent = self._create_agent(display_name, agent_command, is_first=False, setup_cmd=setup_cmd)
            
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
        target_pane = self._tracked_panes[index]

        # Already on this agent?
        if index == state.active_index:
            target_pane.select()
            self._show_notification(f"Already on {target_pane.name}")
            return

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
    
    def action_detach(self) -> None:
        """Detach from the tmux session (keeps all panes running)."""
        tmux.run_command("detach-client")
    
    def action_quit_app(self) -> None:
        """Show quit confirmation modal."""
        self.push_screen(QuitConfirmModal(), self._on_quit_confirm)
    
    def _on_quit_confirm(self, confirmed: bool) -> None:
        """Handle quit confirmation result."""
        if confirmed:
            # Kill the entire tmux session (this will terminate all panes)
            tmux.run_command("kill-session")
    
    def action_show_shortcuts(self) -> None:
        """Show the keyboard shortcuts modal."""
        self.push_screen(ShortcutsModal())
    
    def action_close_agent(self) -> None:
        """Close the currently highlighted agent pane."""
        list_view = self.query_one("#agent-list", ListView)
        current_index = list_view.index
        
        if current_index is None or current_index >= len(self._tracked_panes):
            self._show_notification("No agent selected")
            return
        
        if len(self._tracked_panes) <= 1:
            self._show_notification("Cannot close last agent")
            return
        
        pane = self._tracked_panes[current_index]
        pane_id = pane.pane_id
        pane_name = pane.name
        
        try:
            # Kill the tmux pane
            tmux.run_command(f'kill-pane -t {pane_id}')
            
            # Remove from tracking
            del self._tracked_panes[current_index]
            if pane_id in self._agents_by_pane:
                del self._agents_by_pane[pane_id]
            
            # Update store
            self._store.remove_agent(pane_id)
            
            # Select the previous or first remaining agent
            new_index = min(current_index, len(self._tracked_panes) - 1)
            self._store.set_active_agent(new_index)
            
            self._refresh_list()
            self._show_notification(f"Closed {pane_name}")
        except Exception as e:
            self._show_notification(f"Failed to close: {e}")
    
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
    import argparse
    
    parser = argparse.ArgumentParser(description="Impromptu - Multi-agent TUI manager")
    parser.add_argument("session", nargs="?", default=None,
                        help="Session name to create or attach to (default: impromptu)")
    parser.add_argument("--inside-tmux", action="store_true", 
                        help=argparse.SUPPRESS)  # Internal flag
    args = parser.parse_args()
    
    config = load_config()

    # Check if tmux is available
    if not tmux.is_tmux_available():
        print("Error: tmux is not installed. Please install tmux first.")
        print("  brew install tmux  (macOS)")
        print("  apt install tmux   (Linux)")
        sys.exit(1)

    # If not inside tmux, create session and re-run inside it
    if not tmux.is_inside_tmux():
        session_name = args.session or tmux.SESSION_NAME

        # Check if session already exists - if so, just attach
        if tmux.session_exists(session_name):
            print(f"Attaching to existing session: {session_name}")
            subprocess.run(["tmux", "attach-session", "-t", session_name])
            return

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
            first_agent_cmd = "bash"

            # Small delay to let window settle at full size
            import time
            time.sleep(0.2)
            
            # Create agent pane on the right (85% of full window)
            # Use send-keys to run command in new pane, inheriting shell environment
            tmux.run_command('split-window -h -f -l 85%')
            if first_agent_cmd and first_agent_cmd != "bash":
                tmux.run_command(f'send-keys "{first_agent_cmd}; exit" Enter')
            
            # Resize sidebar to 20% of current window
            tmux.resize_pane("0", width="20%")

            # Keybindings are registered in Sidebar.on_mount() -> _register_keybindings()

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
