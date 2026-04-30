from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable

from neon_link.core.crypto import IdentityManager
from neon_link.models.base import Group, Message


class NetworkPlugin(ABC):
    """
    Interfaz abstracta (Contrato) para cualquier proveedor de red.
    Un plugin debe implementar estos métodos para ser registrado en el Hub.
    """
    
    def __init__(self, name: str, identity_manager: IdentityManager):
        self.name = name
        self.identity_manager = identity_manager
        self._on_message_callback: Callable[[Message], Awaitable[None]] | None = None

    def register_callback(self, callback: Callable[[Message], Awaitable[None]]):
        """Registra el callback que el Hub inyectará para recibir eventos Push."""
        self._on_message_callback = callback

    @abstractmethod
    async def start(self):
        """Inicia la conexión persistente (ej. WebSockets)."""
        pass

    @abstractmethod
    async def stop(self):
        """Cierra la conexión de forma limpia."""
        pass

    @abstractmethod
    async def send_message(self, group_id: str, message: Message) -> bool:
        """Enruta el mensaje hacia la red externa (encriptando si es necesario)."""
        pass

    @abstractmethod
    async def create_group(self, group: Group) -> Group:
        """Crea un grupo en el proveedor subyacente."""
        pass
