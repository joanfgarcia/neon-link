import logging
import os
from typing import Any

from neon_rings.client import RingsClient

from neon_link.core.crypto import IdentityManager
from neon_link.models.network import NetworkEvent
from neon_link.plugins.base import NetworkPlugin

logger = logging.getLogger(__name__)


class RingsHub(NetworkPlugin):
	"""
	Neon-Rings P2P Transport Plugin.
	"""

	def __init__(self, identity_manager: IdentityManager, ws_url: str | None = None, agent_id: str | None = None):
		super().__init__("rings", identity_manager)
		self.ws_url = ws_url or os.environ.get("RINGS_WS_URL", "ws://127.0.0.1:50000/jsonrpc")
		self.agent_id = agent_id or os.environ.get("NEON_LINK_AGENT_ID", "unknown_agent")
		self.client = RingsClient(url=self.ws_url)

	async def start(self):
		logger.info(f"[RingsHub] Connecting to P2P network at {self.ws_url}...")
		await self.client.connect()
		await self.client.register(self.agent_id)
		self.client.set_message_handler(self._on_message)
		logger.info(f"[RingsHub] Connected and registered as {self.agent_id}")

	def publish_my_key_package(self, kp_bytes: bytes):
		"""
		In a real DHT, we would publish the KeyPackage here.
		Currently Rings DHT uses Ed25519 pubkeys as DHT keys.
		"""
		pass

	async def fetch_key_package(self, agent_id: str) -> bytes | None:
		"""Fetch remote KeyPackage via Rings DHT"""
		return None

	async def stop(self):
		await self.client.disconnect()

	async def send_event(self, event: NetworkEvent) -> bool:
		"""Route the binary event to the external network."""
		try:
			payload = {
				"sender_id": self.agent_id,
				"mls_type": event.type,
				"payload": event.payload.hex(),
			}
			await self.client.send_message(event.recipient_id, payload)
			logger.info(f"[RingsHub] Sent {event.type} to {event.recipient_id}")
			return True
		except Exception as e:
			logger.error(f"[RingsHub] Failed to push event: {e}")
			return False

	async def _on_message(self, sender_id: str, payload: Any):
		if not self._on_event_callback:
			return

		if isinstance(payload, dict):
			mls_type = payload.get("mls_type", "application")
			payload_hex = payload.get("payload", "")

			if payload_hex:
				event = NetworkEvent(type=mls_type, recipient_id=self.agent_id, payload=bytes.fromhex(payload_hex))
				# Dispatch to Crypto Pipeline
				await self._on_event_callback(self, sender_id, event)  # type: ignore
