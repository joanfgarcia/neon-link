
from pydantic import BaseModel, Field


class Contact(BaseModel):
    user_id: str
    name: str | None = None

class Group(BaseModel):
    group_id: str
    name: str | None = None
    members: list[str] = Field(default_factory=list)

class Message(BaseModel):
    message_id: str
    group_id: str
    sender_id: str
    content: str
    timestamp: float
