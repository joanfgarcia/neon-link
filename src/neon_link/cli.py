import asyncio
import logging
import os
import sys
import time
from pathlib import Path

import platformdirs
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("neon_link.daemon")

APP_NAME = "neon-link"


def get_config_dir() -> Path:
	return Path(platformdirs.user_config_dir(APP_NAME))


def get_data_dir() -> Path:
	return Path(platformdirs.user_data_dir(APP_NAME))


def init_config():
	config_dir = get_config_dir()
	config_dir.mkdir(parents=True, exist_ok=True)

	data_dir = get_data_dir()
	data_dir.mkdir(parents=True, exist_ok=True)

	env_file = config_dir / ".env"
	db_file = data_dir / "events.db"

	if not env_file.exists():
		content = f"""# Ecosistema Red-Pill / Neon-Link Global Config
NEON_LINK_AGENT_ID="aleth"
NEON_LINK_DB_PATH="{db_file}"
WEBHOOK_URL="http://localhost:8771/webhook"
ENABLE_TELEGRAM=true
ENABLE_FIREBASE=false
TELEGRAM_BOT_TOKEN=""
TELEGRAM_WHITELIST_ID=""
FIREBASE_DB_URL=""
FIREBASE_CREDENTIALS=""
"""
		env_file.write_text(content)
		logger.info(f"[+] Archivo de configuración generado en: {env_file}")
	else:
		logger.info(f"[*] El archivo ya existe: {env_file}")

	logger.info(f"[+] Rutas inicializadas para DB: {db_file}")
	logger.info("Edita el archivo .env con tus tokens antes de iniciar el daemon.")

	try:
		from neon_link.db import init_db, set_db_path

		set_db_path(db_file)
		init_db()
	except Exception as e:
		logger.error(f"Failed to initialize database schema: {e}")


def start_daemon():
	logger.info("Starting Neon-Link Unified Daemon...")
	config_dir = get_config_dir()
	env_file = config_dir / ".env"

	if env_file.exists():
		load_dotenv(env_file)
	load_dotenv()  # Fallback to local .env if present

	agent_id = os.environ.get("NEON_LINK_AGENT_ID")
	if not agent_id:
		raise ValueError(f"NEON_LINK_AGENT_ID no configurado. Ejecuta `neon-link init` o edita {env_file}")

	enable_telegram = os.environ.get("ENABLE_TELEGRAM", "false").lower() == "true"
	enable_firebase = os.environ.get("ENABLE_FIREBASE", "false").lower() == "true"

	if not enable_telegram and not enable_firebase:
		logger.error("No active channels configured in .env. Exiting.")
		sys.exit(1)

	from neon_link.core.crypto import IdentityManager
	from neon_link.core.manager import PluginManager
	from neon_link.core.webhook import WebhookNotifier

	id_mgr = IdentityManager()
	wh_url = os.environ.get("WEBHOOK_URL", "http://localhost:8771/webhook")
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


def main():
	if len(sys.argv) > 1:
		cmd = sys.argv[1]
		if cmd == "init":
			init_config()
		elif cmd == "start":
			start_daemon()
		elif cmd in ("-h", "--help", "help"):
			print("Neon-Link Agnostic Communication Hub")
			print("Usage:")
			print("  neon-link init    - Initializes ~/.config/neon-link/.env and events.db")
			print("  neon-link start   - Starts the daemon")
			print("  neon-link --help  - Shows this message")
		else:
			print(f"Unknown command: {cmd}")
			print("Run 'neon-link --help' for usage.")
			sys.exit(1)
	else:
		start_daemon()


if __name__ == "__main__":
	main()
