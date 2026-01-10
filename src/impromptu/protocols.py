"""Agent protocol abstraction for pluggable backends."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator, Callable, Optional
import asyncio

from .models import Agent, AgentStatus, ContextItem


class AgentProtocol(ABC):
    """Abstract base class for agent communication protocols."""

    @abstractmethod
    async def connect(self, agent_id: str, config: dict) -> Agent:
        """Connect to an agent and return its initial state."""
        pass

    @abstractmethod
    async def disconnect(self, agent_id: str) -> None:
        """Disconnect from an agent."""
        pass

    @abstractmethod
    async def send_message(self, agent_id: str, message: str) -> None:
        """Send a message to an agent."""
        pass

    @abstractmethod
    async def get_thinking_stream(self, agent_id: str) -> AsyncIterator[str]:
        """Get a stream of thinking updates from an agent."""
        pass

    @abstractmethod
    async def get_status(self, agent_id: str) -> AgentStatus:
        """Get the current status of an agent."""
        pass

    @abstractmethod
    async def get_context(self, agent_id: str) -> list[ContextItem]:
        """Get the current context items for an agent."""
        pass


@dataclass
class AgentConfig:
    """Configuration for an agent connection."""
    id: str
    name: str
    protocol: str  # "mock", "http", "subprocess"
    config: dict  # Protocol-specific config


class MockAgentProtocol(AgentProtocol):
    """Mock protocol for development and testing."""

    def __init__(self):
        self._agents: dict[str, Agent] = {}
        self._thinking_queues: dict[str, asyncio.Queue] = {}

    async def connect(self, agent_id: str, config: dict) -> Agent:
        """Create a mock agent."""
        from .agent_manager import create_mock_agents

        # Use predefined mock agents or create new one
        mock_agents = {a.id: a for a in create_mock_agents()}
        if agent_id in mock_agents:
            agent = mock_agents[agent_id]
        else:
            agent = Agent(
                id=agent_id,
                name=config.get("name", f"Agent {agent_id}"),
                status=AgentStatus.IDLE,
            )

        self._agents[agent_id] = agent
        self._thinking_queues[agent_id] = asyncio.Queue()
        return agent

    async def disconnect(self, agent_id: str) -> None:
        """Disconnect mock agent."""
        self._agents.pop(agent_id, None)
        self._thinking_queues.pop(agent_id, None)

    async def send_message(self, agent_id: str, message: str) -> None:
        """Simulate processing a message."""
        if agent := self._agents.get(agent_id):
            agent.status = AgentStatus.THINKING
            await self._thinking_queues[agent_id].put(f"Processing: {message}")

    async def get_thinking_stream(self, agent_id: str) -> AsyncIterator[str]:
        """Stream mock thinking updates."""
        queue = self._thinking_queues.get(agent_id)
        if not queue:
            return

        while True:
            try:
                thought = await asyncio.wait_for(queue.get(), timeout=0.1)
                yield thought
            except asyncio.TimeoutError:
                pass

    async def get_status(self, agent_id: str) -> AgentStatus:
        """Get mock agent status."""
        if agent := self._agents.get(agent_id):
            return agent.status
        return AgentStatus.ERROR

    async def get_context(self, agent_id: str) -> list[ContextItem]:
        """Get mock agent context."""
        if agent := self._agents.get(agent_id):
            return agent.context
        return []


class HTTPAgentProtocol(AgentProtocol):
    """Protocol for agents accessible via HTTP REST API."""

    def __init__(self):
        self._base_urls: dict[str, str] = {}
        self._agents: dict[str, Agent] = {}

    async def connect(self, agent_id: str, config: dict) -> Agent:
        """Connect to an HTTP agent."""
        base_url = config.get("url", "http://localhost:8000")
        self._base_urls[agent_id] = base_url

        # Try to fetch agent info
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{base_url}/agent/{agent_id}") as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        agent = Agent(
                            id=agent_id,
                            name=data.get("name", agent_id),
                            status=AgentStatus(data.get("status", "idle")),
                        )
                        self._agents[agent_id] = agent
                        return agent
        except Exception:
            pass

        # Fallback to basic agent
        agent = Agent(
            id=agent_id,
            name=config.get("name", agent_id),
            status=AgentStatus.IDLE,
        )
        self._agents[agent_id] = agent
        return agent

    async def disconnect(self, agent_id: str) -> None:
        """Disconnect from HTTP agent."""
        self._base_urls.pop(agent_id, None)
        self._agents.pop(agent_id, None)

    async def send_message(self, agent_id: str, message: str) -> None:
        """Send message via HTTP POST."""
        base_url = self._base_urls.get(agent_id)
        if not base_url:
            return

        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                await session.post(
                    f"{base_url}/agent/{agent_id}/message",
                    json={"message": message},
                )
        except Exception:
            pass

    async def get_thinking_stream(self, agent_id: str) -> AsyncIterator[str]:
        """Stream thinking via Server-Sent Events."""
        base_url = self._base_urls.get(agent_id)
        if not base_url:
            return

        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{base_url}/agent/{agent_id}/stream") as resp:
                    async for line in resp.content:
                        if line:
                            yield line.decode().strip()
        except Exception:
            pass

    async def get_status(self, agent_id: str) -> AgentStatus:
        """Get status via HTTP."""
        base_url = self._base_urls.get(agent_id)
        if not base_url:
            return AgentStatus.ERROR

        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{base_url}/agent/{agent_id}/status") as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return AgentStatus(data.get("status", "idle"))
        except Exception:
            pass

        return AgentStatus.ERROR

    async def get_context(self, agent_id: str) -> list[ContextItem]:
        """Get context via HTTP."""
        # TODO: Implement context fetching
        return []


class SubprocessAgentProtocol(AgentProtocol):
    """Protocol for agents running as subprocesses."""

    def __init__(self):
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._agents: dict[str, Agent] = {}
        self._output_queues: dict[str, asyncio.Queue] = {}

    async def connect(self, agent_id: str, config: dict) -> Agent:
        """Start an agent subprocess."""
        command = config.get("command", [])
        if not command:
            raise ValueError(f"No command specified for agent {agent_id}")

        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        self._processes[agent_id] = process
        self._output_queues[agent_id] = asyncio.Queue()

        agent = Agent(
            id=agent_id,
            name=config.get("name", agent_id),
            status=AgentStatus.IDLE,
        )
        self._agents[agent_id] = agent

        # Start reading output in background
        asyncio.create_task(self._read_output(agent_id))

        return agent

    async def _read_output(self, agent_id: str) -> None:
        """Read subprocess output and queue it."""
        process = self._processes.get(agent_id)
        if not process or not process.stdout:
            return

        while True:
            line = await process.stdout.readline()
            if not line:
                break
            await self._output_queues[agent_id].put(line.decode().strip())

    async def disconnect(self, agent_id: str) -> None:
        """Terminate the subprocess."""
        if process := self._processes.pop(agent_id, None):
            process.terminate()
            await process.wait()
        self._agents.pop(agent_id, None)
        self._output_queues.pop(agent_id, None)

    async def send_message(self, agent_id: str, message: str) -> None:
        """Send message to subprocess stdin."""
        process = self._processes.get(agent_id)
        if process and process.stdin:
            process.stdin.write(f"{message}\n".encode())
            await process.stdin.drain()

    async def get_thinking_stream(self, agent_id: str) -> AsyncIterator[str]:
        """Stream subprocess output."""
        queue = self._output_queues.get(agent_id)
        if not queue:
            return

        while True:
            try:
                line = await asyncio.wait_for(queue.get(), timeout=0.1)
                yield line
            except asyncio.TimeoutError:
                pass

    async def get_status(self, agent_id: str) -> AgentStatus:
        """Check if subprocess is running."""
        process = self._processes.get(agent_id)
        if process and process.returncode is None:
            return AgentStatus.THINKING
        return AgentStatus.IDLE

    async def get_context(self, agent_id: str) -> list[ContextItem]:
        """Get context from subprocess (not implemented)."""
        return []


def get_protocol(protocol_name: str) -> AgentProtocol:
    """Get a protocol instance by name."""
    protocols = {
        "mock": MockAgentProtocol,
        "http": HTTPAgentProtocol,
        "subprocess": SubprocessAgentProtocol,
        "acp": ACPAgentProtocol,
        "gemini": GeminiCLIProtocol,
    }

    protocol_class = protocols.get(protocol_name, MockAgentProtocol)
    return protocol_class()


class GeminiCLIProtocol(AgentProtocol):
    """Protocol for Google's Gemini CLI.

    Runs gemini-cli as a subprocess and streams its output.
    Supports both interactive mode and one-shot queries.
    """

    def __init__(self):
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._agents: dict[str, Agent] = {}
        self._output_queues: dict[str, asyncio.Queue] = {}
        self._yolo_mode: dict[str, bool] = {}

    async def connect(self, agent_id: str, config: dict) -> Agent:
        """Start a gemini-cli session."""
        yolo = config.get("yolo", False)
        model = config.get("model", None)
        sandbox = config.get("sandbox", False)

        self._yolo_mode[agent_id] = yolo
        self._output_queues[agent_id] = asyncio.Queue()

        agent = Agent(
            id=agent_id,
            name=config.get("name", "Gemini"),
            status=AgentStatus.IDLE,
        )
        self._agents[agent_id] = agent

        return agent

    async def _start_session(self, agent_id: str, prompt: str) -> None:
        """Start a gemini-cli process for a prompt."""
        if agent_id in self._processes:
            # Kill existing process
            try:
                self._processes[agent_id].terminate()
                await self._processes[agent_id].wait()
            except Exception:
                pass

        # Build command
        cmd = ["gemini"]

        if self._yolo_mode.get(agent_id, False):
            cmd.append("--yolo")

        # Add the prompt as positional argument
        cmd.append(prompt)

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        self._processes[agent_id] = process

        # Start reading output in background
        asyncio.create_task(self._read_output(agent_id))

    async def _read_output(self, agent_id: str) -> None:
        """Read gemini-cli output and queue it."""
        process = self._processes.get(agent_id)
        if not process or not process.stdout:
            return

        if agent := self._agents.get(agent_id):
            agent.status = AgentStatus.THINKING

        buffer = ""
        while True:
            chunk = await process.stdout.read(100)
            if not chunk:
                break

            text = chunk.decode("utf-8", errors="replace")
            buffer += text

            # Split on newlines and queue complete lines
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                if line.strip():
                    await self._output_queues[agent_id].put(line)

        # Queue any remaining text
        if buffer.strip():
            await self._output_queues[agent_id].put(buffer)

        # Mark as ready when done
        if agent := self._agents.get(agent_id):
            agent.status = AgentStatus.READY

    async def disconnect(self, agent_id: str) -> None:
        """Terminate the gemini-cli process."""
        if process := self._processes.pop(agent_id, None):
            try:
                process.terminate()
                await process.wait()
            except Exception:
                pass
        self._agents.pop(agent_id, None)
        self._output_queues.pop(agent_id, None)
        self._yolo_mode.pop(agent_id, None)

    async def send_message(self, agent_id: str, message: str) -> None:
        """Send a message by starting a new gemini-cli run."""
        if agent := self._agents.get(agent_id):
            agent.status = AgentStatus.THINKING
            agent.thinking = ""

        # Clear the queue
        queue = self._output_queues.get(agent_id)
        if queue:
            while not queue.empty():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    break

        # Start a new session with this prompt
        await self._start_session(agent_id, message)

    async def get_thinking_stream(self, agent_id: str) -> AsyncIterator[str]:
        """Stream gemini-cli output."""
        queue = self._output_queues.get(agent_id)
        if not queue:
            return

        while True:
            try:
                line = await asyncio.wait_for(queue.get(), timeout=0.1)
                # Skip ANSI escape sequences for cleaner output
                import re
                clean_line = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', line)
                if clean_line.strip():
                    yield clean_line
            except asyncio.TimeoutError:
                pass

    async def get_status(self, agent_id: str) -> AgentStatus:
        """Check gemini-cli status."""
        if agent := self._agents.get(agent_id):
            return agent.status
        return AgentStatus.ERROR

    async def get_context(self, agent_id: str) -> list[ContextItem]:
        """Get context (gemini-cli doesn't expose this directly)."""
        return []


class ACPAgentProtocol(AgentProtocol):
    """Agent Client Protocol (ACP) implementation.

    Uses JSON-RPC 2.0 over HTTP/WebSocket as defined at:
    https://agentclientprotocol.com/protocol/overview
    """

    PROTOCOL_VERSION = 1
    CLIENT_INFO = {
        "name": "tui",
        "title": "Multi-Agent TUI",
        "version": "0.1.0",
    }

    def __init__(self):
        self._base_urls: dict[str, str] = {}
        self._agents: dict[str, Agent] = {}
        self._sessions: dict[str, str] = {}  # agent_id -> session_id
        self._request_id = 0
        self._update_queues: dict[str, asyncio.Queue] = {}

    def _next_id(self) -> int:
        """Get the next JSON-RPC request ID."""
        self._request_id += 1
        return self._request_id

    async def _jsonrpc_call(
        self, base_url: str, method: str, params: dict | None = None
    ) -> dict:
        """Make a JSON-RPC 2.0 call."""
        try:
            import aiohttp

            request = {
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "method": method,
            }
            if params:
                request["params"] = params

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    base_url,
                    json=request,
                    headers={"Content-Type": "application/json"},
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    return {"error": {"code": resp.status, "message": await resp.text()}}
        except Exception as e:
            return {"error": {"code": -1, "message": str(e)}}

    async def connect(self, agent_id: str, config: dict) -> Agent:
        """Connect to an ACP agent via initialize handshake."""
        base_url = config.get("url", "http://localhost:8000")
        self._base_urls[agent_id] = base_url
        self._update_queues[agent_id] = asyncio.Queue()

        # Step 1: Initialize
        init_response = await self._jsonrpc_call(
            base_url,
            "initialize",
            {
                "protocolVersion": self.PROTOCOL_VERSION,
                "clientCapabilities": {
                    "fs": {"readTextFile": True, "writeTextFile": True},
                    "terminal": True,
                },
                "clientInfo": self.CLIENT_INFO,
            },
        )

        agent_info = {}
        if "result" in init_response:
            result = init_response["result"]
            agent_info = result.get("agentInfo", {})

        # Step 2: Create session
        session_response = await self._jsonrpc_call(base_url, "session/new", {})
        session_id = ""
        if "result" in session_response:
            session_id = session_response["result"].get("sessionId", "")
        self._sessions[agent_id] = session_id

        agent = Agent(
            id=agent_id,
            name=agent_info.get("title", config.get("name", agent_id)),
            status=AgentStatus.IDLE,
        )
        self._agents[agent_id] = agent
        return agent

    async def disconnect(self, agent_id: str) -> None:
        """Disconnect from ACP agent."""
        self._base_urls.pop(agent_id, None)
        self._agents.pop(agent_id, None)
        self._sessions.pop(agent_id, None)
        self._update_queues.pop(agent_id, None)

    async def send_message(self, agent_id: str, message: str) -> None:
        """Send a prompt to the agent via session/prompt."""
        base_url = self._base_urls.get(agent_id)
        session_id = self._sessions.get(agent_id)
        if not base_url or not session_id:
            return

        if agent := self._agents.get(agent_id):
            agent.status = AgentStatus.THINKING

        # Send prompt and stream updates
        try:
            import aiohttp

            request = {
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "method": "session/prompt",
                "params": {
                    "sessionId": session_id,
                    "content": [{"type": "text", "text": message}],
                },
            }

            async with aiohttp.ClientSession() as session:
                # Use SSE or streaming if available
                async with session.post(
                    base_url,
                    json=request,
                    headers={
                        "Content-Type": "application/json",
                        "Accept": "text/event-stream",
                    },
                ) as resp:
                    # Handle streaming updates
                    async for line in resp.content:
                        if line:
                            decoded = line.decode().strip()
                            if decoded.startswith("data:"):
                                data = decoded[5:].strip()
                                await self._update_queues[agent_id].put(data)

                    # Mark as ready when done
                    if agent := self._agents.get(agent_id):
                        agent.status = AgentStatus.READY

        except Exception as e:
            await self._update_queues[agent_id].put(f"Error: {e}")
            if agent := self._agents.get(agent_id):
                agent.status = AgentStatus.ERROR

    async def get_thinking_stream(self, agent_id: str) -> AsyncIterator[str]:
        """Stream session/update notifications."""
        queue = self._update_queues.get(agent_id)
        if not queue:
            return

        while True:
            try:
                update = await asyncio.wait_for(queue.get(), timeout=0.1)
                # Parse JSON-RPC notification if needed
                try:
                    import json
                    data = json.loads(update)
                    if "params" in data and "content" in data["params"]:
                        for block in data["params"]["content"]:
                            if block.get("type") == "text":
                                yield block.get("text", "")
                    else:
                        yield update
                except (json.JSONDecodeError, KeyError):
                    yield update
            except asyncio.TimeoutError:
                pass

    async def get_status(self, agent_id: str) -> AgentStatus:
        """Get current agent status."""
        if agent := self._agents.get(agent_id):
            return agent.status
        return AgentStatus.ERROR

    async def get_context(self, agent_id: str) -> list[ContextItem]:
        """Get context from agent (would require additional ACP methods)."""
        # ACP doesn't have a standard context fetching method yet
        if agent := self._agents.get(agent_id):
            return agent.context
        return []
