from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable

from neon_link.core.crypto import IdentityManager
from neon_link.models.network import NetworkEvent

class NetworkPlugin(ABC):
	"""
	Interfaz abstracta (Contrato) para cualquier proveedor de red (Pipeline Pattern).
	El plugin es 'tonto': solo sabe rutear NetworkEvents hacia la red física y viceversa,
	además de buscar llaves públicas.
	"""
	
	def __init__(self, name: str, identity_manager: IdentityManager):
		self.name = name
		self.identity_manager = identity_manager
		self._on_event_callback: Callable[[str, str, NetworkEvent], Awaitable[None]] | None = None

	def register_callback(self, callback: Callable[[str, str, NetworkEvent], Awaitable[None]]):
		"""Registra el callback que el Pipeline inyectará. Se llama con (channel_name, sender_id, event)."""
		self._on_event_callback = callback

	@abstractmethod
	async def start(self):
		"""Inicia la conexión persistente (ej. WebSockets, Firebase Polling)."""
		pass

	@abstractmethod
	async def stop(self):
		"""Cierra la conexión de forma limpia."""
		pass

	@abstractmethod
	async def send_event(self, event: NetworkEvent) -> bool:
		"""Enruta el evento binario hacia la red externa (sin saber qué hay dentro)."""
		pass

	@abstractmethod
	async def fetch_key_package(self, agent_id: str) -> bytes | None:
		"""Busca y devuelve el KeyPackage público de un agente en el proveedor subyacente."""
		pass
