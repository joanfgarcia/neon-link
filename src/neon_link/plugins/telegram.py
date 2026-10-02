import asyncio
import hashlib
import json
import logging
import os
import threading
import time
from collections import OrderedDict

import requests  # type: ignore[import-untyped]
from dotenv import load_dotenv

from neon_link.core.crypto import IdentityManager
from neon_link.models.network import NetworkEvent
from neon_link.plugins.base import NetworkPlugin, PermanentEgressError

load_dotenv()
from neon_link.db import get_connection  # noqa: E402

logger = logging.getLogger(__name__)

# (connect, read) seconds for sendMessage: an unbounded POST could hang the egress
# thread forever — the exact stall the outbox containment exists to prevent.
SEND_TIMEOUT = (5, 30)
# Bot API rejections that no retry can fix (bad request / chat not found, bot blocked).
_PERMANENT_STATUS = (400, 403)
# Messages whose chunks were partially delivered; bounded so a dead one cannot leak.
_MAX_TRACKED_PROGRESS = 256
# Ingress: an update that cannot be enqueued (DB locked…) is NOT acknowledged —
# the offset stays put and Telegram redelivers it — up to this many attempts.
_MAX_INGRESS_ATTEMPTS = 5
# getUpdates backoff on HTTP errors / exceptions (seconds, doubling).
_POLL_BACKOFF_MAX = 60.0


class TelegramHub(NetworkPlugin):
	def __init__(self, identity_manager: IdentityManager, bot_token: str | None = None, allowed_user_id: str | None = None):
		super().__init__("telegram", identity_manager)
		self.bot_token = bot_token or os.environ.get("TELEGRAM_BOT_TOKEN")
		self.allowed_user_id = allowed_user_id or os.environ.get("TELEGRAM_WHITELIST_ID")
		self.offset = 0
		self.running = False
		# chunks already delivered per (recipient, text): a retry resumes after
		# them instead of re-sending the whole series (in-memory; a restart may
		# repeat the delivered part once).
		self._chunk_progress: OrderedDict[str, int] = OrderedDict()

		if not self.allowed_user_id or not self.bot_token:
			logger.warning("TELEGRAM_WHITELIST_ID or TELEGRAM_BOT_TOKEN missing. Telegram Hub might fail if enabled.")

	def check_red_pill_health(self) -> bool:
		"""Worker heartbeat fresh (< 60 s). Only drives the "offline" notice, so a DB
		error reads as healthy instead of aborting the ingest of the message."""
		try:
			conn = get_connection()
			try:
				row = conn.execute(
					"SELECT (julianday('now') - julianday(last_heartbeat)) * 86400 AS seconds_ago FROM system_health WHERE service_name = 'red_pill'"
				).fetchone()
			finally:
				conn.close()
		except Exception as e:
			logger.warning(f"Health check unavailable: {e}")
			return True
		return not (row and row[0] is not None and row[0] > 60)

	def _split_message(self, text: str, max_chars: int = 4000) -> list[str]:
		if len(text) <= max_chars:
			return [text]

		safe_chunk_size = 3900
		raw_chunks = [text[i : i + safe_chunk_size] for i in range(0, len(text), safe_chunk_size)]
		num_chunks = len(raw_chunks)

		formatted_chunks = []
		for idx, chunk in enumerate(raw_chunks):
			parts = []
			if idx > 0:
				parts.append("...")

			parts.append(chunk)

			if idx < num_chunks - 1:
				parts.append("...")

			parts.append(f"\n{idx + 1}/{num_chunks}")
			formatted_chunks.append("".join(parts))

		return formatted_chunks

	def send_message(self, chat_id, text):
		if not text:
			return
		chunks = self._split_message(text)
		for chunk in chunks:
			url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
			try:
				requests.post(url, json={"chat_id": chat_id, "text": chunk}, timeout=SEND_TIMEOUT)
			except Exception as e:
				logger.error(f"Failed to send message to Telegram: {e}")

	async def send_event(self, event: NetworkEvent) -> bool:
		text = event.payload.decode("utf-8")
		if not text:
			return True
		chunks = self._split_message(text)
		key = hashlib.sha256(f"{event.recipient_id}\0{text}".encode()).hexdigest()
		sent = self._chunk_progress.get(key, 0)
		url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
		for idx in range(sent, len(chunks)):
			try:
				resp = requests.post(url, json={"chat_id": event.recipient_id, "text": chunks[idx]}, timeout=SEND_TIMEOUT)
			except Exception as e:
				logger.error(f"Failed to send message to Telegram: {e}")
				self._remember_progress(key, idx)
				return False
			if resp.status_code in _PERMANENT_STATUS:
				self._chunk_progress.pop(key, None)
				raise PermanentEgressError(f"Telegram API {resp.status_code}: {resp.text[:200]}")
			if resp.status_code != 200:
				logger.error(f"Telegram API error: {resp.text}")
				self._remember_progress(key, idx)
				return False
			await asyncio.sleep(0.2)
		self._chunk_progress.pop(key, None)
		return True

	def _remember_progress(self, key: str, delivered: int) -> None:
		if delivered <= 0:
			self._chunk_progress.pop(key, None)
			return
		self._chunk_progress[key] = delivered
		self._chunk_progress.move_to_end(key)
		while len(self._chunk_progress) > _MAX_TRACKED_PROGRESS:
			self._chunk_progress.popitem(last=False)

	async def fetch_key_package(self, agent_id: str) -> bytes | None:
		return None

	def handle_message(self, message):
		chat_id = str(message["chat"]["id"])
		chat_type = message["chat"].get("type", "private")
		raw_text = message.get("text", "")

		sender = message.get("from", {})
		sender_name = sender.get("username") or sender.get("first_name", "Unknown")
		is_bot = sender.get("is_bot", False)

		allowed_ids = [x.strip() for x in self.allowed_user_id.split(",")] if self.allowed_user_id else []
		if allowed_ids and chat_id not in allowed_ids:
			logger.warning(f"Unauthorized access attempt from {chat_id}")
			return

		if raw_text.startswith("/start"):
			self.send_message(chat_id, "⚡ Bünker Neon-Link conectado. Gateway I/O Activo. Esperando inputs.")
			return

		if raw_text.startswith("/help"):
			help_text = (
				"🛡️ **Sovereign Telegram Gateway**\n\n"
				"Comandos disponibles:\n"
				"• `/list` - Lista las sesiones de Córtex activas.\n"
				"• `/switch <número>` - Ancla el bot a la sesión deseada.\n"
				"• `/new` - Inicia una nueva sesión Headless limpia.\n"
				"• `/models` - Lista los modelos del catálogo curado.\n"
				"• `/model [id]` - Muestra/cambia el modelo respondedor de la sesión.\n"
				"• `/defaults` - Vuelve a la cascade configurada (.env).\n"
				"• `/mission <prompt>` - Fuerza el heavy path (cola).\n"
				"• `/queue` - Estado de la cola de jobs.\n"
				"• `/deferred` - Mensajes DEFERRED (quota agotada).\n"
				"• `/bg <mensaje>` - Envía el mensaje en background (modo Minion).\n"
				"• `/help` - Muestra esta ayuda."
			)
			self.send_message(chat_id, help_text)
			return

		if raw_text.startswith("/new"):
			import time

			payload = json.dumps({"command": "NEW_CASCADE", "mode": "conversational", "_t": time.time()})
			self.send_message(chat_id, "✨ Iniciando nueva sesión Headless...")

		elif raw_text.startswith("/list"):
			import time

			payload = json.dumps({"command": "LIST_CASCADES", "mode": "conversational", "_t": time.time()})
			self.send_message(chat_id, "🔍 Buscando sesiones activas en el Córtex...")
		elif raw_text.startswith("/switch "):
			parts = raw_text.split(" ")
			if len(parts) == 2 and parts[1].isdigit():
				import time

				payload = json.dumps({"command": "SWITCH_CASCADE", "index": int(parts[1]), "mode": "conversational", "_t": time.time()})
			else:
				self.send_message(chat_id, "❌ Uso: /switch <número>")
				return
		elif raw_text.startswith("/models"):
			import time

			backend = None
			if " --backend " in raw_text or raw_text.startswith("/models --backend"):
				parts = raw_text.split()
				for i, p in enumerate(parts):
					if p == "--backend" and i + 1 < len(parts):
						backend = parts[i + 1]
						break
			payload = json.dumps({"command": "LIST_MODELS", "backend": backend, "mode": "conversational", "_t": time.time()})
			self.send_message(chat_id, "🧠 Listando modelos del catálogo curado...")
		elif raw_text.startswith("/model"):
			import time

			rest = raw_text[len("/model") :].strip()
			if rest:
				payload = json.dumps({"command": "SET_MODEL", "model": rest, "mode": "conversational", "_t": time.time()})
				self.send_message(chat_id, f"🔧 Estableciendo modelo de sesión a `{rest}`...")
			else:
				payload = json.dumps({"command": "SHOW_MODEL", "mode": "conversational", "_t": time.time()})
				self.send_message(chat_id, "🔍 Consultando modelo actual de la sesión...")
		elif raw_text.startswith("/defaults"):
			import time

			payload = json.dumps({"command": "RESET_MODEL", "mode": "conversational", "_t": time.time()})
			self.send_message(chat_id, "↩️ Restableciendo modelo a la cascade configurada (.env)...")
		elif raw_text.startswith("/deferred"):
			import time

			payload = json.dumps({"command": "LIST_DEFERRED", "mode": "conversational", "_t": time.time()})
			self.send_message(chat_id, "📋 Consultando mensajes DEFERRED...")
		elif raw_text.startswith("/queue"):
			import time

			payload = json.dumps({"command": "SHOW_QUEUE", "mode": "conversational", "_t": time.time()})
			self.send_message(chat_id, "🗂️ Consultando la cola de jobs...")
		elif raw_text.startswith("/mission"):
			import time

			prompt = raw_text[len("/mission") :].strip()
			if not prompt:
				self.send_message(chat_id, "❌ Uso: /mission <prompt>")
				return
			payload = json.dumps({"command": "HEAVY_PATH", "text": prompt, "mode": "conversational", "_t": time.time()})
			self.send_message(chat_id, "🚀 Encolando como misión (heavy path)...")
		else:
			# Routing Policy Engine
			bot_username = os.environ.get("TELEGRAM_BOT_USERNAME", "")
			mode = "conversational" if chat_type == "private" else "background"

			if raw_text.startswith("/bg "):
				mode = "background"
				formatted_text = f"[{sender_name}] {raw_text[4:].strip()}"
			elif chat_type in ["group", "supergroup"] and bot_username:
				mode = "background"  # Default for groups

				if is_bot:
					# Bot-to-Bot Protocol (B2BP)
					# Requires strict syntax to trigger conversational mode and prevent infinite loops
					if f"] @{bot_username} [" in raw_text or f">>{bot_username}<<" in raw_text:
						mode = "conversational"
				else:
					# Human operator
					if f"@{bot_username}" in raw_text:
						mode = "conversational"

				formatted_text = f"[{sender_name}] {raw_text}"
			else:
				formatted_text = f"[{sender_name}] {raw_text}"

			import time

			payload = json.dumps({"text": formatted_text, "mode": mode, "_t": time.time()})

		# Check health. This watches the red-pill WORKER heartbeat (system_health
		# table), which processes the inbox under ANY execution backend — it is
		# intentionally backend-agnostic (no IDE required for opencode/claude).
		if not self.check_red_pill_health():
			self.send_message(chat_id, "⚠️ Córtex Offline. Red-Pill no responde. El mensaje será encolado.")

		logger.info(f"Received from Telegram: {raw_text}")

		# Pass to Pipeline via callback. A failure propagates: the poller does not
		# acknowledge the update, so Telegram redelivers it (no silent loss).
		if self._on_event_callback:
			event = NetworkEvent(type="application", recipient_id=chat_id, payload=payload.encode("utf-8"))
			asyncio.run(self._on_event_callback(self, chat_id, event))  # type: ignore

	def poll_telegram(self):
		url = f"https://api.telegram.org/bot{self.bot_token}/getUpdates"
		logger.info("Started Telegram Ingress Polling...")
		backoff = 1.0
		attempts: dict[int, int] = {}
		while self.running:
			if not self.bot_token:
				logger.error("TELEGRAM_BOT_TOKEN not set. Exiting Ingress loop.")
				break

			try:
				resp = requests.get(url, params={"timeout": 10, "offset": self.offset}, timeout=15)
			except Exception as e:
				logger.error(f"Telegram polling error: {e}")
				time.sleep(backoff)
				backoff = min(backoff * 2, _POLL_BACKOFF_MAX)
				continue

			if resp.status_code != 200:
				delay = backoff
				if resp.status_code == 409:
					logger.error("getUpdates 409 Conflict: another poller is using this bot token (a second neon-link running?)")
				elif resp.status_code == 429:
					delay = max(delay, float(_retry_after(resp)))
					logger.warning(f"getUpdates rate-limited; retrying in {delay:.0f}s")
				else:
					logger.error(f"getUpdates HTTP {resp.status_code}: {resp.text[:200]}")
				time.sleep(delay)
				backoff = min(backoff * 2, _POLL_BACKOFF_MAX)
				continue
			backoff = 1.0

			try:
				updates = resp.json().get("result", [])
			except Exception as e:
				logger.error(f"getUpdates returned an unreadable body: {e}")
				continue
			for update in updates:
				if not self._ingest_update(update, attempts):
					break

	def _ingest_update(self, update: dict, attempts: dict[int, int]) -> bool:
		"""Handle one update and acknowledge it (advance the offset). On failure the
		offset stays put so Telegram redelivers it; after _MAX_INGRESS_ATTEMPTS it is
		dropped with an error. Returns False to stop the current batch."""
		update_id = update["update_id"]
		try:
			if "message" in update:
				self.handle_message(update["message"])
		except Exception as e:
			n = attempts.get(update_id, 0) + 1
			if n < _MAX_INGRESS_ATTEMPTS:
				attempts[update_id] = n
				logger.error(f"Failed to ingest Telegram update {update_id} ({e}); retry {n}/{_MAX_INGRESS_ATTEMPTS - 1}")
				time.sleep(min(2**n, 30))
				return False
			logger.error(f"Dropping Telegram update {update_id} after {n} failed attempts: {e}")
		attempts.pop(update_id, None)
		self.offset = update_id + 1
		return True

	async def start(self):
		self.running = True
		if not os.environ.get("TELEGRAM_BOT_USERNAME") and self.bot_token:
			try:
				resp = requests.get(f"https://api.telegram.org/bot{self.bot_token}/getMe", timeout=10)
				if resp.status_code == 200:
					os.environ["TELEGRAM_BOT_USERNAME"] = resp.json()["result"]["username"]
			except Exception as e:
				logger.error(f"Failed to fetch bot username: {e}")

			try:
				commands_payload = {
					"commands": [
						{"command": "help", "description": "Muestra la ayuda de comandos"},
						{"command": "list", "description": "Lista las sesiones activas"},
						{"command": "switch", "description": "Ancla el bot a una sesión"},
						{"command": "new", "description": "Inicia una sesión Headless"},
						{"command": "models", "description": "Lista el catálogo de modelos"},
						{"command": "model", "description": "Muestra/cambia el modelo de sesión"},
						{"command": "defaults", "description": "Vuelve a la cascade de .env"},
						{"command": "mission", "description": "Fuerza el heavy path (cola)"},
						{"command": "queue", "description": "Estado de la cola de jobs"},
						{"command": "deferred", "description": "Mensajes DEFERRED"},
						{"command": "bg", "description": "Envía un mensaje en background"},
					]
				}
				resp = requests.post(f"https://api.telegram.org/bot{self.bot_token}/setMyCommands", json=commands_payload, timeout=10)
				if resp.status_code != 200:
					logger.warning(f"Failed to set bot commands: {resp.text}")
			except Exception as e:
				logger.error(f"Failed to set bot commands: {e}")

		self.t_ingress = threading.Thread(target=self.poll_telegram)
		self.t_ingress.daemon = True
		self.t_ingress.start()

	async def stop(self):
		self.running = False
		if hasattr(self, "t_ingress"):
			self.t_ingress.join(timeout=2.0)


def _retry_after(resp) -> float:
	"""Seconds Telegram asks to wait on a 429 (`parameters.retry_after`), default 5."""
	try:
		return float(resp.json().get("parameters", {}).get("retry_after", 5))
	except Exception:
		return 5.0
