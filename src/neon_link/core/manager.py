import logging
import sqlite3
import json
import asyncio
import time
import threading

from neon_link.core.crypto import IdentityManager
from neon_link.core.middleware import CryptoPipeline
from neon_link.core.webhook import WebhookNotifier
from neon_link.db import get_connection
from neon_link.plugins.base import NetworkPlugin

logger = logging.getLogger(__name__)

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
		
		# Publish keys if plugin is firebase
		if plugin.name == "firebase" and hasattr(plugin, "publish_my_key_package"):
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
			
		if hasattr(self, 't_egress'):
			self.t_egress.join(timeout=2.0)

	def _poll_outbox_loop(self):
		"""Poll SQLite outbox and route through Egress Pipeline"""
		logger.info("[Manager] Started Outbox Polling for Egress...")
		loop = asyncio.new_event_loop()
		asyncio.set_event_loop(loop)
		
		while self.running:
			try:
				conn = get_connection()
				conn.row_factory = sqlite3.Row
				cursor = conn.cursor()
				cursor.execute("SELECT * FROM outbox WHERE status = 'PENDING' ORDER BY created_at ASC")
				rows = cursor.fetchall()
				
				for row in rows:
					channel = row['channel']
					if channel in self.plugins:
						plugin = self.plugins[channel]
						payload_json = json.loads(row['payload'])
						text = payload_json.get("text", "No text provided")
						recipient_id = row['channel_user_id']
						
						# Pass through CryptoPipeline
						success = loop.run_until_complete(
							self.pipeline.process_egress(plugin, recipient_id, text)
						)
						
						if success:
							cursor.execute("UPDATE outbox SET status = 'SENT' WHERE id = ?", (row['id'],))
							logger.info(f"[Manager] Processed Egress for msg {row['id']} via {channel}")
					else:
						logger.warning(f"[Manager] Unknown channel {channel} for outbox msg {row['id']}")
						
				conn.commit()
				conn.close()
			except Exception as e:
				logger.error(f"[Manager] Outbox polling error: {e}")
				
			time.sleep(1.0)
			
	def get_plugin(self, name: str) -> NetworkPlugin:
		return self.plugins[name]
