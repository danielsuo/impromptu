"""Gemini CLI hook installer for Impromptu.

Installs hooks to ~/.gemini for state tracking and session matching.
"""

import json
import shutil
from pathlib import Path
from typing import Optional


HOOK_SCRIPTS = {
    "session_start.sh": '''#!/bin/bash
# Gemini CLI SessionStart hook for Impromptu
# Writes session ID mapping to temp file for agent-session correlation

INPUT=$(cat)

if command -v jq &> /dev/null; then
    SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // empty')
else
    SESSION_ID=$(echo "$INPUT" | grep -o '"session_id"[[:space:]]*:[[:space:]]*"[^"]*"' | sed 's/.*:.*"\\([^"]*\\)".*/\\1/')
fi

if [ -n "$IMPROMPTU_AGENT_ID" ] && [ -n "$SESSION_ID" ]; then
    MAPPING_FILE="/tmp/impromptu_session_mapping.txt"
    TEMP_FILE=$(mktemp)
    # Remove old entry for this agent, add new one (1:1 mapping)
    [ -f "$MAPPING_FILE" ] && grep -v "^${IMPROMPTU_AGENT_ID}=" "$MAPPING_FILE" > "$TEMP_FILE" 2>/dev/null || true
    echo "${IMPROMPTU_AGENT_ID}=${SESSION_ID}" >> "$TEMP_FILE"
    mv "$TEMP_FILE" "$MAPPING_FILE"
fi

exit 0
''',
    "state_tracker.sh": '''#!/bin/bash
# Gemini CLI State Tracker Hook for Impromptu

STATE_FILE="/tmp/impromptu_agent_state.txt"
INPUT=$(cat)

EVENT_NAME=$(echo "$INPUT" | grep -o '"hook_event_name"[[:space:]]*:[[:space:]]*"[^"]*"' | sed 's/.*:.*"\\([^"]*\\)".*/\\1/' || echo "")
AGENT_ID="${IMPROMPTU_AGENT_ID:-unknown}"

case "$EVENT_NAME" in
    "BeforeAgent") NEW_STATE="busy" ;;
    "AfterAgent") NEW_STATE="idle" ;;
    "BeforeModel") NEW_STATE="busy" ;;
    "AfterModel") NEW_STATE="idle" ;;
    "BeforeTool") NEW_STATE="busy" ;;
    "AfterTool") NEW_STATE="busy" ;;  # Still processing, model will respond after
    "Notification")
        NOTIFICATION_TYPE=$(echo "$INPUT" | grep -o '"notification_type"[[:space:]]*:[[:space:]]*"[^"]*"' | sed 's/.*:.*"\\([^"]*\\)".*/\\1/' || echo "")
        [ "$NOTIFICATION_TYPE" = "ToolPermission" ] && NEW_STATE="blocked"
        ;;
    *) NEW_STATE="" ;;
esac

if [ -n "$NEW_STATE" ] && [ -n "$AGENT_ID" ] && [ "$AGENT_ID" != "unknown" ]; then
    TEMP_FILE=$(mktemp)
    [ -f "$STATE_FILE" ] && grep -v "^${AGENT_ID}=" "$STATE_FILE" > "$TEMP_FILE" 2>/dev/null || true
    echo "${AGENT_ID}=${NEW_STATE}" >> "$TEMP_FILE"
    mv "$TEMP_FILE" "$STATE_FILE"
fi

exit 0
''',
}

HOOKS_CONFIG = {
    "hooks": {
        "SessionStart": [{
            "matcher": "startup",
            "hooks": [{
                "name": "impromptu-session-capture",
                "type": "command",
                "command": "$HOME/.gemini/hooks/session_start.sh",
                "description": "Captures session ID for Impromptu",
                "timeout": 5000
            }]
        }],
        "BeforeAgent": [{
            "matcher": "",
            "hooks": [{
                "name": "impromptu-state-busy-agent",
                "type": "command",
                "command": "$HOME/.gemini/hooks/state_tracker.sh",
                "description": "Sets agent state to BUSY when agent starts",
                "timeout": 5000
            }]
        }],
        "BeforeModel": [{
            "matcher": "",
            "hooks": [{
                "name": "impromptu-state-busy-model",
                "type": "command",
                "command": "$HOME/.gemini/hooks/state_tracker.sh",
                "description": "Sets agent state to BUSY when model starts",
                "timeout": 5000
            }]
        }],
        "AfterModel": [{
            "matcher": "",
            "hooks": [{
                "name": "impromptu-state-idle",
                "type": "command",
                "command": "$HOME/.gemini/hooks/state_tracker.sh",
                "description": "Sets agent state to IDLE after model response",
                "timeout": 5000
            }]
        }],
        "BeforeTool": [{
            "matcher": "",
            "hooks": [{
                "name": "impromptu-state-busy-tool",
                "type": "command",
                "command": "$HOME/.gemini/hooks/state_tracker.sh",
                "description": "Sets agent state to BUSY when tool starts",
                "timeout": 5000
            }]
        }],
        "AfterTool": [{
            "matcher": "",
            "hooks": [{
                "name": "impromptu-state-after-tool",
                "type": "command",
                "command": "$HOME/.gemini/hooks/state_tracker.sh",
                "description": "Updates agent state after tool completes",
                "timeout": 5000
            }]
        }],
        "Notification": [{
            "matcher": "ToolPermission",
            "hooks": [{
                "name": "impromptu-state-blocked",
                "type": "command",
                "command": "$HOME/.gemini/hooks/state_tracker.sh",
                "description": "Sets agent state to BLOCKED",
                "timeout": 5000
            }]
        }]
    }
}


def install_hooks() -> bool:
    """Install Impromptu hooks to ~/.gemini.
    
    Returns True if hooks were installed or updated.
    """
    gemini_dir = Path.home() / ".gemini"
    if not gemini_dir.exists():
        return False  # Gemini CLI not installed
    
    hooks_dir = gemini_dir / "hooks"
    hooks_dir.mkdir(exist_ok=True)
    
    # Install hook scripts
    for name, content in HOOK_SCRIPTS.items():
        script_path = hooks_dir / name
        script_path.write_text(content)
        script_path.chmod(0o755)
    
    # Build hooks config with absolute paths
    home_path = str(Path.home())
    hooks_config_with_paths = {}
    for event_name, event_configs in HOOKS_CONFIG["hooks"].items():
        hooks_config_with_paths[event_name] = []
        for config in event_configs:
            new_config = dict(config)
            new_hooks = []
            for hook in config.get("hooks", []):
                new_hook = dict(hook)
                # Replace $HOME with actual path
                if "command" in new_hook:
                    new_hook["command"] = new_hook["command"].replace("$HOME", home_path)
                new_hooks.append(new_hook)
            new_config["hooks"] = new_hooks
            hooks_config_with_paths[event_name].append(new_config)
    
    # Update settings.json with hook configuration
    settings_path = gemini_dir / "settings.json"
    if settings_path.exists():
        try:
            with open(settings_path, 'r') as f:
                settings = json.load(f)
        except (json.JSONDecodeError, IOError):
            settings = {}
    else:
        settings = {}
    
    # Merge hooks config (don't overwrite other settings)
    if "hooks" not in settings:
        settings["hooks"] = {}
    
    # Enable hooks in tools section (required for hooks to work)
    if "tools" not in settings:
        settings["tools"] = {}
    settings["tools"]["enableHooks"] = True
    
    for event_name, event_config in hooks_config_with_paths.items():
        settings["hooks"][event_name] = event_config
    
    with open(settings_path, 'w') as f:
        json.dump(settings, f, indent=2)
    
    return True


def hooks_installed() -> bool:
    """Check if Impromptu hooks are installed."""
    gemini_dir = Path.home() / ".gemini"
    if not gemini_dir.exists():
        return False
    
    hooks_dir = gemini_dir / "hooks"
    if not hooks_dir.exists():
        return False
    
    # Check for our hook scripts
    for name in HOOK_SCRIPTS:
        if not (hooks_dir / name).exists():
            return False
    
    return True
