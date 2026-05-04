import os
import json
import time
import sqlite3
import threading
import logging
import asyncio

import firebase_admin
from firebase_admin import credentials, db

# Assuming pure_mls is installed and configured somewhere in the system
# We will mock the pure_mls usage as per the previous file's structure if it's not fully ready,
# but we'll include the hooks for it.
from pure_mls.group import MLSGroup

from neon_link.db import get_connection

logger = logging.getLogger(__name__)

class FirebaseHub:
    def __init__(self):
        self.running = True
        self.db_url = os.environ.get("FIREBASE_DB_URL", "https://replace-me.firebaseio.com")
        self.credential_path = os.environ.get("FIREBASE_CREDENTIALS", "firebase-keys.json")
        self.agent_id = os.environ.get("NEON_LINK_AGENT_ID", "red_pill_core")
        self.mls_groups = {} # Dictionary mapping group_id -> MLSGroup
        
        logger.info("[FirebaseHub] Initializing Firebase SDK...")
        try:
            firebase_admin.get_app("neon_link")
        except ValueError:
            try:
                cred = credentials.Certificate(self.credential_path)
                firebase_admin.initialize_app(cred, {"databaseURL": self.db_url}, name="neon_link")
            except Exception as e:
                logger.error(f"Failed to load Firebase credentials from {self.credential_path}: {e}")
                
        try:
            self.app = firebase_admin.get_app("neon_link")
        except ValueError:
            self.app = None

    def decrypt_payload(self, group_id, ciphertext):
        """Decrypts the E2E payload using pure-mls."""
        if group_id not in self.mls_groups:
            logger.warning(f"[FirebaseHub] Unknown MLS group {group_id}. Cannot decrypt. Returning raw.")
            return ciphertext
        try:
            # Placeholder for actual MLS decrypt
            # plaintext = self.mls_groups[group_id].decrypt_application_message(ciphertext)
            return ciphertext # Fallback for now until MLS groups are persisted
        except Exception as e:
            logger.error(f"Decryption failed: {e}")
            return ciphertext

    def encrypt_payload(self, group_id, plaintext):
        """Encrypts the payload using pure-mls before sending to Firebase."""
        if group_id not in self.mls_groups:
            logger.warning(f"[FirebaseHub] Unknown MLS group {group_id}. Cannot encrypt. Sending raw.")
            return plaintext
        try:
            # Placeholder for actual MLS encrypt
            # ciphertext = self.mls_groups[group_id].encrypt_application_message(plaintext)
            return plaintext # Fallback
        except Exception as e:
            logger.error(f"Encryption failed: {e}")
            return plaintext

    def poll_firebase(self):
        logger.info("[FirebaseHub] Started Firebase Ingress Polling...")
        while self.running:
            if not self.app:
                logger.error("Firebase App not initialized. Exiting Ingress loop.")
                break
                
            try:
                ref = db.reference(f"mailboxes/{self.agent_id}/inbox", app=self.app)
                messages = ref.get()
                
                if messages:
                    conn = get_connection()
                    for msg_id, pkg in messages.items():
                        group_id = pkg.get("group_id", "unknown")
                        sender_id = pkg.get("sender_id", "unknown")
                        
                        if "ciphertext" in pkg:
                            logger.info(f"[FirebaseHub] Received encrypted message {msg_id}")
                            plaintext = self.decrypt_payload(group_id, pkg["ciphertext"])
                            
                            # Insert into local SQLite WAL
                            payload = json.dumps({"text": plaintext, "sender_id": sender_id})
                            
                            conn.execute(
                                "INSERT INTO inbox (channel, channel_user_id, payload) VALUES (?, ?, ?)",
                                ("firebase", sender_id, payload)
                            )
                            logger.info(f"[FirebaseHub] Enqueued message from {sender_id} to local DB.")
                            
                        # Delete message from Firebase once enqueued
                        ref.child(msg_id).delete()
                        
                    conn.commit()
                    conn.close()
                    
            except Exception as e:
                logger.error(f"[FirebaseHub] Polling error: {e}")
                
            time.sleep(2.0)

    def poll_outbox(self):
        logger.info("[FirebaseHub] Started Firebase Egress Polling...")
        while self.running:
            if not self.app:
                break
                
            try:
                conn = get_connection()
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM outbox WHERE status = 'PENDING' AND channel = 'firebase' ORDER BY created_at ASC")
                rows = cursor.fetchall()
                
                for row in rows:
                    payload = json.loads(row['payload'])
                    text = payload.get("text", "No text provided")
                    recipient_id = row['channel_user_id']
                    
                    # Assume group_id is somehow mapped or we use recipient_id
                    group_id = recipient_id 
                    ciphertext = self.encrypt_payload(group_id, text)
                    
                    # Push to Firebase recipient's inbox
                    try:
                        out_ref = db.reference(f"mailboxes/{recipient_id}/inbox", app=self.app)
                        out_ref.push({
                            "sender_id": self.agent_id,
                            "group_id": group_id,
                            "ciphertext": ciphertext,
                            "timestamp": time.time()
                        })
                        
                        cursor.execute("UPDATE outbox SET status = 'SENT' WHERE id = ?", (row['id'],))
                        logger.info(f"[FirebaseHub] Sent reply to Firebase: {row['id']}")
                    except Exception as push_err:
                        logger.error(f"[FirebaseHub] Failed to push to Firebase: {push_err}")
                    
                conn.commit()
                conn.close()
            except Exception as e:
                logger.error(f"[FirebaseHub] Outbox polling error: {e}")
                
            time.sleep(1.0)

    def start_threads(self):
        self.t1 = threading.Thread(target=self.poll_firebase)
        self.t2 = threading.Thread(target=self.poll_outbox)
        self.t1.daemon = True
        self.t2.daemon = True
        self.t1.start()
        self.t2.start()

    def stop_threads(self):
        self.running = False
        if hasattr(self, 't1'):
            self.t1.join(timeout=2.0)
        if hasattr(self, 't2'):
            self.t2.join(timeout=2.0)
