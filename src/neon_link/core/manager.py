import logging
from typing import Dict
from neon_link.plugins.base import NetworkPlugin
from neon_link.models.base import Message
from neon_link.core.webhook import WebhookNotifier

from neon_link.core.crypto import IdentityManager

logger = logging.getLogger(__name__)

class PluginManager:
    def __init__(self, webhook_notifier: WebhookNotifier, identity_manager: IdentityManager):
        self.plugins: Dict[str, NetworkPlugin] = {}
        self.webhook_notifier = webhook_notifier
        self.identity_manager = identity_manager

    def register(self, plugin: NetworkPlugin):
        """Registra un plugin y le inyecta el callback de llegada de mensajes."""
        logger.info(f"Registrando plugin: {plugin.name}")
        plugin.register_callback(self._handle_incoming_message)
        self.plugins[plugin.name] = plugin

    async def _handle_incoming_message(self, message: Message):
        """
        Callback central. Todos los plugins disparan este método cuando reciben un mensaje.
        Aquí se enruta el payload hacia Red-Pill usando el Webhook.
        """
        logger.info(f"Mensaje entrante interceptado del grupo {message.group_id}")
        await self.webhook_notifier.notify_message(message.model_dump())

    async def start_all(self):
        for name, plugin in self.plugins.items():
            logger.info(f"Iniciando {name}...")
            await plugin.start()

    async def stop_all(self):
        for name, plugin in self.plugins.items():
            logger.info(f"Deteniendo {name}...")
            await plugin.stop()

    def get_plugin(self, name: str) -> NetworkPlugin:
        return self.plugins[name]
