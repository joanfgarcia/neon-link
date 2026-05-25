import asyncio
import json
import logging
import os
from typing import Any

from neon_rings.client import RingsClient
from neon_rings.crypto import KeyPair

from neon_link.core.crypto import IdentityManager
from neon_link.models.network import NetworkEvent
from neon_link.plugins.base import NetworkPlugin

logger = logging.getLogger(__name__)


class RingsHub(NetworkPlugin):
	"""
	Rings Transport Plugin (Dumb P2P Layer).
	Only handles WebSocket connection to the Rings Server/Hub, registers agent_id,
	and sends/receives payloads. No crypto logic inside this layer.
	"""

	def __init__(self, identity_manager: IdentityManager, endpoint_url: str | None = None, agent_id: str | None = None):
		super().__init__("rings", identity_manager)
		self.endpoint_url = endpoint_url or os.environ.get("RINGS_ENDPOINT_URL") or "ws://localhost:50000"
		self.agent_id = agent_id or os.environ.get("NEON_LINK_AGENT_ID")
		self.running = False
		self.client: RingsClient | None = None

		if not self.endpoint_url or not self.agent_id:
			logger.warning("Rings config missing (RINGS_ENDPOINT_URL or NEON_LINK_AGENT_ID). Plugin might fail if enabled.")

		# Grab our private signature key to use for DHT registration / identification
		identities = self.identity_manager.get_identities()
		if identities:
			_, sig_key = list(identities.values())[0]
			self.keypair = KeyPair(sig_key._private_key)
		else:
			self.keypair = KeyPair.generate()

	async def fetch_key_package(self, agent_id: str) -> bytes | None:
		"""Fetch remote KeyPackage via DHT"""
		if not self.client:
			return None
		# If it's a valid hex key, get from DHT
		if len(agent_id) == 64 and all(c in "0123456789abcdefABCDEF" for c in agent_id):
			try:
				data = await self.client.dht_get(agent_id)
				if data:
					return bytes.fromhex(data)
			except Exception as e:
				logger.error(f"[RingsHub] Failed to fetch KeyPackage from DHT: {e}")
		return None

	def publish_my_key_package(self, kp_bytes: bytes):
		if not self.client:
			return
		try:
			loop = asyncio.get_event_loop()
			if loop.is_running():
				asyncio.create_task(self.client.dht_put(self.keypair, kp_bytes.hex()))
			else:
				loop.run_until_complete(self.client.dht_put(self.keypair, kp_bytes.hex()))
			logger.info(f"[RingsHub] Published KeyPackage to DHT under key {self.keypair.public_key_hex}")
		except Exception as e:
			logger.error(f"[RingsHub] Failed to publish KeyPackage: {e}")

	async def start(self):
		self.running = True
		logger.info(f"[RingsHub] Connecting to Rings Server at {self.endpoint_url}...")
		self.client = RingsClient(url=self.endpoint_url)
		await self.client.connect()

		# Register using either the configured agent_id or fallback to public key hex
		node_id = self.agent_id or self.keypair.public_key_hex
		await self.client.register(node_id)
		logger.info(f"[RingsHub] Registered node {node_id}")

		# Set message handler
		self.client.set_message_handler(self._handle_message)

	async def stop(self):
		self.running = False
		if self.client:
			await self.client.disconnect()
			self.client = None

	async def send_event(self, event: NetworkEvent) -> bool:
		if not self.client:
			logger.error("[RingsHub] Client not connected.")
			return False

		try:
			payload = {"type": event.type, "recipient_id": event.recipient_id, "payload_hex": event.payload.hex()}
			# Send via Rings P2P client
			res = await self.client.send_message(target_id=event.recipient_id, payload=payload)
			if isinstance(res, dict) and res.get("ok") and res.get("delivered"):
				return True
			logger.warning(f"[RingsHub] Message delivery failed: {res}")
			return False
		except Exception as e:
			logger.error(f"[RingsHub] Failed to send P2P message: {e}")
			return False

	async def _handle_message(self, sender_id: str, payload: Any):
		if not self._on_event_callback:
			return

		try:
			if isinstance(payload, str):
				payload = json.loads(payload)

			mls_type = payload.get("type", "application")
			payload_hex = payload.get("payload_hex", "")
			recipient_id = payload.get("recipient_id", self.agent_id)

			if payload_hex:
				event = NetworkEvent(type=mls_type, recipient_id=recipient_id, payload=bytes.fromhex(payload_hex))
				# Dispatch to Crypto Pipeline
				await self._on_event_callback(self, sender_id, event)
		except Exception as e:
			logger.error(f"[RingsHub] Error handling inbound message: {e}")
