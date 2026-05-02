import time
import requests
import json
import sqlite3
import threading
import logging
import os
from dotenv import load_dotenv

load_dotenv()
from db import get_connection

logger = logging.getLogger(__name__)

ALLOWED_USER_ID = os.environ.get("TELEGRAM_WHITELIST_ID", "REPLACE_ME")
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "REPLACE_ME")

class TelegramHub:
    def __init__(self):
        self.offset = 0
        self.running = True

    def check_red_pill_health(self) -> bool:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT (julianday('now') - julianday(last_heartbeat)) * 86400 AS seconds_ago FROM system_health WHERE service_name = 'red_pill'")
        row = cursor.fetchone()
        conn.close()
        
        if row and row[0] is not None:
            if row[0] > 60:
                return False
        return True

    def send_message(self, chat_id, text):
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        try:
            requests.post(url, json={"chat_id": chat_id, "text": text})
        except Exception as e:
            logger.error(f"Failed to send message to Telegram: {e}")

    def handle_message(self, message):
        chat_id = str(message['chat']['id'])
        text = message.get('text', '')

        if chat_id != ALLOWED_USER_ID and ALLOWED_USER_ID != "REPLACE_ME":
            logger.warning(f"Unauthorized access attempt from {chat_id}")
            return

        if text.startswith("/start"):
            self.send_message(chat_id, "⚡ Bünker Neon-Link conectado. Gateway I/O Activo. Esperando inputs.")
            return

        if text.startswith("/list"):
            payload = json.dumps({"command": "LIST_CASCADES"})
            self.send_message(chat_id, "🔍 Buscando sesiones activas en el Córtex...")
        elif text.startswith("/switch "):
            parts = text.split(" ")
            if len(parts) == 2 and parts[1].isdigit():
                payload = json.dumps({"command": "SWITCH_CASCADE", "index": int(parts[1])})
            else:
                self.send_message(chat_id, "❌ Uso: /switch <número>")
                return
        else:
            payload = json.dumps({"text": text})

        # Check health
        if not self.check_red_pill_health():
            self.send_message(chat_id, "⚠️ Córtex Offline. El IDE o Red-Pill no responde. El mensaje será encolado.")
            
        logger.info(f"Received from Telegram: {text}")
        conn = get_connection()
        
        # Insert into Inbox
        conn.execute(
            "INSERT INTO inbox (channel, channel_user_id, payload) VALUES (?, ?, ?)",
            ("telegram", chat_id, payload)
        )
        conn.commit()
        conn.close()

    def poll_telegram(self):
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
        logger.info("Started Telegram Ingress Polling...")
        while self.running:
            if BOT_TOKEN == "REPLACE_ME":
                logger.error("TELEGRAM_BOT_TOKEN not set. Exiting Ingress loop.")
                break
                
            try:
                resp = requests.get(url, params={"timeout": 10, "offset": self.offset}, timeout=15)
                if resp.status_code == 200:
                    data = resp.json()
                    for update in data.get('result', []):
                        self.offset = update['update_id'] + 1
                        if 'message' in update:
                            self.handle_message(update['message'])
            except Exception as e:
                logger.error(f"Telegram polling error: {e}")
                time.sleep(5)

    def poll_outbox(self):
        logger.info("Started Telegram Egress Polling...")
        while self.running:
            try:
                conn = get_connection()
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM outbox WHERE status = 'PENDING' AND channel = 'telegram' ORDER BY created_at ASC")
                rows = cursor.fetchall()
                
                for row in rows:
                    payload = json.loads(row['payload'])
                    text = payload.get("text", "No text provided")
                    self.send_message(row['channel_user_id'], text)
                    cursor.execute("UPDATE outbox SET status = 'SENT' WHERE id = ?", (row['id'],))
                    logger.info(f"Sent reply to Telegram: {row['id']}")
                    
                conn.commit()
                conn.close()
                time.sleep(1)
            except Exception as e:
                logger.error(f"Outbox polling error: {e}")
                time.sleep(5)

    def run(self):
        t1 = threading.Thread(target=self.poll_telegram)
        t2 = threading.Thread(target=self.poll_outbox)
        t1.daemon = True
        t2.daemon = True
        t1.start()
        t2.start()
        
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Shutting down Telegram Hub...")
            self.running = False
            t1.join()
            t2.join()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    hub = TelegramHub()
    hub.run()
