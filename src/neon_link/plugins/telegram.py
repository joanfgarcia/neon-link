import asyncio
import json
import logging
import os
import threading
import time

import requests  # type: ignore[import-untyped]
from dotenv import load_dotenv

from neon_link.core.crypto import IdentityManager
from neon_link.models.network import NetworkEvent
from neon_link.plugins.base import NetworkPlugin

load_dotenv()
from neon_link.db import get_connection  # noqa: E402

logger = logging.getLogger(__name__)


class TelegramHub(NetworkPlugin):
	def __init__(self, identity_manager: IdentityManager, bot_token: str | None = None, allowed_user_id: str | None = None):
		super().__init__("telegram", identity_manager)
		self.bot_token = bot_token or os.environ.get("TELEGRAM_BOT_TOKEN")
		self.allowed_user_id = allowed_user_id or os.environ.get("TELEGRAM_WHITELIST_ID")
		self.offset = 0
		self.running = False

		if not self.allowed_user_id or not self.bot_token:
			logger.warning("TELEGRAM_WHITELIST_ID or TELEGRAM_BOT_TOKEN missing. Telegram Hub might fail if enabled.")

	def check_red_pill_health(self) -> bool:
		conn = get_connection()
		cursor = conn.cursor()
		cursor.execute(
			"SELECT (julianday('now') - julianday(last_heartbeat)) * 86400 AS seconds_ago FROM system_health WHERE service_name = 'red_pill'"
		)
		row = cursor.fetchone()
		conn.close()

		return not (row and row[0] is not None and row[0] > 60)

	def send_message(self, chat_id, text):
		url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
		try:
			requests.post(url, json={"chat_id": chat_id, "text": text})
		except Exception as e:
			logger.error(f"Failed to send message to Telegram: {e}")

	async def send_event(self, event: NetworkEvent) -> bool:
		text = event.payload.decode("utf-8")
		url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
		try:
			resp = requests.post(url, json={"chat_id": event.recipient_id, "text": text})
			if resp.status_code == 200:
				return True
			logger.error(f"Telegram API error: {resp.text}")
			return False
		except Exception as e:
			logger.error(f"Failed to send message to Telegram: {e}")
			return False

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

		if raw_text.startswith("/list"):
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

			payload = json.dumps({"text": formatted_text, "mode": mode})

		# Check health
		if not self.check_red_pill_health():
			self.send_message(chat_id, "⚠️ Córtex Offline. El IDE o Red-Pill no responde. El mensaje será encolado.")

		logger.info(f"Received from Telegram: {raw_text}")

		# Pass to Pipeline via callback
		if self._on_event_callback:
			event = NetworkEvent(type="application", recipient_id=chat_id, payload=payload.encode("utf-8"))
			try:
				asyncio.run(self._on_event_callback(self, chat_id, event))  # type: ignore
			except Exception as e:
				logger.error(f"Failed to enqueue via callback: {e}")

	def poll_telegram(self):
		url = f"https://api.telegram.org/bot{self.bot_token}/getUpdates"
		logger.info("Started Telegram Ingress Polling...")
		while self.running:
			if not self.bot_token:
				logger.error("TELEGRAM_BOT_TOKEN not set. Exiting Ingress loop.")
				break

			try:
				resp = requests.get(url, params={"timeout": 10, "offset": self.offset}, timeout=15)
				if resp.status_code == 200:
					data = resp.json()
					for update in data.get("result", []):
						self.offset = update["update_id"] + 1
						if "message" in update:
							self.handle_message(update["message"])
			except Exception as e:
				logger.error(f"Telegram polling error: {e}")
				time.sleep(5)

	async def start(self):
		self.running = True
		if not os.environ.get("TELEGRAM_BOT_USERNAME") and self.bot_token:
			try:
				resp = requests.get(f"https://api.telegram.org/bot{self.bot_token}/getMe", timeout=10)
				if resp.status_code == 200:
					os.environ["TELEGRAM_BOT_USERNAME"] = resp.json()["result"]["username"]
			except Exception as e:
				logger.error(f"Failed to fetch bot username: {e}")

		self.t_ingress = threading.Thread(target=self.poll_telegram)
		self.t_ingress.daemon = True
		self.t_ingress.start()

	async def stop(self):
		self.running = False
		if hasattr(self, "t_ingress"):
			self.t_ingress.join(timeout=2.0)
