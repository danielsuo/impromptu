"""Sidebar application - main TUI component for Impromptu."""

import asyncio
import os
import shutil
import time
import traceback
import uuid as uuid_module
from pathlib import Path
from typing import Optional

from textual.app import App, ComposeResult
from textual.widgets import Static, ListView, Label
from textual.timer import Timer

from ..config import Config
from .. import tmux
from ..agent import GeminiAgent, AgentStatus
from ..state import StateStore, UIState
from ..theme import get_colors
from ..socket_server import HookSocketServer
from . import (
    AgentSelectModal,
    ShortcutsModal,
    RenameModal,
    QuitConfirmModal,
    AgentItem,
    NotificationArea,
    SetupCommandModal,
)

class Sidebar(App):
    """Textual sidebar that manages agents in a single pane."""

    @property
    def CSS(self) -> str:
        """Load CSS from template files and substitute theme variables."""
        c = get_colors()
        
        css_dir = Path(__file__).parent.parent / "assets" / "css"
        css_parts = []
        
        for filename in ["sidebar.tcss", "modals.tcss"]:
            css_file = css_dir / filename
            if css_file.exists():
                template = css_file.read_text()
                # Replace $variable with actual color values
                for var, val in [
                    ("background", c.background),
                    ("surface-light", c.surface_light),
                    ("surface", c.surface),
                    ("border-light", c.border_light),
                    ("border", c.border),
                    ("text-muted", c.text_muted),
                    ("text-dim", c.text_dim),
                    ("text", c.text),
                    ("primary-dim", c.primary_dim),
                    ("primary", c.primary),
                    ("secondary", c.secondary),
                    ("success-dim", c.success_dim),
                    ("success", c.success),
                    ("warning-dim", c.warning_dim),
                    ("warning", c.warning),
                    ("error-dim", c.error_dim),
                    ("error", c.error),
                    ("agent-active", c.agent_active),
                    ("agent-background", c.agent_background),
                    ("agent-busy", c.agent_busy),
                    ("selection-bg", c.selection_bg),
                    ("selection", c.selection),
                    ("highlight", c.highlight),
                ]:
                    template = template.replace(f"${var}", val)
                css_parts.append(template)
        
        return "\n".join(css_parts)

    # Default bindings as fallback when config doesn't specify a key
    # Maps action -> (default_key, description)
    DEFAULT_BINDINGS = {
        "new_agent": ("n", "New"),
        "rename_agent": ("r", "Rename"),
        "import_agent": ("i", "Import"),
        "show_shortcuts": ("?", "Help"),
        "switch_agent(0)": ("1", "1"),
        "switch_agent(1)": ("2", "2"),
        "switch_agent(2)": ("3", "3"),
        "switch_agent(3)": ("4", "4"),
        "switch_agent(4)": ("5", "5"),
        "focus_agent_pane": ("tab", "Focus"),
        "refresh": ("R", "Refresh"),
        "detach": ("d", "Detach"),
        "quit_app": ("q", "Quit"),
        "close_agent": ("w", "Close"),
        "cursor_down": ("j", None),
        "cursor_up": ("k", None),
    }

    # Leave BINDINGS empty - we populate dynamically in on_mount
    BINDINGS = []

    def __init__(self, config: Config):
        super().__init__()
        with open("/tmp/impromptu_error.log", "a") as f:
            f.write("Sidebar.__init__ started\n")
        self.config = config
        self._agents: list[tuple[str, str, int]] = []  # (name, command, num_lines) for modal

        self._sidebar_pane_id: str | None = None  # Sidebar pane ID (always visible)
        self._poll_timer: Timer | None = None
        self._agents_by_pane: dict[str, GeminiAgent] = {}  # pane_id -> agent instance
        self._socket_servers: dict[str, HookSocketServer] = {}  # agent_uuid -> socket server
        
        # Centralized state store
        self._store = StateStore()
        self._store.subscribe(self._on_state_change)
        with open("/tmp/impromptu_error.log", "a") as f:
            f.write("Sidebar.__init__ completed\n")
    
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
        agents_differ = old_state.agents != new_state.agents
        index_differ = old_state.active_index != new_state.active_index
        with open("/tmp/impromptu_timing.log", "a") as f:
            if new_state.agents and old_state.agents:
                old_msgs = old_state.agents[0].messages
                new_msgs = new_state.agents[0].messages
                f.write(f"[{time.time():.3f}] COMPARE agents_differ={agents_differ} same_list={id(old_msgs)==id(new_msgs)} old={old_msgs} new={new_msgs}\n")
        if agents_differ or index_differ:
            with open("/tmp/impromptu_timing.log", "a") as f:
                f.write(f"[{time.time():.3f}] _on_state_change RENDER triggered\n")
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
    
    def _on_hook_message(self, message: dict, agent_id: str, pane_id: str) -> None:
        """Handle hook messages received via socket.
        
        This is called from the socket server thread when a Gemini CLI hook sends data.
        Delegates to agent.handle_hook() for agent-specific processing.
        
        Message pinning behavior:
        - BeforeAgent: Clear messages, pin user prompt to first line
        - Other events: Append to messages (pinned stays first)
        - AfterAgent: Keep only pinned prompt + final response
        """
        event_name = message.get('hook_event_name', '')
        
        # Log for debugging timing
        with open("/tmp/impromptu_timing.log", "a") as f:
            f.write(f"[{time.time():.3f}] HOOK_MSG agent={agent_id} event={event_name}\n")
        
        # Find the agent and delegate handling
        agent = self._agents_by_pane.get(pane_id)
        if not agent:
            return
        
        # Let the agent process the hook message
        new_status, new_message = agent.handle_hook(message)
        
        # Update state on main thread
        def update():
            agent_state = None
            for a in self._store.state.agents:
                if a.pane_id == pane_id:
                    agent_state = a
                    break
            if not agent_state:
                return
            
            if new_status:
                self._store.update_agent(pane_id, status=new_status.value)
            
            if event_name == 'BeforeAgent':
                # New user prompt - clear old messages, pin this prompt
                if new_message:
                    self._store.update_agent(
                        pane_id, 
                        messages=[new_message],  # Start fresh with just the prompt
                        pinned_message=new_message  # Pin it
                    )
            elif event_name == 'AfterAgent':
                # Agent complete - condense to pinned + last response
                pinned = agent_state.pinned_message
                # Use new_message if provided (from AfterAgent hook), else find last gemini response
                last_response = new_message
                if not last_response:
                    for msg in reversed(agent_state.messages):
                        if msg[0] == 'gemini' and msg[1] != '💭 Thinking...':
                            last_response = msg
                            break
                
                # Build final messages - wrap response across available lines
                final_msgs = []
                if pinned:
                    final_msgs.append(pinned)
                
                if last_response:
                    response_text = last_response[1]
                    # Calculate how many lines available for response
                    lines_for_response = agent_state.num_lines - len(final_msgs)
                    
                    if lines_for_response > 0:
                        # Get approximate sidebar width (use config or default)
                        sidebar_width = self.config.sidebar_width - 4  # Account for padding & prefix
                        
                        # Wrap text across available lines
                        if len(response_text) <= sidebar_width:
                            final_msgs.append(('gemini', response_text))
                        else:
                            # Split into chunks, trying to break at word boundaries
                            remaining = response_text
                            is_first = True
                            for _ in range(lines_for_response):
                                if not remaining:
                                    break
                                if len(remaining) <= sidebar_width:
                                    role = 'gemini' if is_first else 'continuation'
                                    final_msgs.append((role, remaining))
                                    break
                                else:
                                    # Try to break at a space
                                    chunk = remaining[:sidebar_width]
                                    last_space = chunk.rfind(' ')
                                    if last_space > sidebar_width // 2:
                                        # Break at space if it's in the second half
                                        chunk = remaining[:last_space]
                                        remaining = remaining[last_space + 1:]
                                    else:
                                        # Break at width limit
                                        remaining = remaining[sidebar_width:]
                                    role = 'gemini' if is_first else 'continuation'
                                    final_msgs.append((role, chunk))
                                    is_first = False
                
                self._store.update_agent(pane_id, messages=final_msgs)
            elif new_message:
                # Normal event - append message, keeping pinned first
                pinned = agent_state.pinned_message
                max_msgs = agent_state.num_lines
                
                # Build new message list
                current_msgs = list(agent_state.messages)
                current_msgs.append(new_message)
                
                # Ensure pinned stays first if present
                if pinned and current_msgs and current_msgs[0] != pinned:
                    current_msgs = [pinned] + [m for m in current_msgs if m != pinned]
                
                # Trim to max lines (keep pinned + most recent)
                if len(current_msgs) > max_msgs:
                    if pinned:
                        # Keep pinned + last (max_msgs - 1)
                        current_msgs = [pinned] + current_msgs[-(max_msgs - 1):]
                    else:
                        current_msgs = current_msgs[-max_msgs:]
                
                self._store.update_agent(pane_id, messages=current_msgs)
        
        # Schedule on main thread
        self.call_later(update)

    def compose(self) -> ComposeResult:
        yield Static("IMPROMPTU", id="title")
        yield Static("AGENTS", id="agents-header")
        yield ListView(id="agent-list")
        # Docked bottom elements
        yield Static("Current: gemini", id="current-agent")
        yield NotificationArea()
        # Rich markup: highlight key letters with different style
        yield Static("[bold #7aa2f7 on #3b4261]n[/]ew  [bold #7aa2f7 on #3b4261]r[/]ename  [bold #7aa2f7 on #3b4261]i[/]mport  [bold #7aa2f7 on #3b4261]?[/]help", id="shortcuts")

    def _load_bindings(self) -> None:
        """Load keybindings from config and apply dynamically.
        
        Uses config.bindings (from TOML) and falls back to DEFAULT_BINDINGS.
        Only applies non-tmux bindings (those not starting with M-).
        """
        # Build map: action -> (key, description) from config
        config_bindings = {}
        bindings = self.config.bindings
        if isinstance(bindings, dict):
            for key, value in bindings.items():
                # Skip tmux bindings (M-key) - those are handled separately
                if key.startswith("M-"):
                    continue
                if isinstance(value, list) and len(value) >= 1:
                    action = value[0]
                    description = value[1] if len(value) > 1 else None
                    config_bindings[action] = (key, description)
        
        # Merge: config takes precedence over defaults
        final_bindings = dict(self.DEFAULT_BINDINGS)
        for action, (key, desc) in config_bindings.items():
            final_bindings[action] = (key, desc)
        
        # Apply bindings dynamically
        for action, (key, description) in final_bindings.items():
            if description:
                self.bind(key, action, description=description)
            else:
                self.bind(key, action)

    def on_mount(self) -> None:
        """Initialize agent list and start polling."""
        def log(msg):
            with open("/tmp/impromptu_error.log", "a") as f:
                f.write(f"on_mount: {msg}\n")
        log("started")
        
        self.dark = self.config.dark_mode
        
        # Load keybindings from config dynamically
        self._load_bindings()
        log("bindings loaded")

        # Build agent list from config (list of dicts)
        self._agents = [(a.get("name", "unnamed"), self._build_command(a), a.get("num_lines", 2)) for a in self.config.agents]
        log(f"agents built: {self._agents}")
        
        # Get sidebar pane ID
        sidebar_id = tmux.get_pane_id("0")
        if sidebar_id:
            self._sidebar_pane_id = sidebar_id
        log(f"sidebar pane: {sidebar_id}")
        
        # Clear stale session mappings from previous runs
        for f in [Path("/tmp/impromptu_session_mapping.txt"), Path("/tmp/impromptu_agent_state.txt")]:
            if f.exists():
                f.unlink()
        log("cleared stale mappings")
        
        # Kill any existing pane 1 (from startup script) - we'll create our own
        existing_pane = tmux.get_pane_id("1")
        if existing_pane:
            tmux.run_command(f'kill-pane -t {existing_pane}')
        log(f"killed existing pane: {existing_pane}")
        
        # Create initial agent
        if self._agents:
            first_name, first_cmd, first_num_lines = self._agents[0]
        else:
            first_name, first_cmd, first_num_lines = "gemini", "bash", 2
        log(f"creating agent: {first_name}")
        self._create_agent(first_name, first_cmd, is_first=True, num_lines=first_num_lines)
        log("agent created")
        
        # Register tmux keybindings
        self._register_keybindings()
        log("keybindings registered")
        
        # Notification expiry timer
        self.set_interval(0.5, self._expire_notifications)
        log("on_mount complete")
    
    def _register_keybindings(self) -> None:
        """Register tmux keybindings from config.
        
        Extracts M-key bindings and registers them with tmux.
        Maps actions to appropriate tmux commands.
        """
        tmux_bindings = self.config.get_tmux_bindings()
        
        for key, action in tmux_bindings.items():
            # Map action to tmux command
            if action == "focus_sidebar":
                tmux.run_command(f'bind-key -n {key} select-pane -t 0')
            elif action == "detach":
                tmux.run_command(f'bind-key -n {key} detach-client')
            elif action.startswith("switch_agent("):
                # Extract agent index from switch_agent(N)
                idx = action[len("switch_agent("):-1]
                # Send the key to sidebar (0-9), then focus agent pane
                sidebar_key = str(int(idx) + 1) if int(idx) < 9 else "0"
                tmux.run_command(f'bind-key -n {key} "select-pane -t 0 ; send-keys {sidebar_key} ; select-pane -t 1"')
            else:
                # For other actions, find the corresponding sidebar key and send it
                # Look up what key triggers this action in sidebar bindings
                sidebar_key = self._get_sidebar_key_for_action(action)
                if sidebar_key:
                    tmux.run_command(f'bind-key -n {key} "select-pane -t 0 ; send-keys {sidebar_key}"')
    
    def _get_sidebar_key_for_action(self, action: str) -> str | None:
        """Find the sidebar key that triggers an action."""
        bindings = self.config.bindings
        if isinstance(bindings, dict):
            for key, value in bindings.items():
                if not key.startswith("M-") and isinstance(value, list) and len(value) >= 1:
                    if value[0] == action:
                        return key
        return None
    
    def _create_agent(self, name: str, command: str, is_first: bool = False, 
                      setup_cmd: str = "", num_lines: int = 2) -> Optional[GeminiAgent]:
        """Create a new agent with proper session tracking.
        
        Args:
            name: Display name for the agent
            is_first: If True, this is the first agent (uses split-window -h)
            num_lines: Number of message lines to display in sidebar
        
        Returns:
            The created GeminiAgent, or None if creation failed
        """
        def log(msg):
            with open("/tmp/impromptu_error.log", "a") as f:
                f.write(f"_create_agent: {msg}\n")
        
        log(f"start name={name} command={command} is_first={is_first}")
        
        # Create agent
        agent_uuid = str(uuid_module.uuid4())
        project_dir = os.getcwd()
        agent = GeminiAgent(id=agent_uuid, name=name, pane_id=None)
        agent.init(project_dir)
        log(f"agent created uuid={agent_uuid}")
        
        # Check if command exists (skip for empty command - uses default shell)
        if command and not shutil.which(command.split()[0]):
            self._show_notification(f"Error: Command not found: {command}")
            log(f"command not found: {command}")
            return None
        log("command check passed")

        # Determine command execution strategy
        use_send_keys = self.config.debug_mode
        
        if use_send_keys:
            # In debug mode, create shell pane and send command via keys
            # This keeps pane open if command fails
            pane_cmd = ""  # Empty means default shell
            pane_env = None  # Don't pass env to split-window, we'll export via send-keys
            # Construct keys command with env export (no exec)
            env_export = f"export IMPROMPTU_AGENT_ID={agent.uuid}"
            if command:
                keys_cmd = f"{env_export} && {setup_cmd} && {command}" if setup_cmd else f"{env_export} && {command}"
            else:
                keys_cmd = f"{env_export} && {setup_cmd}" if setup_cmd else env_export
        else:
            # Standard mode: pass command to split-window with exec
            if command:
                full_cmd = f"{setup_cmd} && exec {command}" if setup_cmd else command
            else:
                full_cmd = f"{setup_cmd}; exec $SHELL" if setup_cmd else ""
            pane_cmd = full_cmd
            keys_cmd = None
            pane_env = {"IMPROMPTU_AGENT_ID": agent.uuid}

        # Note: agent.created_at is set automatically for session matching
        
        # Create the pane
        try:
            if is_first:
                tmux.split_window_with_command(
                    direction="-h",
                    target="0",
                    command=pane_cmd,
                    env=pane_env,
                )
                tmux.run_command('resize-pane -t 0 -x 20%')
            else:
                visible_pane_id = self._get_visible_pane_id()
                if not visible_pane_id:
                    return None
                
                # Create new pane by splitting from current visible one
                tmux.split_window_with_command(
                    direction="-v",
                    target=visible_pane_id,
                    command=pane_cmd,
                    env=pane_env
                )
                # Break the OLD visible pane to a hidden window, leaving new pane as main
                tmux.run_command(f'break-pane -d -s {visible_pane_id}')
                tmux.run_command('resize-pane -t 0 -x 20%')
                tmux.run_command('select-pane -t 1')
        except Exception as e:
            with open("/tmp/impromptu_error.log", "a") as f:
                f.write(f"_create_agent pane creation error: {e}\n{traceback.format_exc()}\n")
            self._show_notification(f"Failed to create pane: {e}")
            return None
        
        # Get the new pane's ID (it's always index 1 in window 0 now)
        new_pane_id = tmux.get_pane_id("1")
        
        if new_pane_id:
            # Send command keys if in debug mode
            if use_send_keys and keys_cmd:
                # Small delay to ensure shell is ready
                time.sleep(0.1)
                tmux.send_keys(new_pane_id, keys_cmd)

            agent.pane_id = new_pane_id
            
            # Capture pane PID for session matching
            agent.pane_pid = tmux.get_pane_pid(new_pane_id)
            
            # Start socket server for instant hook message IPC (async)
            socket_server = HookSocketServer(
                agent_id=agent.uuid,
                on_message=lambda msg, aid=agent.uuid, pid=new_pane_id: self._on_hook_message(msg, aid, pid)
            )
            # Schedule async start on Textual's event loop
            self.call_later(lambda: asyncio.create_task(socket_server.start()))
            self._socket_servers[agent.uuid] = socket_server
            
            self._agents_by_pane[new_pane_id] = agent
            
            # Add to state store (status starts as idle, no messages yet)
            self._store.add_agent(new_pane_id, name, status="idle", messages=[], num_lines=num_lines)
            
            if is_first:
                self._store.set_active_agent(0)
            else:
                new_index = len(self._store.state.agents) - 1
                self._store.set_active_agent(new_index)
                tmux.focus_pane(new_pane_id)
            
            return agent
        
        return None
    
    def _expire_notifications(self) -> None:
        """Check and expire old notifications."""
        self._store.clean_notifications()

    def _get_visible_pane_id(self) -> str | None:
        """Get the pane_id of the agent pane currently in the main window (visible).
        
        Excludes the sidebar pane.
        """
        for agent in self._store.state.agents:
            # Skip if this is the sidebar
            if self._sidebar_pane_id and agent.pane_id == self._sidebar_pane_id:
                continue
            if tmux.is_pane_in_main_window(agent.pane_id):
                return agent.pane_id
        return None
    
    def _debug_panes(self) -> str:
        """Return debug info about tracked panes."""
        lines = [f"Sidebar: {self._sidebar_pane_id or 'None'}"]
        for i, agent in enumerate(self._store.state.agents):
            window = tmux.get_pane_window(agent.pane_id)
            lines.append(f"  [{i+1}] {agent.name}: {agent.pane_id} (window {window})")
        return "\n".join(lines)

    def _refresh_list(self) -> None:
        """DEPRECATED: Use _render_agent_list instead. Kept for compatibility."""
        self._render_agent_list()
    
    def _render_agent_list(self) -> None:
        """Render agent list from _store (single source of truth)."""
        try:
            list_view = self.query_one("#agent-list", ListView)
            
            # Get current items count
            current_count = len(list_view)
            target_count = len(self._store.state.agents)
            
            # Get active pane for highlighting
            active_pane_id = self._get_visible_pane_id()
            
            # Update existing items in place, add new ones, or remove extras
            for i, agent in enumerate(self._store.state.agents):
                is_active = (agent.pane_id == active_pane_id)
                
                if i < current_count:
                    # Update existing item's labels
                    existing_item = list(list_view.children)[i]
                    if existing_item:
                        try:
                            # Update header label
                            labels = list(existing_item.query(Label))
                            if labels:
                                icon = AgentItem.STATUS_ICONS.get(agent.status, "🟢")
                                labels[0].update(f"[{i + 1}] {icon} {agent.name}")
                            
                            # Update message labels (use agent's num_lines)
                            num_msg_labels = agent.num_lines
                            for j, msg in enumerate(agent.messages[:num_msg_labels] if agent.messages else []):
                                if j + 1 < len(labels):
                                    # Messages are (role, content) tuples - include role prefix
                                    if isinstance(msg, tuple):
                                        role, content = msg[0], msg[1]
                                        if role == "continuation":
                                            text = f"  {content}"
                                        else:
                                            prefix = "› " if role == "user" else "‹ " if role == "gemini" else "  "
                                            text = f"{prefix}{content}"
                                    else:
                                        text = msg
                                    labels[j + 1].update(text)
                            # Clear remaining message labels
                            for j in range(len(agent.messages), num_msg_labels):
                                if j + 1 < len(labels):
                                    labels[j + 1].update("")
                        except Exception:
                            pass
                        # Update active class (for highlighting)
                        if is_active:
                            existing_item.add_class("active-agent")
                        else:
                            existing_item.remove_class("active-agent")
                else:
                    # Add new item with messages and num_lines
                    item = AgentItem(agent.name, i, status=agent.status, 
                                    active=is_active, messages=agent.messages or [],
                                    num_lines=agent.num_lines)
                    list_view.append(item)
            
            # Remove extra items if we have fewer agents now
            while len(list_view) > target_count:
                list_view.pop()
        except Exception as e:
            with open("/tmp/impromptu_error.log", "a") as f:
                f.write(f"_render_agent_list error: {e}\n{traceback.format_exc()}\n")
    
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
        # Look up num_lines from matching agent config
        num_lines = 2  # default
        for name, cmd, nl in self._agents:
            if name == agent_name:
                num_lines = nl
                break
        self._pending_agent = (agent_name, agent_command, num_lines)
        self.push_screen(SetupCommandModal(agent_name), self._on_setup_command)
    
    def _on_setup_command(self, setup_cmd: str) -> None:
        """Handle setup command from modal, then create agent."""
        if not hasattr(self, "_pending_agent"):
            return
        agent_name, agent_command, num_lines = self._pending_agent
        del self._pending_agent
        self._create_agent_pane(agent_name, agent_command, setup_cmd, num_lines)
    
    def _create_agent_pane(self, agent_name: str, agent_command: str, 
                           setup_cmd: str = "", num_lines: int = 2) -> None:
        """Create a new agent pane with the given command."""
        try:
            # Determine display name for new agent
            if agent_name == "Empty Shell":
                display_name = f"shell-{len(self._store.state.agents) + 1}"
            else:
                count = sum(1 for a in self._store.state.agents if a.name.startswith(agent_name))
                display_name = f"{agent_name}-{count + 1}" if count > 0 else agent_name
            
            agent = self._create_agent(display_name, agent_command, is_first=False, 
                                       setup_cmd=setup_cmd, num_lines=num_lines)
            
            if agent:
                self._pause_polling(3.0)
                self._show_notification(f"Started: {display_name}")
            else:
                self._show_notification("Failed to create agent")
        except Exception as e:
            self._show_notification(f"Failed: {e}")

    def action_switch_agent(self, index: int) -> None:
        """Switch to a different agent using break/join-pane."""
        if index >= len(self._store.state.agents):
            self._show_notification(f"No agent {index + 1}")
            return
        
        state = self._store.state
        target_agent = self._store.state.agents[index]

        # Already on this agent?
        if index == state.active_index:
            tmux.run_command(f"select-pane -t {target_agent.pane_id}")
            self._show_notification(f"Already on {target_agent.name}")
            return

        try:
            # Get the currently active pane (from store)
            current_agent = self._store.state.agents[state.active_index] if 0 <= state.active_index < len(self._store.state.agents) else None
            current_pane_id = current_agent.pane_id if current_agent else None
            target_pane_id = target_agent.pane_id
            
            # Check if target pane still exists
            if not tmux.pane_exists(target_pane_id):
                self._show_notification(f"Pane {target_agent.name} no longer exists")
                return
            
            # Check if target is already in main window (nothing to do)
            if tmux.is_pane_in_main_window(target_pane_id):
                tmux.run_command(f"select-pane -t {target_pane_id}")
                self._store.set_active_agent(index)
                self._show_notification(f"Focused {target_agent.name}")
                return
            
            # Only break current if it's in main window (visible)
            should_break_current = current_pane_id and tmux.is_pane_in_main_window(current_pane_id)
            
            if should_break_current and self._sidebar_pane_id:
                # Batch: break current, join target, resize, focus
                tmux.run_command(
                    f'break-pane -d -s {current_pane_id} \\; '
                    f'join-pane -h -s {target_pane_id} -t {self._sidebar_pane_id} \\; '
                    f'resize-pane -t 0 -x 20% \\; '
                    f'select-pane -t 1'
                )
            elif self._sidebar_pane_id:
                # Just join target (nothing visible to break)
                tmux.run_command(
                    f'join-pane -h -s {target_pane_id} -t {self._sidebar_pane_id} \\; '
                    f'resize-pane -t 0 -x 20% \\; '
                    f'select-pane -t 1'
                )
            
            # Update active via store (triggers UI update)
            self._store.set_active_agent(index)
            self._pause_polling(3.0)
            self._show_notification(f"Switched to {target_agent.name}")
        except Exception as e:
            self._show_notification(f"Failed: {e}")

    def action_focus_agent_pane(self) -> None:
        """Switch focus to the visible agent pane."""
        try:
            state = self._store.state
            if 0 <= state.active_index < len(self._store.state.agents):
                agent = self._store.state.agents[state.active_index]
                tmux.run_command(f"select-pane -t {agent.pane_id}")
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
        with open("/tmp/impromptu_error.log", "a") as f:
            f.write("action_quit_app called!\n")
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
        """Close the currently selected or visible agent pane."""
        with open("/tmp/impromptu_error.log", "a") as f:
            f.write("action_close_agent called!\n")
        list_view = self.query_one("#agent-list", ListView)
        current_index = list_view.index
        
        # Fall back to visible pane
        if current_index is None or current_index >= len(self._store.state.agents):
            visible_pane_id = self._get_visible_pane_id()
            if visible_pane_id:
                current_index = next((i for i, p in enumerate(self._store.state.agents) 
                                     if p.pane_id == visible_pane_id), None)
        
        if current_index is None or current_index >= len(self._store.state.agents):
            self._show_notification("No agent selected")
            return
        
        # If only one agent, show quit confirmation
        if len(self._store.state.agents) <= 1:
            self.action_quit_app()
            return
        
        agent = self._store.state.agents[current_index]
        pane_id = agent.pane_id
        pane_name = agent.name
        
        with open("/tmp/impromptu_error.log", "a") as f:
            f.write(f"Closing agent: {pane_name} (pane {pane_id})\n")
        
        # Close immediately without confirmation
        try:
            # Kill the pane
            tmux.run_command(f'kill-pane -t {pane_id}')
            
            with open("/tmp/impromptu_error.log", "a") as f:
                f.write(f"Pane killed, cleaning up state\n")
            
            with open("/tmp/impromptu_error.log", "a") as f:
                f.write(f"DEBUG: pane_id={pane_id}, _agents_by_pane keys={list(self._agents_by_pane.keys())}\n")
            
            # Clean up socket server - don't await, just fire and forget
            try:
                if pane_id in self._agents_by_pane:
                    with open("/tmp/impromptu_error.log", "a") as f:
                        f.write(f"DEBUG: popping agent from _agents_by_pane\n")
                    agent_obj = self._agents_by_pane.pop(pane_id)
                    with open("/tmp/impromptu_error.log", "a") as f:
                        f.write(f"DEBUG: agent popped, checking socket\n")
                    if hasattr(agent_obj, 'uuid') and agent_obj.uuid in self._socket_servers:
                        with open("/tmp/impromptu_error.log", "a") as f:
                            f.write(f"DEBUG: removing socket server\n")
                        self._socket_servers.pop(agent_obj.uuid, None)
            except Exception as e:
                with open("/tmp/impromptu_error.log", "a") as f:
                    f.write(f"DEBUG: socket cleanup error: {e}\n")
            
            with open("/tmp/impromptu_error.log", "a") as f:
                f.write(f"Step 1: socket cleanup done\n")
            
            self._store.remove_agent(pane_id)
            
            with open("/tmp/impromptu_error.log", "a") as f:
                f.write(f"Step 2: agent removed from store\n")
            
            # Switch to another agent (simple approach - just select pane 1)
            new_index = min(current_index, len(self._store.state.agents) - 1)
            with open("/tmp/impromptu_error.log", "a") as f:
                f.write(f"Step 3: new_index={new_index}, agents_count={len(self._store.state.agents)}\n")
            
            if new_index >= 0 and len(self._store.state.agents) > 0:
                self._store.set_active_agent(new_index)
                with open("/tmp/impromptu_error.log", "a") as f:
                    f.write(f"Step 4: active agent set\n")
                # Just select the next pane instead of complex switch
                tmux.run_command("select-pane -t 1")
                with open("/tmp/impromptu_error.log", "a") as f:
                    f.write(f"Step 5: select-pane done\n")
            
            with open("/tmp/impromptu_error.log", "a") as f:
                f.write(f"Step 6: about to refresh list\n")
            
            self._refresh_list()
            
            with open("/tmp/impromptu_error.log", "a") as f:
                f.write(f"Step 7: list refreshed\n")
            
            self._show_notification(f"Closed {pane_name}")
            
            with open("/tmp/impromptu_error.log", "a") as f:
                f.write(f"Close complete\n")
        except Exception as e:
            with open("/tmp/impromptu_error.log", "a") as f:
                import traceback
                f.write(f"Close failed: {e}\n{traceback.format_exc()}\n")
            self._show_notification(f"Failed: {e}")

    def action_rename_agent(self) -> None:
        """Show modal to rename the currently highlighted agent."""
        list_view = self.query_one("#agent-list", ListView)
        current_index = list_view.index
        
        # Fall back to current visible pane if none selected in list
        if current_index is None or current_index >= len(self._store.state.agents):
            visible_pane_id = self._get_visible_pane_id()
            if visible_pane_id:
                current_index = next((i for i, p in enumerate(self._store.state.agents) if p.pane_id == visible_pane_id), None)
        
        if current_index is None or current_index >= len(self._store.state.agents):
            self._show_notification("No agent selected")
            return
        
        current_agent = self._store.state.agents[current_index]
        self._rename_index = current_index  # Store for callback
        self.push_screen(RenameModal(current_agent.name), self._on_rename_complete)
    
    def _on_rename_complete(self, new_name: str | None) -> None:
        """Handle rename modal result."""
        try:
            if new_name is None:
                return
            
            current_index = getattr(self, '_rename_index', None)
            if current_index is None or current_index >= len(self._store.state.agents):
                self._show_notification("Agent no longer exists")
                return
            
            # Update the pane name (single source of truth)
            agent = self._store.state.agents[current_index]
            agent.name = new_name
            
            # Also update the tmux pane title
            tmux.run_command(f'select-pane -t {agent.pane_id} -T "{new_name}"')
            
            # Update UI immediately, then pause status polling
            self._refresh_list()
            self._pause_polling(2.0)
            self._show_notification(f"Renamed to: {new_name}")
            
            # Focus the agent pane
            tmux.run_command("select-pane -t 1")
        except Exception as e:
            with open("/tmp/impromptu_error.log", "a") as f:
                f.write(f"Rename error: {e}\n")
                traceback.print_exc(file=f)
            raise
    
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

