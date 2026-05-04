import os
import sys
import time
import logging
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("neon_link.daemon")

def main():
    """Unified Daemon Entry Point for Neon-Link."""
    logger.info("Starting Neon-Link Unified Daemon...")
    load_dotenv()
    
    enable_telegram = os.environ.get("ENABLE_TELEGRAM", "false").lower() == "true"
    enable_firebase = os.environ.get("ENABLE_FIREBASE", "false").lower() == "true"
    
    if not enable_telegram and not enable_firebase:
        logger.error("No active channels configured in .env (ENABLE_TELEGRAM, ENABLE_FIREBASE). Exiting.")
        sys.exit(1)
        
    hubs = []
    
    if enable_telegram:
        logger.info("Initializing Telegram Hub...")
        try:
            from neon_link.plugins.telegram import TelegramHub
            t_hub = TelegramHub()
            t_hub.start_threads()
            hubs.append(t_hub)
        except Exception as e:
            logger.error(f"Failed to start Telegram Hub: {e}")
            
    if enable_firebase:
        logger.info("Initializing Firebase Hub...")
        try:
            from neon_link.plugins.firebase import FirebaseHub
            f_hub = FirebaseHub()
            f_hub.start_threads()
            hubs.append(f_hub)
        except Exception as e:
            logger.error(f"Failed to start Firebase Hub: {e}")
            
    if not hubs:
        logger.error("All enabled hubs failed to start. Exiting.")
        sys.exit(1)
        
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down Neon-Link Daemon...")
        for hub in hubs:
            hub.stop_threads()

if __name__ == "__main__":
    main()
