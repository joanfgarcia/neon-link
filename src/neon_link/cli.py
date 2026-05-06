import os
import sys
import time
import logging
import asyncio
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("neon_link.daemon")

def main():
	"""Unified Daemon Entry Point for Neon-Link."""
	logger.info("Starting Neon-Link Unified Daemon...")
	load_dotenv()
	
	agent_id = os.environ.get("NEON_LINK_AGENT_ID", "red_pill_core")
	enable_telegram = os.environ.get("ENABLE_TELEGRAM", "false").lower() == "true"
	enable_firebase = os.environ.get("ENABLE_FIREBASE", "false").lower() == "true"
	
	if not enable_telegram and not enable_firebase:
		logger.error("No active channels configured in .env (ENABLE_TELEGRAM, ENABLE_FIREBASE). Exiting.")
		sys.exit(1)
		
	from neon_link.core.crypto import IdentityManager
	from neon_link.core.webhook import WebhookNotifier
	from neon_link.core.manager import PluginManager
	
	id_mgr = IdentityManager()
	wh_url = os.environ.get("WEBHOOK_URL", "http://localhost:8000/webhook")
	wh_notifier = WebhookNotifier(wh_url)
	manager = PluginManager(wh_notifier, id_mgr, agent_id)
	
	if enable_telegram:
		logger.info("Initializing Telegram Hub...")
		try:
			from neon_link.plugins.telegram import TelegramHub
			t_hub = TelegramHub(id_mgr)
			manager.register(t_hub)
		except Exception as e:
			logger.error(f"Failed to start Telegram Hub: {e}")
			
	if enable_firebase:
		logger.info("Initializing Firebase Hub...")
		try:
			from neon_link.plugins.firebase import FirebaseHub
			f_hub = FirebaseHub(id_mgr)
			manager.register(f_hub)
		except Exception as e:
			logger.error(f"Failed to start Firebase Hub: {e}")
			
	if not manager.plugins:
		logger.error("All enabled hubs failed to start. Exiting.")
		sys.exit(1)
		
	loop = asyncio.get_event_loop()
	loop.run_until_complete(manager.start_all())
	
	try:
		while True:
			time.sleep(1)
	except KeyboardInterrupt:
		logger.info("Shutting down Neon-Link Daemon...")
		loop.run_until_complete(manager.stop_all())

if __name__ == "__main__":
	main()
