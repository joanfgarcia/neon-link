from fastapi.testclient import TestClient

from neon_link.api.server import app
from neon_link.core.inbox import inbox
from neon_link.models.base import Message

client = TestClient(app)

def test_get_inbox_summary():
    # Limpiamos el estado global (inbox es un Singleton)
    inbox.queues.clear()
    
    msg = Message(message_id="test", timestamp=0.0, group_id="g1", sender_id="s1", content="...")
    inbox.push("Alpha", msg)
    
    response = client.get("/inbox/summary")
    assert response.status_code == 200
    data = response.json()
    assert data["Alpha"] == 1

def test_get_agent_inbox():
    inbox.queues.clear()
    msg = Message(message_id="test2", timestamp=0.0, group_id="g1", sender_id="s1", content="...")
    inbox.push("Beta", msg)
    
    response = client.get("/inbox/Beta")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["message_id"] == "test2"
    
    # La cola debe quedar vacía
    assert len(inbox.queues["Beta"]) == 0
