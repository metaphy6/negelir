"""
Negelir P2P — TCP transport for real network communication.
Phase 9: Drop-in replacement for SimulatedTransport using real TCP sockets.
Implements the same interface: register_node, send, broadcast, get_pending.
"""

import asyncio
import json
import ssl
import struct
from dataclasses import dataclass, field

from protocol.messages import P2PMessage
from node.peer import get_p2p_logger

log = get_p2p_logger("tcp_transport")

# Message frame: 4-byte length prefix + payload
HEADER_SIZE = 4
MAX_MESSAGE_SIZE = 1024 * 1024  # 1 MB


@dataclass
class TcpTransportConfig:
    """Configuration for TCP transport."""
    host: str = "0.0.0.0"
    port: int = 9742
    use_tls: bool = False
    cert_path: str = ""
    key_path: str = ""
    ca_path: str = ""
    connect_timeout: float = 5.0
    read_timeout: float = 10.0


@dataclass
class PeerConnection:
    """Active connection to a remote peer."""
    peer_id: str
    host: str
    port: int
    reader: asyncio.StreamReader | None = None
    writer: asyncio.StreamWriter | None = None
    connected: bool = False


class TcpTransport:
    """
    Real TCP transport for P2P communication.
    Same interface as SimulatedTransport for drop-in replacement.

    Features:
      - Length-prefixed message framing
      - Optional mTLS (self-signed certificates)
      - Wire serialization via P2PMessage.to_bytes/from_bytes
      - Per-node inbox queue (same as SimulatedTransport)
    """

    def __init__(self, config: TcpTransportConfig | None = None):
        self.config = config or TcpTransportConfig()
        self.node_inboxes: dict[str, asyncio.Queue] = {}
        self._connections: dict[str, PeerConnection] = {}
        self._server: asyncio.Server | None = None
        self._local_node_id: str = ""
        self._ssl_context: ssl.SSLContext | None = None
        self._running = False

    def _create_ssl_context(self) -> ssl.SSLContext | None:
        """Create mTLS context if TLS is enabled."""
        if not self.config.use_tls:
            return None
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_3
        if self.config.cert_path and self.config.key_path:
            ctx.load_cert_chain(self.config.cert_path, self.config.key_path)
        if self.config.ca_path:
            ctx.load_verify_locations(self.config.ca_path)
        else:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        return ctx

    def register_node(self, node_id: str):
        """Register a local node with an inbox queue."""
        self.node_inboxes[node_id] = asyncio.Queue()
        if not self._local_node_id:
            self._local_node_id = node_id
        log.debug(f"Node registered: {node_id[:8]}")

    def unregister_node(self, node_id: str) -> bool:
        """Remove a node from the transport."""
        if node_id in self.node_inboxes:
            del self.node_inboxes[node_id]
            return True
        return False

    def add_peer(self, peer_id: str, host: str, port: int):
        """Register a known remote peer for outbound connections."""
        self._connections[peer_id] = PeerConnection(
            peer_id=peer_id, host=host, port=port
        )

    async def start_server(self):
        """Start listening for incoming connections."""
        self._ssl_context = self._create_ssl_context()
        self._server = await asyncio.start_server(
            self._handle_connection,
            self.config.host,
            self.config.port,
            ssl=self._ssl_context,
        )
        self._running = True
        log.info(f"TCP server listening on {self.config.host}:{self.config.port}")

    async def stop(self):
        """Shut down the transport."""
        self._running = False
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        for conn in self._connections.values():
            if conn.writer:
                conn.writer.close()
        log.info("TCP transport stopped")

    async def _handle_connection(self, reader: asyncio.StreamReader,
                                  writer: asyncio.StreamWriter):
        """Handle an incoming TCP connection."""
        addr = writer.get_extra_info("peername")
        log.debug(f"Incoming connection from {addr}")
        try:
            while self._running:
                msg = await self._read_message(reader)
                if msg is None:
                    break
                # Route to local node inbox
                target = self._local_node_id
                if target and target in self.node_inboxes:
                    self.node_inboxes[target].put_nowait(msg)
        except (asyncio.IncompleteReadError, ConnectionResetError):
            pass
        finally:
            writer.close()

    async def _connect_to_peer(self, peer: PeerConnection) -> bool:
        """Establish outbound TCP connection to a peer."""
        if peer.connected and peer.writer:
            return True
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(
                    peer.host, peer.port,
                    ssl=self._ssl_context,
                ),
                timeout=self.config.connect_timeout,
            )
            peer.reader = reader
            peer.writer = writer
            peer.connected = True
            log.info(f"Connected to peer {peer.peer_id[:8]} at {peer.host}:{peer.port}")
            return True
        except (OSError, asyncio.TimeoutError) as e:
            log.warning(f"Failed to connect to {peer.peer_id[:8]}: {e}")
            peer.connected = False
            return False

    @staticmethod
    async def _write_message(writer: asyncio.StreamWriter, message: P2PMessage):
        """Write a length-prefixed message to a stream."""
        data = message.to_bytes()
        if len(data) > MAX_MESSAGE_SIZE:
            raise ValueError(f"Message too large: {len(data)} bytes")
        header = struct.pack("!I", len(data))
        writer.write(header + data)
        await writer.drain()

    @staticmethod
    async def _read_message(reader: asyncio.StreamReader) -> P2PMessage | None:
        """Read a length-prefixed message from a stream."""
        try:
            header = await reader.readexactly(HEADER_SIZE)
            length = struct.unpack("!I", header)[0]
            if length > MAX_MESSAGE_SIZE:
                return None
            data = await reader.readexactly(length)
            return P2PMessage.from_bytes(data)
        except (asyncio.IncompleteReadError, struct.error):
            return None

    def send(self, sender_id: str, target_id: str, message: P2PMessage):
        """
        Send a message to a specific peer.
        Synchronous wrapper that schedules the async send.
        Falls back to inbox delivery for local nodes (test compatibility).
        """
        # Local delivery (same process)
        if target_id in self.node_inboxes:
            wire = message.to_bytes()
            received = P2PMessage.from_bytes(wire)
            self.node_inboxes[target_id].put_nowait(received)
            return

        # Remote delivery would use _connect_to_peer + _write_message
        peer = self._connections.get(target_id)
        if peer:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(self._async_send(peer, message))
            else:
                loop.run_until_complete(self._async_send(peer, message))

    async def _async_send(self, peer: PeerConnection, message: P2PMessage):
        """Async send to a remote peer."""
        if not await self._connect_to_peer(peer):
            return
        try:
            await self._write_message(peer.writer, message)
        except (OSError, asyncio.TimeoutError) as e:
            log.warning(f"Send failed to {peer.peer_id[:8]}: {e}")
            peer.connected = False

    def broadcast(self, sender_id: str, message: P2PMessage):
        """Broadcast to all known peers (local + remote)."""
        for node_id in list(self.node_inboxes.keys()):
            if node_id != sender_id:
                self.send(sender_id, node_id, message)
        for peer_id in self._connections:
            if peer_id != sender_id:
                self.send(sender_id, peer_id, message)

    def get_pending(self, node_id: str) -> list[P2PMessage]:
        """Get all pending messages for a node (non-blocking)."""
        inbox = self.node_inboxes.get(node_id)
        if not inbox:
            return []
        messages = []
        while not inbox.empty():
            try:
                messages.append(inbox.get_nowait())
            except asyncio.QueueEmpty:
                break
        return messages

    @property
    def node_count(self) -> int:
        return len(self.node_inboxes)

    def get_neighbors(self, node_id: str) -> list[str]:
        """Return all known peers (no topology limit in TCP mode)."""
        local = [n for n in self.node_inboxes if n != node_id]
        remote = [p for p in self._connections if p != node_id]
        return local + remote
