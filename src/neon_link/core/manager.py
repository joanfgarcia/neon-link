import asyncio
import json
import logging
import os
import sqlite3
import threading
import time

from neon_link.core.crypto import IdentityManager
from neon_link.core.middleware import CryptoPipeline
from neon_link.core.webhook import WebhookNotifier
from neon_link.db import get_connection
from neon_link.plugins.base import NetworkPlugin, PermanentEgressError

logger = logging.getLogger(__name__)

# Egress retry policy — por TIEMPO, no por número de intentos: un envío fallido se
# reintenta con backoff exponencial (BASE, x2, tope MAX) mientras el mensaje tenga
# menos de MAX_AGE. Un corte de red corto (vuelta de suspensión, wifi) no pierde
# el mensaje, y uno roto no se martillea cada segundo.
EGRESS_BACKOFF_BASE_S = float(os.getenv("NEON_EGRESS_BACKOFF_BASE_S", "5"))
EGRESS_BACKOFF_MAX_S = float(os.getenv("NEON_EGRESS_BACKOFF_MAX_S", "300"))
EGRESS_MAX_AGE_S = float(os.getenv("NEON_EGRESS_MAX_AGE_H", "24")) * 3600


class PluginManager:
	def __init__(self, webhook_notifier: WebhookNotifier, identity_manager: IdentityManager, agent_id: str):
		self.plugins: dict[str, NetworkPlugin] = {}
		self.webhook_notifier = webhook_notifier
		self.identity_manager = identity_manager
		self.pipeline = CryptoPipeline(identity_manager, agent_id)
		self.running = False

	def register(self, plugin: NetworkPlugin):
		"""Registra un plugin y le inyecta el callback de llegada de eventos."""
		logger.info(f"Registrando plugin: {plugin.name}")
		# El callback del plugin apunta directamente al Ingress del Pipeline
		plugin.register_callback(self.pipeline.process_ingress)
		self.plugins[plugin.name] = plugin

		# Publish keys if plugin is firebase or rings
		if plugin.name in ["firebase", "rings"] and hasattr(plugin, "publish_my_key_package"):
			plugin.publish_my_key_package(self.pipeline.get_public_key_package())

	async def start_all(self):
		self.running = True
		for name, plugin in self.plugins.items():
			logger.info(f"Iniciando {name}...")
			await plugin.start()

		self.t_egress = threading.Thread(target=self._poll_outbox_loop)
		self.t_egress.daemon = True
		self.t_egress.start()

	async def stop_all(self):
		self.running = False
		for name, plugin in self.plugins.items():
			logger.info(f"Deteniendo {name}...")
			await plugin.stop()

		if hasattr(self, "t_egress"):
			self.t_egress.join(timeout=2.0)

	def _resolve_session(self, session_id: str) -> str:
		"""Translates a UUID session_id back to the physical channel_user_id. Fallbacks to itself if not found (legacy)."""
		conn = get_connection()
		try:
			conn.row_factory = sqlite3.Row
			cursor = conn.cursor()
			cursor.execute("SELECT channel_user_id FROM sessions_mapping WHERE session_id = ?", (session_id,))
			row = cursor.fetchone()
			if row:
				return row["channel_user_id"]
			return session_id
		finally:
			conn.close()

	def _poll_outbox_loop(self):
		"""Poll SQLite outbox and route through Egress Pipeline"""
		logger.info("[Manager] Started Outbox Polling for Egress...")
		loop = asyncio.new_event_loop()
		asyncio.set_event_loop(loop)

		while self.running:
			conn = None
			try:
				conn = get_connection()
				conn.row_factory = sqlite3.Row
				cursor = conn.cursor()
				cursor.execute(
					"SELECT *, (julianday('now') - julianday(created_at)) * 86400.0 AS age_s FROM outbox "
					"WHERE status = 'PENDING' AND (next_attempt_at IS NULL OR next_attempt_at <= ?) ORDER BY created_at ASC",
					(time.time(),),
				)
				rows = cursor.fetchall()

				for row in rows:
					self._process_outbox_row_contained(loop, cursor, row)
					# Commit per message: the write lock is never held across network
					# sends, and a crash mid-batch never re-sends what was delivered.
					conn.commit()
			except Exception as e:
				logger.error(f"[Manager] Outbox polling error: {e}")
			finally:
				if conn is not None:
					conn.close()

			time.sleep(1.0)

	def _process_outbox_row_contained(self, loop, cursor, row) -> None:
		"""Per-message containment: one bad message must NEVER abort the batch
		(it used to: an exception escaped to the outer handler and blocked every
		subsequent message forever)."""
		try:
			self._process_outbox_row(loop, cursor, row)
		except PermanentEgressError as e:
			logger.error(f"[Manager] Undeliverable outbox msg {row['id']}: {e}")
			self._fail_outbox_msg(cursor, row, row["channel"], f"undeliverable: {e}")
		except Exception as e:
			logger.exception(f"[Manager] Egress error for msg {row['id']} ({e}); will retry")
			self._schedule_retry(cursor, row, f"processing error: {e}")

	def _process_outbox_row(self, loop, cursor, row) -> None:
		"""Process a single outbox row. Raises PermanentEgressError for messages
		that can never be delivered; any other failure is retried with backoff."""
		channel = row["channel"]
		if channel not in self.plugins:
			# Not registered in THIS process (plugin disabled/failed to start):
			# retried with backoff, so a restart with the plugin back delivers it.
			self._schedule_retry(cursor, row, f"unknown channel: {channel}")
			return

		plugin = self.plugins[channel]
		try:
			payload_json = json.loads(row["payload"])
		except (TypeError, ValueError) as e:
			raise PermanentEgressError(f"corrupt payload: {e}") from e
		if not isinstance(payload_json, dict):
			raise PermanentEgressError(f"payload is not an object: {type(payload_json).__name__}")
		text = payload_json.get("text", "No text provided")
		session_id = row["channel_user_id"]

		# Translate UUID session back to the real channel_user_id; ids without a
		# mapping fall back to themselves (legacy rows already carry the chat id).
		# A recipient the network rejects surfaces as a send failure.
		recipient_id = self._resolve_session(session_id)

		# Pass through CryptoPipeline
		success = loop.run_until_complete(self.pipeline.process_egress(plugin, recipient_id, text))

		if success:
			cursor.execute("UPDATE outbox SET status = 'SENT' WHERE id = ?", (row["id"],))
			logger.info(f"[Manager] Processed Egress for msg {row['id']} via {channel}")
			return
		self._schedule_retry(cursor, row, "send failed")

	def _schedule_retry(self, cursor, row, reason: str) -> None:
		"""Backoff the row, or dead-letter it once it is older than EGRESS_MAX_AGE_S."""
		retries = (row["retries"] or 0) + 1
		age_s = _row_age_s(row)
		if age_s >= EGRESS_MAX_AGE_S:
			self._fail_outbox_msg(cursor, row, row["channel"], f"{reason}; gave up after {retries} attempts ({age_s / 3600:.1f}h old)")
			logger.error(f"[Manager] Egress gave up on msg {row['id']} after {retries} attempts. Moved to dead_letters.")
			return
		delay = min(EGRESS_BACKOFF_BASE_S * 2 ** min(retries - 1, 16), EGRESS_BACKOFF_MAX_S)
		cursor.execute("UPDATE outbox SET retries = ?, next_attempt_at = ? WHERE id = ?", (retries, time.time() + delay, row["id"]))
		logger.warning(f"[Manager] Egress failed for msg {row['id']} ({reason}); retry {retries} in {delay:.0f}s")

	def _fail_outbox_msg(self, cursor, row, channel, reason: str) -> None:
		"""Mark an outbox row FAILED and record it in dead_letters (undeliverable or
		aged out). `neon-link redrive` puts it back in the queue."""
		cursor.execute("UPDATE outbox SET status = 'FAILED' WHERE id = ?", (row["id"],))
		cursor.execute(
			"INSERT INTO dead_letters (original_table, original_id, channel, channel_user_id, payload, error_reason) VALUES (?, ?, ?, ?, ?, ?)",
			("outbox", row["id"], channel, row["channel_user_id"], row["payload"], reason),
		)

	def get_plugin(self, name: str) -> NetworkPlugin:
		return self.plugins[name]


def _row_age_s(row) -> float:
	"""Age of an outbox row in seconds (`age_s` computed by the poll query)."""
	try:
		age = row["age_s"]
	except (IndexError, KeyError):
		return 0.0
	return float(age) if age is not None else 0.0


def redrive_outbox_dead_letters(conn, ids: list[int] | None = None) -> int:
	"""Requeue dead-lettered OUTBOX messages (all, or the given dead_letter ids).

	The outbox row goes back to PENDING with a fresh clock (retries, backoff and
	created_at reset, so the age cap starts over) and its dead_letter entry is
	removed — the message itself lives on in the outbox. Returns rows requeued.
	"""
	query = "SELECT id, original_id FROM dead_letters WHERE original_table = 'outbox'"
	params: list = []
	if ids:
		query += f" AND id IN ({','.join('?' * len(ids))})"
		params = list(ids)
	letters = conn.execute(query, params).fetchall()
	requeued = 0
	for letter_id, outbox_id in letters:
		cur = conn.execute(
			"UPDATE outbox SET status = 'PENDING', retries = 0, next_attempt_at = NULL, created_at = CURRENT_TIMESTAMP "
			"WHERE id = ? AND status = 'FAILED'",
			(outbox_id,),
		)
		if cur.rowcount:
			conn.execute("DELETE FROM dead_letters WHERE id = ?", (letter_id,))
			requeued += 1
	conn.commit()
	return requeued
