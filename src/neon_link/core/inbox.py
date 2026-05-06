import collections

from neon_link.models.base import Message


class LocalInbox:
	"""
	Memoria temporal (Buffer) para mensajes entrantes desencriptados.
	Evita depender de Webhooks hacia el cliente. El cliente hace polling.
	"""

	def __init__(self):
		self.queues: dict[str, collections.deque[Message]] = collections.defaultdict(collections.deque)

	def push(self, agent_id: str, msg: Message):
		self.queues[agent_id].append(msg)

	def summary(self) -> dict[str, int]:
		return {agent: len(q) for agent, q in self.queues.items()}

	def pop_all(self, agent_id: str) -> list[Message]:
		msgs = list(self.queues[agent_id])
		self.queues[agent_id].clear()
		return msgs


# Singleton global para la instancia de FastAPI
inbox = LocalInbox()
