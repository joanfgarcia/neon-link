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

	def __init__(self, identity_manager: IdentityManager, db_url: str | None = None, credential_path: str | None = None, agent_id: str | None = None):
		super().__init__("firebase", identity_manager)
		self.running = False
		self.db_url = db_url or os.environ.get("FIREBASE_DB_URL")
		self.credential_path = credential_path or os.environ.get("FIREBASE_CREDENTIALS")
		self.agent_id = agent_id or os.environ.get("NEON_LINK_AGENT_ID")
		self.ttl_hours = float(os.environ.get("NEON_LINK_TTL_HOURS", "24.0"))
		self.community_alias = os.environ.get("NEON_LINK_COMMUNITY_ALIAS", "default_community")

		if not self.db_url or not self.credential_path or not self.agent_id:
			logger.warning("Firebase config missing (FIREBASE_DB_URL, FIREBASE_CREDENTIALS or NEON_LINK_AGENT_ID). Plugin might fail if enabled.")

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
		self.t2 = threading.Thread(target=self._cleanup_loop)
		self.t2.daemon = True
		self.t2.start()

	async def stop(self):
		self.running = False
		if hasattr(self, "t1"):
			self.t1.join(timeout=2.0)
		if hasattr(self, "t2"):
			self.t2.join(timeout=2.0)

	async def send_event(self, event: NetworkEvent) -> bool:
		"""Route the binary event to the external network."""
		if not self.app:
			return False
		try:
			if event.recipient_id == "broadcast":
				out_ref = db.reference(f"communities/{self.community_alias}/broadcast", app=self.app)
			else:
				out_ref = db.reference(f"mailboxes/{event.recipient_id}/inbox", app=self.app)

			out_ref.push({"sender_id": self.agent_id, "mls_type": event.type, "payload": event.payload.hex(), "timestamp": time.time()})
			logger.info(f"[FirebaseHub] Sent {event.type} to {event.recipient_id}")
			return True
		except Exception as e:
			logger.error(f"[FirebaseHub] Failed to push event: {e}")
			return False

	def _is_msg_processed(self, msg_id: str) -> bool:
		from neon_link.db import get_connection
		conn = get_connection()
		try:
			cursor = conn.cursor()
			cursor.execute("SELECT 1 FROM processed_firebase_messages WHERE msg_id = ?", (msg_id,))
			return cursor.fetchone() is not None
		except Exception as e:
			logger.error(f"[FirebaseHub] Failed to check processed msg {msg_id}: {e}")
			return False
		finally:
			conn.close()

	def _mark_msg_processed(self, msg_id: str):
		from neon_link.db import get_connection
		conn = get_connection()
		try:
			conn.execute("INSERT OR IGNORE INTO processed_firebase_messages (msg_id) VALUES (?)", (msg_id,))
			conn.commit()
		except Exception as e:
			logger.error(f"[FirebaseHub] Failed to mark msg {msg_id} processed: {e}")
		finally:
			conn.close()

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
				# 1. Read private inbox
				inbox_ref = db.reference(f"mailboxes/{self.agent_id}/inbox", app=self.app)
				messages = inbox_ref.get()

				if messages and self._on_event_callback:
					for msg_id, pkg in messages.items():
						if self._is_msg_processed(msg_id):
							continue

						sender_id = pkg.get("sender_id", "unknown")
						mls_type = pkg.get("mls_type", "application")
						payload_hex = pkg.get("payload", pkg.get("ciphertext", pkg.get("content", "")))
						recipient_id = pkg.get("group_id", self.agent_id)

						if payload_hex:
							event = NetworkEvent(type=mls_type, recipient_id=recipient_id, payload=bytes.fromhex(payload_hex))
							loop.run_until_complete(self._on_event_callback(self, sender_id, event))  # type: ignore

						self._mark_msg_processed(msg_id)

				# 2. Read community broadcast
				broadcast_ref = db.reference(f"communities/{self.community_alias}/broadcast", app=self.app)
				broadcasts = broadcast_ref.get()

				if broadcasts and self._on_event_callback:
					for msg_id, pkg in broadcasts.items():
						if self._is_msg_processed(msg_id):
							continue

						sender_id = pkg.get("sender_id", "unknown")
						mls_type = pkg.get("mls_type", "broadcast")
						payload_hex = pkg.get("payload", pkg.get("ciphertext", pkg.get("content", "")))

						if payload_hex:
							event = NetworkEvent(type=mls_type, recipient_id="broadcast", payload=bytes.fromhex(payload_hex))
							loop.run_until_complete(self._on_event_callback(self, sender_id, event))  # type: ignore

						self._mark_msg_processed(msg_id)

				error_backoff = 2.0  # Reset backoff on success
				time.sleep(2.0)
			except Exception as e:
				logger.error(f"[FirebaseHub] Polling error: {e}. Retrying in {error_backoff}s...")
				time.sleep(error_backoff)
				error_backoff = min(error_backoff * 2, max_backoff)

	def _cleanup_loop(self):
		logger.info("[FirebaseHub] Started Mailbox/Cache Cleanup Daemon Loop...")
		ttl_seconds = self.ttl_hours * 3600.0

		while self.running:
			if not self.app:
				time.sleep(30)
				continue

			try:
				now = time.time()
				threshold = now - ttl_seconds

				# Sweep 1: Clean expired messages in private inbox
				inbox_ref = db.reference(f"mailboxes/{self.agent_id}/inbox", app=self.app)
				messages = inbox_ref.get()
				if messages:
					for msg_id, pkg in messages.items():
						ts = pkg.get("timestamp", 0.0)
						if ts > 0.0 and ts < threshold:
							try:
								inbox_ref.child(msg_id).delete()
								logger.info(f"[FirebaseHub] Swept expired private message {msg_id} (timestamp: {ts})")
							except Exception as e:
								logger.error(f"[FirebaseHub] Failed to delete expired message {msg_id}: {e}")

				# Sweep 2: Clean expired community broadcast messages we authored
				broadcast_ref = db.reference(f"communities/{self.community_alias}/broadcast", app=self.app)
				broadcasts = broadcast_ref.get()
				if broadcasts:
					for msg_id, pkg in broadcasts.items():
						sender_id = pkg.get("sender_id")
						ts = pkg.get("timestamp", 0.0)
						if sender_id == self.agent_id and ts > 0.0 and ts < threshold:
							try:
								broadcast_ref.child(msg_id).delete()
								logger.info(f"[FirebaseHub] Swept expired broadcast {msg_id} sent by me (timestamp: {ts})")
							except Exception as e:
								logger.error(f"[FirebaseHub] Failed to delete expired broadcast {msg_id}: {e}")

				# Sweep 3: Clean local processed message cache in events.db (processed_at < 2 * TTL_HOURS ago)
				local_threshold_hours = self.ttl_hours * 2.0
				from neon_link.db import get_connection
				conn = get_connection()
				try:
					conn.execute(
						"DELETE FROM processed_firebase_messages WHERE processed_at < datetime('now', ?)",
						(f"-{local_threshold_hours} hours",)
					)
					conn.commit()
				except Exception as e:
					logger.error(f"[FirebaseHub] Failed to purge local tracking cache: {e}")
				finally:
					conn.close()

			except Exception as e:
				logger.error(f"[FirebaseHub] Cleanup sweep failed: {e}")

			# Sleep for 5 minutes (300 seconds) between sweeps
			time.sleep(300)
