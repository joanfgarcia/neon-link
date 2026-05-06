import asyncio
import logging
import os
import threading
import time

import firebase_admin
from firebase_admin import credentials, db

from neon_link.core.crypto import IdentityManager
from neon_link.models.network import NetworkEvent
from neon_link.plugins.base import NetworkPlugin

logger = logging.getLogger(__name__)


class FirebaseHub(NetworkPlugin):
	"""
	Firebase Transport Plugin (Dumb Layer).
	Only handles Firebase RTDB logic, push/pull bytes. No Crypto logic.
	"""

	def __init__(self, identity_manager: IdentityManager):
		super().__init__("firebase", identity_manager)
		self.running = False
		self.db_url = os.environ.get("FIREBASE_DB_URL", "https://replace-me.firebaseio.com")
		self.credential_path = os.environ.get("FIREBASE_CREDENTIALS", "firebase-keys.json")
		self.agent_id = os.environ.get("NEON_LINK_AGENT_ID", "red_pill_core")

		logger.info("[FirebaseHub] Initializing Firebase SDK...")
		try:
			firebase_admin.get_app("neon_link")
		except ValueError:
			try:
				cred = credentials.Certificate(self.credential_path)
				firebase_admin.initialize_app(cred, {"databaseURL": self.db_url}, name="neon_link")
			except Exception as e:
				logger.error(f"Failed to load Firebase credentials from {self.credential_path}: {e}")

		try:
			self.app = firebase_admin.get_app("neon_link")
		except ValueError:
			self.app = None

	async def fetch_key_package(self, agent_id: str) -> bytes | None:
		"""Fetch remote KeyPackage via Firebase"""
		if not self.app:
			return None
		ref = db.reference(f"public_keys/{agent_id}", app=self.app)
		data = ref.get()
		if data and "key_package" in data:
			return bytes.fromhex(data["key_package"])
		return None

	def publish_my_key_package(self, kp_bytes: bytes):
		if not self.app:
			return
		try:
			ref = db.reference(f"public_keys/{self.agent_id}", app=self.app)
			ref.set({"key_package": kp_bytes.hex()})
			logger.info(f"[FirebaseHub] Published KeyPackage to Firebase for {self.agent_id}")
		except Exception as e:
			logger.error(f"Failed to publish KeyPackage: {e}")

	async def start(self):
		self.running = True
		self.t1 = threading.Thread(target=self._poll_firebase)
		self.t1.daemon = True
		self.t1.start()

	async def stop(self):
		self.running = False
		if hasattr(self, "t1"):
			self.t1.join(timeout=2.0)

	async def send_event(self, event: NetworkEvent) -> bool:
		"""Route the binary event to the external network."""
		if not self.app:
			return False
		try:
			# We route everything to the recipient's inbox for now to mimic the P2P swarm model
			# In a full group setup, we might write to mailboxes/{group_id}/messages
			out_ref = db.reference(f"mailboxes/{event.recipient_id}/inbox", app=self.app)

			out_ref.push({"sender_id": self.agent_id, "mls_type": event.type, "payload": event.payload.hex(), "timestamp": time.time()})
			logger.info(f"[FirebaseHub] Sent {event.type} to {event.recipient_id}")
			return True
		except Exception as e:
			logger.error(f"[FirebaseHub] Failed to push event: {e}")
			return False

	def _poll_firebase(self):
		logger.info("[FirebaseHub] Started Firebase Ingress Polling...")
		loop = asyncio.new_event_loop()
		asyncio.set_event_loop(loop)

		error_backoff = 2.0
		max_backoff = 30.0

		while self.running:
			if not self.app:
				break

			try:
				# Read private inbox
				inbox_ref = db.reference(f"mailboxes/{self.agent_id}/inbox", app=self.app)
				messages = inbox_ref.get()

				if messages and self._on_event_callback:
					for msg_id, pkg in messages.items():
						sender_id = pkg.get("sender_id", "unknown")
						mls_type = pkg.get("mls_type", "application")
						payload_hex = pkg.get("payload", pkg.get("ciphertext", pkg.get("content", "")))

						# Fallback for old group_id format if present
						recipient_id = pkg.get("group_id", self.agent_id)

						if payload_hex:
							event = NetworkEvent(type=mls_type, recipient_id=recipient_id, payload=bytes.fromhex(payload_hex))
							# Dispatch to Crypto Pipeline
							loop.run_until_complete(self._on_event_callback(self, sender_id, event))  # type: ignore

						inbox_ref.child(msg_id).delete()
				error_backoff = 2.0  # Reset backoff on success
				time.sleep(2.0)
			except Exception as e:
				logger.error(f"[FirebaseHub] Polling error: {e}. Retrying in {error_backoff}s...")
				time.sleep(error_backoff)
				error_backoff = min(error_backoff * 2, max_backoff)
