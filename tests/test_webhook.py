import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from neon_link.core.webhook import WebhookNotifier

@pytest.mark.asyncio
async def test_webhook_notify():
	notifier = WebhookNotifier("http://test.url")
	notifier.client.post = AsyncMock()
	mock_resp = MagicMock()
	notifier.client.post.return_value = mock_resp
	
	await notifier.notify_message({"test": "data"}, 4.0)
	
	notifier.client.post.assert_called_once()
	args, kwargs = notifier.client.post.call_args
	assert args[0] == "http://test.url"
	assert kwargs["json"]["urgency"] == 4.0
	mock_resp.raise_for_status.assert_called_once()

@pytest.mark.asyncio
async def test_webhook_notify_error(caplog):
	import logging
	caplog.set_level(logging.ERROR)
	notifier = WebhookNotifier("http://test.url")
	notifier.client.post = AsyncMock(side_effect=Exception("Timeout"))
	
	await notifier.notify_message({"test": "data"})
	assert "Timeout" in caplog.text
