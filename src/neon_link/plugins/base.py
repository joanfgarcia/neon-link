from abc import ABC, abstractmethod
from typing import List, Callable, Awaitable
from neon_link.models.base import Contact, Group, Message

class NetworkPlugin(ABC):
    """
    Interfaz abstracta (Contrato) para cualquier proveedor de red.
    Un plugin debe implementar estos métodos para ser registrado en el Hub.
    """
    
    def __init__(self, name: str):
        self.name = name
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
