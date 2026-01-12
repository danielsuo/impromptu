"""tmux integration module for impromptu."""

import os
import subprocess
import shutil
from dataclasses import dataclass
from typing import Optional


SESSION_NAME = "impromptu"

# Module-level cache for content hashes (pane_id -> (hash, timestamp))
_pane_content_cache: dict[str, tuple[str, float]] = {}


@dataclass
class Pane:
    """Represents a tmux pane."""
    id: str
    index: int
    title: str
    command: str
    active: bool
    width: int
    height: int


@dataclass
class TrackedPane:
    """A pane we're tracking across windows.
    
    The pane_id (like %1, %2) is stable and doesn't change.
    The window changes when we break/join panes.
    This is the single source of truth for agent UI state.
    """
    pane_id: str  # Stable ID like %1, %2
    name: str  # Display name
    status: str = "idle"  # "idle", "busy", "blocked"
    messages: list = None  # Recent message previews
    
    def __post_init__(self):
        if self.messages is None:
            self.messages = []
    
    def get_window(self) -> Optional[str]:
        """Get the window index this pane is currently in."""
        result = subprocess.run(
            ["tmux", "display-message", "-p", "-t", self.pane_id, "#{window_index}"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return result.stdout.strip()
        return None
    
    def pane_exists(self) -> bool:
        """Check if this pane still exists in tmux."""
        result = subprocess.run(
            ["tmux", "display-message", "-p", "-t", self.pane_id, "#{pane_id}"],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0
    
    def is_in_main_window(self) -> bool:
        """Check if this pane is in the main window (window 0)."""
        window = self.get_window()
        return window == "0"
    
    def break_to_background(self) -> bool:
        """Move this pane to a background window. Returns True if successful."""
        result = subprocess.run(
            ["tmux", "break-pane", "-d", "-s", self.pane_id],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0
    
    def join_to_main(self, target_pane_id: str) -> tuple[bool, str]:
        """Join this pane back to the main window, right of target pane.
        
        Returns (success, error_message)
        """
        result = subprocess.run(
            ["tmux", "join-pane", "-h", "-s", self.pane_id, "-t", target_pane_id],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return False, result.stderr.strip()
        return True, ""
    
    def select(self) -> None:
        """Focus this pane."""
        subprocess.run(
            ["tmux", "select-pane", "-t", self.pane_id],
            capture_output=True
        )
    
    def get_last_activity(self) -> int:
        """Get the Unix timestamp of last activity in this pane."""
        result = subprocess.run(
            ["tmux", "display-message", "-p", "-t", self.pane_id, "#{pane_last_activity}"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            try:
                return int(result.stdout.strip())
            except ValueError:
                return 0
        return 0
    
    def capture_content(self, lines: int = 10) -> str:
        """Capture the last N lines of pane content."""
        result = subprocess.run(
            ["tmux", "capture-pane", "-p", "-t", self.pane_id, "-S", f"-{lines}"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return result.stdout
        return ""
    
    def get_pane_pid(self) -> int | None:
        """Get the PID of the shell process in this pane."""
        result = subprocess.run(
            ["tmux", "display-message", "-p", "-t", self.pane_id, "#{pane_pid}"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            try:
                return int(result.stdout.strip())
            except ValueError:
                return None
        return None
    
    def get_child_cpu(self) -> float:
        """Get the total CPU usage of child processes in this pane.
        
        Returns the sum of CPU% of all child processes of the pane's shell.
        """
        pane_pid = self.get_pane_pid()
        if not pane_pid:
            return 0.0
        
        try:
            # Get child PIDs
            result = subprocess.run(
                ["pgrep", "-P", str(pane_pid)],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0 or not result.stdout.strip():
                return 0.0
            
            child_pids = result.stdout.strip().split('\n')
            
            # Get CPU for each child
            total_cpu = 0.0
            for pid in child_pids:
                ps_result = subprocess.run(
                    ["ps", "-o", "pcpu=", "-p", pid.strip()],
                    capture_output=True,
                    text=True,
                )
                if ps_result.returncode == 0 and ps_result.stdout.strip():
                    try:
                        total_cpu += float(ps_result.stdout.strip())
                    except ValueError:
                        pass
            
            return total_cpu
        except Exception:
            return 0.0
    
    def get_status(self) -> str:
        """Get the current status of this pane.
        
        Returns one of: 'busy', 'idle', 'active'
        - busy: Child process using CPU (> 1%)
        - active: Currently visible in main window and idle
        - idle: Background pane, not busy
        """
        # Check CPU usage of child processes
        cpu = self.get_child_cpu()
        is_visible = self.is_in_main_window()
        
        if cpu > 1.0:
            return "busy"
        elif is_visible:
            return "active"
        else:
            return "idle"


def is_tmux_available() -> bool:
    """Check if tmux is installed."""
    return shutil.which("tmux") is not None


def is_inside_tmux() -> bool:
    """Check if we're running inside tmux."""
    return os.environ.get("TMUX") is not None


def session_exists(name: str = SESSION_NAME) -> bool:
    """Check if a tmux session exists."""
    result = subprocess.run(
        ["tmux", "has-session", "-t", name],
        capture_output=True,
    )
    return result.returncode == 0


def create_session(name: str = SESSION_NAME, command: str = "") -> None:
    """Create a new tmux session."""
    cmd = ["tmux", "new-session", "-d", "-s", name]
    if command:
        cmd.append(command)
    subprocess.run(cmd, check=True)


def attach_session(name: str = SESSION_NAME) -> None:
    """Attach to an existing tmux session."""
    subprocess.run(["tmux", "attach-session", "-t", name], check=True)


def kill_session(name: str = SESSION_NAME) -> None:
    """Kill a tmux session."""
    subprocess.run(["tmux", "kill-session", "-t", name], capture_output=True)


def split_window(
    direction: str = "h",
    percent: int = 75,
    command: str = "",
    target: Optional[str] = None,
) -> None:
    """Split the current window.
    
    Args:
        direction: 'h' for horizontal, 'v' for vertical
        percent: size of the new pane as percentage
        command: command to run in new pane
        target: target pane (default: current)
    """
    cmd = ["tmux", "split-window", f"-{direction}", "-p", str(percent)]
    if target:
        cmd.extend(["-t", target])
    if command:
        cmd.append(command)
    subprocess.run(cmd, check=True)


def select_pane(pane_id: str) -> None:
    """Select/focus a pane."""
    subprocess.run(["tmux", "select-pane", "-t", pane_id], check=True)


def send_keys(pane_id: str, keys: str, enter: bool = True) -> None:
    """Send keys to a pane."""
    cmd = ["tmux", "send-keys", "-t", pane_id, keys]
    if enter:
        cmd.append("Enter")
    subprocess.run(cmd, check=True)


def list_panes() -> list[Pane]:
    """List all panes in the current session."""
    result = subprocess.run(
        [
            "tmux", "list-panes",
            "-F", "#{pane_id}|#{pane_index}|#{pane_title}|#{pane_current_command}|#{pane_active}|#{pane_width}|#{pane_height}"
        ],
        capture_output=True,
        text=True,
    )
    
    panes = []
    for line in result.stdout.strip().split("\n"):
        if not line:
            continue
        parts = line.split("|")
        if len(parts) >= 7:
            panes.append(Pane(
                id=parts[0],
                index=int(parts[1]),
                title=parts[2],
                command=parts[3],
                active=parts[4] == "1",
                width=int(parts[5]),
                height=int(parts[6]),
            ))
    return panes


def get_active_pane() -> Optional[Pane]:
    """Get the currently active pane."""
    for pane in list_panes():
        if pane.active:
            return pane
    return None


def bind_key(key: str, command: str, no_prefix: bool = True) -> None:
    """Bind a key to a tmux command.
    
    Args:
        key: Key to bind (e.g., "M-1" for Alt+1)
        command: tmux command to run
        no_prefix: If True, key works without prefix (Ctrl-b)
    """
    prefix = "-n " if no_prefix else ""
    full_cmd = f'tmux bind-key {prefix}{key} "{command}"'
    subprocess.run(full_cmd, shell=True, check=True)


def unbind_key(key: str, no_prefix: bool = True) -> None:
    """Unbind a key."""
    cmd = ["tmux", "unbind-key"]
    if no_prefix:
        cmd.append("-n")
    cmd.append(key)
    subprocess.run(cmd, capture_output=True)


def register_keybindings(bindings: dict[str, str]) -> None:
    """Register multiple keybindings.
    
    Args:
        bindings: dict mapping key names to pane indices or commands
                  e.g., {"M-1": "0", "M-2": "1", "M-s": "0"}
    """
    for key, target in bindings.items():
        # If target is a number, it's a pane index
        if target.isdigit():
            bind_key(key, f"select-pane -t {target}")
        else:
            bind_key(key, target)


def respawn_pane(pane_id: str, command: str) -> None:
    """Kill current process in pane and start a new command.
    
    This allows swapping agents in the same pane.
    """
    # Send Ctrl-C to stop current process
    subprocess.run(["tmux", "send-keys", "-t", pane_id, "C-c"], capture_output=True)
    # Small delay for process to terminate
    import time
    time.sleep(0.1)
    # Clear the pane
    subprocess.run(["tmux", "send-keys", "-t", pane_id, "clear", "Enter"], capture_output=True)
    # Run the new command
    subprocess.run(["tmux", "send-keys", "-t", pane_id, command, "Enter"], check=True)


def setup_layout(agents: dict[str, str], sidebar_width: int = 25) -> None:
    """Set up the tmux layout with sidebar and agent panes.
    
    Args:
        agents: dict mapping agent names to commands
                e.g., {"gemini": "gemini", "claude": "claude --chat"}
        sidebar_width: width of sidebar as percentage
    """
    agent_list = list(agents.items())
    
    if not agent_list:
        return
    
    # First agent in the main area (right side)
    first_name, first_cmd = agent_list[0]
    split_window(direction="h", percent=100 - sidebar_width, command=first_cmd)
    
    # Additional agents split vertically
    for name, cmd in agent_list[1:]:
        # Split the right pane vertically
        split_window(direction="v", percent=50, command=cmd, target="{right}")
    
    # Focus back on sidebar (pane 0)
    select_pane("0")


def resize_pane(pane_id: str, width: Optional[str] = None, height: Optional[str] = None) -> None:
    """Resize a pane to specific width/height.
    
    Args:
        pane_id: target pane 
        width: width in columns or percentage (e.g., "30" or "20%")
        height: height in rows or percentage
    """
    cmd = ["tmux", "resize-pane", "-t", pane_id]
    if width:
        cmd.extend(["-x", width])
    if height:
        cmd.extend(["-y", height])
    subprocess.run(cmd, check=True)


def run_command(command: str) -> None:
    """Run an arbitrary tmux command."""
    with open("/tmp/impromptu_debug.log", "a") as _f:
        _f.write(f"RUN_CMD: tmux {command}\n")
    try:
        result = subprocess.run(f"tmux {command}", shell=True, check=True, capture_output=True, text=True)
        with open("/tmp/impromptu_debug.log", "a") as _f:
            _f.write("RUN_CMD: SUCCESS\n")
    except subprocess.CalledProcessError as e:
        with open("/tmp/impromptu_debug.log", "a") as _f:
            _f.write(f"RUN_CMD FAILED: {e}\n")
            _f.write(f"STDOUT: {e.stdout}\n")
            _f.write(f"STDERR: {e.stderr}\n")
        raise


def split_window_with_command(
    direction: str = "-h",
    target: str = "0",
    command: str = "",
    env: dict[str, str] | None = None
) -> None:
    """Split window and run a command.
    
    TMux runs commands through the user's default shell.
    
    Args:
        direction: -h for horizontal, -v for vertical
        target: Target pane
        command: Shell command to run in the new pane
        env: Environment variables to set (e.g., {"IMPROMPTU_AGENT_ID": "xxx"})
    """
    # Build base command as list
    cmd = ["tmux", "split-window", direction, "-t", target]
    
    if command or env:
        # Build the full command string
        parts = []
        if env:
            for key, value in env.items():
                parts.append(f"export {key}={value}")
        if command:
            parts.append(command)
        
        full_cmd = "; ".join(parts)
        
        if command:
            # Use interactive shell (-i -c) for commands so shell functions work
            import os as _os
            user_shell = _os.environ.get("SHELL", "/bin/bash")
            cmd.extend([user_shell, "-i", "-c", full_cmd])
        else:
            # No command - just pass env setup, shell will stay open
            cmd.append(full_cmd + "; exec $SHELL")
    
    with open("/tmp/impromptu_debug.log", "a") as _f:
        _f.write(f"CMD: {cmd}\n")
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        with open("/tmp/impromptu_debug.log", "a") as _f:
            _f.write("SUCCESS\n")
    except subprocess.CalledProcessError as e:
        with open("/tmp/impromptu_debug.log", "a") as _f:
            _f.write(f"FAILED: {e}\n")
            _f.write(f"STDOUT: {e.stdout}\n")
            _f.write(f"STDERR: {e.stderr}\n")
        raise


def get_pane_id(pane_target: str = "") -> Optional[str]:
    """Get the pane ID for a pane target.
    
    Pane IDs (like %1, %2) are stable, unlike indices which change with splits.
    Empty string gets the current/active pane.
    """
    cmd = ["tmux", "display-message", "-p", "#{pane_id}"]
    if pane_target:
        cmd = ["tmux", "display-message", "-p", "-t", pane_target, "#{pane_id}"]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return result.stdout.strip()
    return None


def swap_pane(source: str, target: str) -> None:
    """Swap two panes by their ID or index."""
    subprocess.run(["tmux", "swap-pane", "-s", source, "-t", target], check=True)


