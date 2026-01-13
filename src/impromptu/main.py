"""Impromptu: Multi-agent TUI with tmux orchestration."""

import argparse
import os
import shutil
import subprocess
import sys
import time
import traceback

from .config import load_config
from . import tmux
from .ui import Sidebar


def main():
    """Main entry point - orchestrates tmux and runs sidebar."""
    
    # Set up error logging to file
    error_log = "/tmp/impromptu_error.log"
    
    parser = argparse.ArgumentParser(description="Impromptu - Multi-agent TUI manager")
    parser.add_argument("session", nargs="?", default=None,
                        help="Session name to create or attach to (default: impromptu)")
    parser.add_argument("--debug", action="store_true", 
                        help="Debug mode: use send-keys for commands to keep panes open on error")
    parser.add_argument("--inside-tmux", action="store_true", 
                        help=argparse.SUPPRESS)  # Internal flag
    args = parser.parse_args()
    
    config = load_config()
    config.debug_mode = args.debug

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
        inner_cmd = [sys.executable, "-m", "impromptu.main", "--inside-tmux"]
        if args.debug:
            inner_cmd.append("--debug")
        subprocess.run([
            "tmux", "new-session", "-s", session_name, "-d",
            *inner_cmd
        ], check=True)
        
        # Small delay to let session initialize
        time.sleep(0.3)

        # Attach to the session
        subprocess.run(["tmux", "attach-session", "-t", session_name])
        return

    # We're inside tmux - set up layout and run sidebar
    if "--inside-tmux" in sys.argv:
        try:
            # Get first agent command (unused currently, but kept for future use)
            agents = config.agents  # config.agents is already a list
            first_agent_cmd = "bash"

            # Small delay to let window settle at full size
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

    # Run the sidebar app - bindings are loaded dynamically in on_mount
    try:
        app = Sidebar(config)
        with open("/tmp/impromptu_error.log", "a") as f:
            f.write(f"Starting app.run()\n")
            f.write(f"  TERM={os.environ.get('TERM', 'unset')}\n")
            f.write(f"  isatty(stdin)={sys.stdin.isatty()}\n")
            f.write(f"  isatty(stdout)={sys.stdout.isatty()}\n")
            f.write(f"  shell={os.environ.get('SHELL', 'unset')}\n")
            size = shutil.get_terminal_size()
            f.write(f"  terminal_size={size.columns}x{size.lines}\n")
        app.run()
        with open("/tmp/impromptu_error.log", "a") as f:
            f.write("app.run() completed normally\n")
    except Exception as e:
        error_msg = traceback.format_exc()
        with open("/tmp/impromptu_error.log", "a") as f:
            f.write(f"\n{'='*60}\n{error_msg}\n")
        print(f"Error: {e}", file=sys.stderr)
        print(f"Full traceback saved to /tmp/impromptu_error.log", file=sys.stderr)
        if config.debug_mode:
            print("\nDebug mode: Press Enter to exit...", file=sys.stderr)
            input()


if __name__ == "__main__":
    main()
