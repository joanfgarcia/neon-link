from neon_link.core.inbox import LocalInbox
from neon_link.models.base import Message


def test_inbox_push_and_summary():
    inbox = LocalInbox()
    
    msg1 = Message(message_id="1", timestamp=0.0, group_id="g1", sender_id="s1", content="hello")
    msg2 = Message(message_id="2", timestamp=0.0, group_id="g1", sender_id="s2", content="world")
    
    inbox.push("AgentA", msg1)
    inbox.push("AgentA", msg2)
    inbox.push("AgentB", msg1)
    
    summary = inbox.summary()
    assert summary["AgentA"] == 2
    assert summary["AgentB"] == 1
    assert summary.get("AgentC", 0) == 0

def test_inbox_pop_all():
    inbox = LocalInbox()
    msg = Message(message_id="1", timestamp=0.0, group_id="g1", sender_id="s1", content="hello")
    inbox.push("AgentX", msg)
    
    msgs = inbox.pop_all("AgentX")
    assert len(msgs) == 1
    assert msgs[0].message_id == "1"
    
    # Después de hacer pop, la cola debe estar vacía
    assert len(inbox.pop_all("AgentX")) == 0
    assert inbox.summary().get("AgentX", 0) == 0
