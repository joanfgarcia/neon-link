from pydantic import BaseModel
from typing import Literal

class NetworkEvent(BaseModel):
	"""
	Standard event passed between CryptoMiddleware and Transport plugins.
	- type: The MLS semantic type of the message.
	- recipient_id: The target destination. If type is 'welcome', this is a user ID. Otherwise, a group ID.
	- payload: The raw bytes to transmit.
	"""
	type: Literal["application", "welcome", "update"]
	recipient_id: str
	payload: bytes
