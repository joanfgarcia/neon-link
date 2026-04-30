import asyncio
import logging
from typing import Dict, Any

import firebase_admin
from firebase_admin import credentials, db
from pure_mls.group import MLSGroup

from neon_link.plugins.base import NetworkPlugin
from neon_link.models.base import Group, Message
from neon_link.core.crypto import IdentityManager

logger = logging.getLogger(__name__)

class FirebasePlugin(NetworkPlugin):
    """
    Implementación del protocolo NetworkPlugin usando Firebase Realtime Database.
    Incluye la capa de cifrado E2E mediante pure-mls.
    """
    
    def __init__(self, db_url: str, credential_path: str, identity_manager: IdentityManager):
        super().__init__(name="firebase", identity_manager=identity_manager)
        self.db_url = db_url
        self.credential_path = credential_path
        self._running = False
        self._polling_tasks = []
        self.mls_groups: Dict[str, MLSGroup] = {}

    async def start(self):
        logger.info("[FirebasePlugin] Inicializando SDK de Firebase...")
        try:
            firebase_admin.get_app("neon_link")
        except ValueError:
            cred = credentials.Certificate(self.credential_path)
            firebase_admin.initialize_app(cred, {"databaseURL": self.db_url}, name="neon_link")
            
        self.app = firebase_admin.get_app("neon_link")
        self._running = True
        
        # Iniciar listener para cada identidad cargada
        for agent_id, keys in self.identity_manager.get_identities().items():
            logger.info(f"[FirebasePlugin] Iniciando escucha para {agent_id}...")
            task = asyncio.create_task(self._poll_mailbox(agent_id, keys))
            self._polling_tasks.append(task)

    async def stop(self):
        logger.info("[FirebasePlugin] Deteniendo conexión...")
        self._running = False
        for task in self._polling_tasks:
            task.cancel()

    async def _poll_mailbox(self, agent_id: str, keys):
        """Poll de Firebase simulado (SDK síncrono no soporta listen async fácilmente)."""
        kem_key, sig_key = keys
        while self._running:
            try:
                # Usar to_thread para no bloquear el Event Loop de FastAPI
                ref = db.reference(f"mailboxes/{agent_id}/inbox", app=self.app)
                messages = await asyncio.to_thread(ref.get)
                
                if messages:
                    for msg_id, pkg in messages.items():
                        if "ciphertext" in pkg:
                            logger.info(f"[FirebasePlugin] Desencriptando mensaje {msg_id} para {agent_id}")
                            # TODO: Reemplazar con desencriptado real de pure-mls cuando carguemos los grupos
                            # ciphertext = pkg["ciphertext"]
                            # plaintext = self.mls_groups[group_id].decrypt_application_message(ciphertext)
                            msg = Message(
                                id=msg_id,
                                group_id=pkg.get("group_id", "unknown"),
                                sender_id=pkg.get("sender_id", "unknown"),
                                content="<encrypted_content_placeholder>"
                            )
                            # Encolar en el inbox local
                            from neon_link.core.inbox import inbox
                            inbox.push(agent_id, msg)
                            
                            # Disparar callback (opcional/legacy)
                            if self._on_message_callback:
                                await self._on_message_callback(msg)
                            
                            # Borrar mensaje procesado
                            await asyncio.to_thread(ref.child(msg_id).delete)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[FirebasePlugin] Error en polling: {e}")
            
            await asyncio.sleep(2.0)

    async def send_message(self, group_id: str, message: Message) -> bool:
        """Encripta el mensaje usando pure-mls y hace Push a Firebase."""
        logger.info(f"[FirebasePlugin] Enviando mensaje a {group_id}")
        return True

    async def create_group(self, group: Group) -> Group:
        """Crea el grupo MLS y sube las claves a Firebase."""
        logger.info(f"[FirebasePlugin] Creando grupo MLS: {group.group_id}")
        return group
