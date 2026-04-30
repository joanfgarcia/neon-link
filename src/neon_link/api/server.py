
from fastapi import FastAPI

from neon_link.core.inbox import inbox
from neon_link.models.base import Contact, Group, Message

app = FastAPI(
    title="Neon-Link",
    description="Agnostic Communication Hub",
    version="0.1.0"
)

@app.get("/inbox/summary", response_model=dict[str, int])
async def get_inbox_summary():
    """Retorna un recuento de los mensajes en cola para cada agente (Optimizado para el Heartbeat)."""
    return inbox.summary()

@app.get("/inbox/{agent_id}", response_model=list[Message])
async def get_agent_inbox(agent_id: str):
    """Retorna todos los mensajes de un agente y limpia la cola local."""
    return inbox.pop_all(agent_id)

@app.get("/contacts", response_model=list[Contact])
async def get_contacts():
    """Obtener la agenda de contactos sincronizada."""
    return []

@app.post("/groups", response_model=Group)
async def create_group(group: Group):
    """Crear un nuevo grupo (o iniciar chat 1v1)."""
    return group

@app.post("/groups/{group_id}/members")
async def add_member(group_id: str, user_id: str):
    """Añadir un usuario a un grupo existente."""
    return {"status": "ok", "group_id": group_id, "added": user_id}

@app.delete("/groups/{group_id}/members/{user_id}")
async def remove_member(group_id: str, user_id: str):
    """Eliminar o salir de un grupo."""
    return {"status": "ok", "group_id": group_id, "removed": user_id}

@app.post("/groups/{group_id}/messages")
async def send_message(group_id: str, message: Message):
    """Enviar un mensaje al grupo."""
    return {"status": "sent", "message_id": message.message_id}
