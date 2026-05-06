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
		text = message.get("text", "")

		if self.allowed_user_id and chat_id != self.allowed_user_id:
			logger.warning(f"Unauthorized access attempt from {chat_id}")
			return

		if text.startswith("/start"):
			self.send_message(chat_id, "⚡ Bünker Neon-Link conectado. Gateway I/O Activo. Esperando inputs.")
			return

		if text.startswith("/list"):
			payload = json.dumps({"command": "LIST_CASCADES", "mode": "conversational"})
			self.send_message(chat_id, "🔍 Buscando sesiones activas en el Córtex...")
		elif text.startswith("/switch "):
			parts = text.split(" ")
			if len(parts) == 2 and parts[1].isdigit():
				payload = json.dumps({"command": "SWITCH_CASCADE", "index": int(parts[1]), "mode": "conversational"})
			else:
				self.send_message(chat_id, "❌ Uso: /switch <número>")
				return
		else:
			# Routing Policy Engine
			bot_username = os.environ.get("TELEGRAM_BOT_USERNAME", "")
			mode = "conversational" if chat_type == "private" else "background"

			if text.startswith("/bg "):
				mode = "background"
				text = text[4:].strip()
			elif chat_type in ["group", "supergroup"] and bot_username and f"@{bot_username}" in text:
				mode = "conversational"

			payload = json.dumps({"text": text, "mode": mode})

		# Check health
		if not self.check_red_pill_health():
			self.send_message(chat_id, "⚠️ Córtex Offline. El IDE o Red-Pill no responde. El mensaje será encolado.")

		logger.info(f"Received from Telegram: {text}")

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
		self.t_ingress = threading.Thread(target=self.poll_telegram)
		self.t_ingress.daemon = True
		self.t_ingress.start()

	async def stop(self):
		self.running = False
		if hasattr(self, "t_ingress"):
			self.t_ingress.join(timeout=2.0)
