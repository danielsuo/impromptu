"""
Async Unix Domain Socket server for receiving hook messages from Gemini CLI.

This provides instant IPC between Gemini CLI hooks and Impromptu using asyncio,
integrating naturally with Textual's event loop.
"""

import asyncio
import json
import time
from pathlib import Path
from typing import Callable, Optional, Any

SOCKET_DIR = Path("/tmp/impromptu_sockets")


class HookSocketServer:
    """Async socket server that listens for hook messages."""
    
    def __init__(
        self,
        agent_id: str,
        on_message: Callable[[dict], None],
    ):
        """
        Args:
            agent_id: Unique identifier for this agent
            on_message: Callback invoked with parsed JSON when a message arrives
        """
        self.agent_id = agent_id
        self.on_message = on_message
        self._server: Optional[asyncio.AbstractServer] = None
        self._running = False
        
        # Ensure socket directory exists
        SOCKET_DIR.mkdir(exist_ok=True)
    
    @property
    def socket_path(self) -> Path:
        """Path to this agent's socket file."""
        return SOCKET_DIR / f"{self.agent_id}.sock"
    
    async def start(self) -> None:
        """Start the async socket server."""
        if self._running:
            return
        
        # Clean up any existing socket
        if self.socket_path.exists():
            self.socket_path.unlink()
        
        # Create async Unix domain socket server
        self._server = await asyncio.start_unix_server(
            self._handle_client,
            path=str(self.socket_path)
        )
        self._running = True
        
        # Log for debugging
        with open("/tmp/impromptu_timing.log", "a") as f:
            f.write(f"[{time.time():.3f}] SOCKET_START agent_id={self.agent_id} path={self.socket_path}\n")
    
    async def stop(self) -> None:
        """Stop the server and clean up."""
        self._running = False
        
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        
        if self.socket_path.exists():
            try:
                self.socket_path.unlink()
            except Exception:
                pass
    
    async def _handle_client(
        self, 
        reader: asyncio.StreamReader, 
        writer: asyncio.StreamWriter
    ) -> None:
        """Handle an incoming connection."""
        try:
            # Read all data until EOF
            data = await reader.read()
            if data:
                self._process_message(data)
        except Exception as e:
            with open("/tmp/impromptu_timing.log", "a") as f:
                f.write(f"[{time.time():.3f}] SOCKET_ERROR agent_id={self.agent_id} error={e}\n")
        finally:
            writer.close()
            await writer.wait_closed()
    
    def _process_message(self, data: bytes) -> None:
        """Parse and dispatch a received message."""
        recv_time = time.time()
        try:
            text = data.decode('utf-8', errors='ignore').strip()
            message = json.loads(text)
            
            # Log receipt with timing
            event_name = message.get('hook_event_name', 'unknown')
            with open("/tmp/impromptu_timing.log", "a") as f:
                f.write(f"[{recv_time:.3f}] SOCKET_RECV agent_id={self.agent_id} event={event_name}\n")
            
            # Dispatch to callback
            self.on_message(message)
            
        except json.JSONDecodeError:
            # Not valid JSON
            with open("/tmp/impromptu_timing.log", "a") as f:
                f.write(f"[{recv_time:.3f}] SOCKET_RECV_RAW agent_id={self.agent_id} data={data[:100]}\n")
            self.on_message({"raw": data.decode('utf-8', errors='ignore')})
        except Exception as e:
            with open("/tmp/impromptu_timing.log", "a") as f:
                f.write(f"[{recv_time:.3f}] SOCKET_HANDLE_ERROR agent_id={self.agent_id} error={e}\n")
