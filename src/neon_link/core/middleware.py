import hashlib
import json
import logging
import sqlite3

from pure_mls.group import MLSGroup, MLSMessage
from pure_mls.tree import KeyPackage

from neon_link.core.crypto import IdentityManager
from neon_link.db import get_connection
from neon_link.models.network import NetworkEvent
from neon_link.plugins.base import NetworkPlugin

logger = logging.getLogger(__name__)


class CryptoPipeline:
	def __init__(self, identity_manager: IdentityManager, agent_id: str):
		self.identity_manager = identity_manager
		self.agent_id = agent_id
		# For simplicity, we just use the first identity loaded.
		identities = self.identity_manager.get_identities()
		if not identities:
			raise ValueError("No identities loaded in IdentityManager")
		self.kem_key, self.sig_key = list(identities.values())[0]

	def _get_group_state(self, group_id: str) -> MLSGroup | None:
		conn = get_connection()
		try:
			conn.row_factory = sqlite3.Row
			cursor = conn.cursor()
			cursor.execute("SELECT state_payload FROM mls_states WHERE group_id = ?", (group_id,))
			row = cursor.fetchone()
			if row:
				return MLSGroup.from_bytes(row["state_payload"])
			return None
		finally:
			conn.close()

	def _save_group_state(self, group_id: str, group: MLSGroup):
		conn = get_connection()
		try:
			conn.execute(
				"INSERT OR REPLACE INTO mls_states (group_id, state_payload, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
				(group_id, group.to_bytes()),
			)
			conn.commit()
		finally:
			conn.close()

	async def process_egress(self, plugin: NetworkPlugin, channel_user_id: str, payload_str: str) -> bool:
		"""
		Takes plaintext, encrypts if necessary, and sends via plugin.
		"""
		# We assume firebase requires E2E.
		if plugin.name != "firebase":
			# Just pass plaintext
			event = NetworkEvent(type="application", recipient_id=channel_user_id, payload=payload_str.encode())
			return await plugin.send_event(event)

		group_id = channel_user_id
		group = self._get_group_state(group_id)

		if not group:
			logger.info(f"[Pipeline] Auto-creating group {group_id} for encryption...")
			group = MLSGroup.create(group_id.encode(), self.sig_key, self.kem_key)
			remote_kp_bytes = await plugin.fetch_key_package(group_id)
			if remote_kp_bytes:
				remote_kp = KeyPackage.from_bytes(remote_kp_bytes)
				group, welcome, _ = group.add_member(remote_kp)
				# Save state
				self._save_group_state(group_id, group)

				# Send welcome
				welcome_event = NetworkEvent(type="welcome", recipient_id=group_id, payload=MLSMessage.wrap_welcome(welcome).to_bytes())
				await plugin.send_event(welcome_event)
			else:
				logger.warning(f"[Pipeline] Could not fetch KeyPackage for {group_id}. Encrypting locally only.")
				self._save_group_state(group_id, group)

		# Encrypt application message
		try:
			# Advance epoch for Forward Secrecy before sending app message
			group, update = group.update_key()
			self._save_group_state(group_id, group)

			update_event = NetworkEvent(type="update", recipient_id=group_id, payload=MLSMessage.wrap_commit(update).to_bytes())
			await plugin.send_event(update_event)

			ciphertext = group.encrypt_application_message(payload_str.encode())
			event = NetworkEvent(type="application", recipient_id=group_id, payload=ciphertext)
			self._save_group_state(group_id, group)
			return await plugin.send_event(event)
		except Exception as e:
			logger.error(f"[Pipeline] Encryption/Commit failed: {e}")
			return False

	async def process_ingress(self, plugin: NetworkPlugin, sender_id: str, event: NetworkEvent):
		"""
		Receives an event from the plugin, decrypts if it's E2E, and enqueues to inbox.
		"""
		group_id = event.recipient_id  # Either group_id or user_id depending on context

		if plugin.name != "firebase":
			# Plaintext
			self._enqueue_inbox(plugin.name, sender_id, event.payload.decode("utf-8"))
			return

		# Firebase E2E handling
		if event.type == "welcome":
			try:
				welcome = MLSMessage.from_bytes(event.payload).unwrap_welcome()
				group = MLSGroup.join(welcome, self.sig_key, self.kem_key)
				self._save_group_state(group_id, group)
				logger.info(f"[Pipeline] Joined MLS group {group_id} via Welcome.")
			except Exception as e:
				logger.error(f"[Pipeline] Failed to process Welcome: {e}")

		elif event.type == "update":
			existing_group = self._get_group_state(group_id)
			if existing_group:
				try:
					update = MLSMessage.from_bytes(event.payload).unwrap_commit()
					updated_group = existing_group.process_update(update)
					self._save_group_state(group_id, updated_group)
					logger.info(f"[Pipeline] Processed Update for group {group_id}.")
				except Exception as e:
					logger.error(f"[Pipeline] Failed to process Update: {e}")

		elif event.type == "application":
			existing_group = self._get_group_state(group_id)
			if existing_group:
				try:
					plaintext_bytes = existing_group.decrypt_application_message(event.payload)
					self._save_group_state(group_id, existing_group)
					self._enqueue_inbox(plugin.name, sender_id, plaintext_bytes.decode("utf-8"))
				except Exception as e:
					logger.error(f"[Pipeline] Decryption failed: {e}")
			else:
				logger.warning(f"[Pipeline] Received ciphertext for unknown group {group_id}")

	def _get_or_create_session(self, channel: str, channel_user_id: str) -> str:
		import uuid
		conn = get_connection()
		try:
			conn.row_factory = sqlite3.Row
			cursor = conn.cursor()
			cursor.execute("SELECT session_id FROM sessions_mapping WHERE channel = ? AND channel_user_id = ?", (channel, channel_user_id))
			row = cursor.fetchone()
			if row:
				return row["session_id"]
			
			session_id = str(uuid.uuid4())
			cursor.execute("INSERT INTO sessions_mapping (session_id, channel, channel_user_id) VALUES (?, ?, ?)", (session_id, channel, channel_user_id))
			conn.commit()
			return session_id
		finally:
			conn.close()

	def _enqueue_inbox(self, channel: str, sender_id: str, plaintext: str):
		# Extract Routing Policy from decrypted JSON
		try:
			decoded = json.loads(plaintext)
			text = decoded.get("text", plaintext)
			group_size = decoded.get("group_size", 100)  # Assumes massive if missing
			priority = decoded.get("priority", "normal")
			mode = decoded.get("mode", "background")
		except Exception:
			text = plaintext
			group_size = 100
			priority = "normal"
			mode = "background"

		if group_size <= 2 and priority == "critical":
			mode = "conversational"

		# Abstraction: Create a UUID session for this channel + sender_id (chat_id)
		session_id = self._get_or_create_session(channel, sender_id)

		payload = json.dumps({"text": text, "sender_id": sender_id, "mode": mode})
		message_id = hashlib.sha256(payload.encode("utf-8")).hexdigest()

		conn = get_connection()
		try:
			cursor = conn.execute(
				"INSERT OR IGNORE INTO inbox (message_id, channel, channel_user_id, payload) VALUES (?, ?, ?, ?)",
				(message_id, channel, session_id, payload),
			)
			if cursor.rowcount > 0:
				conn.commit()
				logger.info(f"[Pipeline] Enqueued {mode} message from {sender_id} via {channel}.")
			else:
				logger.info(f"[Pipeline] Dropped duplicate message from {sender_id} via {channel}.")
		finally:
			conn.close()

	def get_public_key_package(self) -> bytes:
		"""Helper to expose the Agent's KeyPackage so the Plugin can upload it if it wants"""
		kp = KeyPackage.create(
			encryption_key=self.kem_key.public_bytes(),
			init_key_pub=self.kem_key.public_bytes(),
			signature_key=self.sig_key.public_bytes(),
			identity=self.agent_id.encode(),
			sign_fn=self.sig_key.sign,
		)
		return kp.to_bytes()
