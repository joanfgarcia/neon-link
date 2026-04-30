import logging

import httpx

logger = logging.getLogger(__name__)

class WebhookNotifier:
    def __init__(self, target_url: str):
        self.target_url = target_url
        self.client = httpx.AsyncClient()

    async def notify_message(self, message_data: dict, urgency: float = 5.0):
        """
        Envía un POST al Webhook configurado.
        Red-Pill traducirá esto en una Señal de Dolor de intensidad = urgency.
        """
        payload = {
            "type": "incoming_message",
            "urgency": urgency,
            "data": message_data
        }
        try:
            response = await self.client.post(self.target_url, json=payload)
            response.raise_for_status()
        except Exception as e:
            logger.error(f"Failed to deliver webhook to {self.target_url}: {e}")
