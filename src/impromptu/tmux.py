"""tmux integration module for impromptu."""

import os
import subprocess
import shutil
from typing import Optional


SESSION_NAME = "impromptu"


# =============================================================================
# Pane Helper Functions
# =============================================================================
# These functions operate on pane_id strings directly, rather than requiring
# a TrackedPane object. This allows AgentUIState to be the single source of
# truth for agent-pane bindings.


def get_pane_window(pane_id: str) -> Optional[str]:
    """Get the window index a pane is currently in."""
    result = subprocess.run(
        ["tmux", "display-message", "-p", "-t", pane_id, "#{window_index}"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return result.stdout.strip()
    return None


def pane_exists(pane_id: str) -> bool:
    """Check if a pane still exists in tmux."""
    result = subprocess.run(
        ["tmux", "display-message", "-p", "-t", pane_id, "#{pane_id}"],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def is_pane_in_main_window(pane_id: str) -> bool:
    """Check if a pane is in the main window (window 0)."""
    window = get_pane_window(pane_id)
    return window == "0"


def focus_pane(pane_id: str) -> None:
    """Focus a pane by its ID."""
    subprocess.run(
        ["tmux", "select-pane", "-t", pane_id],
        capture_output=True
    )


def get_pane_pid(pane_id: str) -> int | None:
    """Get the PID of the shell process in a pane."""
    result = subprocess.run(
        ["tmux", "display-message", "-p", "-t", pane_id, "#{pane_pid}"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0 and result.stdout.strip():
        try:
            return int(result.stdout.strip())
        except ValueError:
            return None
    return None


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


def select_pane(pane_id: str) -> None:
    """Select/focus a pane."""
    subprocess.run(["tmux", "select-pane", "-t", pane_id], check=True)


def send_keys(pane_id: str, keys: str, enter: bool = True) -> None:
    """Send keys to a pane."""
    cmd = ["tmux", "send-keys", "-t", pane_id, keys]
    if enter:
        cmd.append("Enter")
    subprocess.run(cmd, check=True)


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
            user_shell = os.environ.get("SHELL", "/bin/bash")
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
