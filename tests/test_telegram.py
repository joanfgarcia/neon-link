from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from neon_link.core.crypto import IdentityManager
from neon_link.plugins.telegram import TelegramHub


@pytest.fixture
def mock_identity_manager():
	return MagicMock(spec=IdentityManager)


@patch("neon_link.plugins.telegram.requests")
def test_send_message(mock_req, mock_identity_manager):
	hub = TelegramHub(mock_identity_manager)
	hub.send_message("123", "Hello")
	mock_req.post.assert_called_once()


@pytest.mark.asyncio
@patch("neon_link.plugins.telegram.requests")
async def test_send_event(mock_req, mock_identity_manager):
	hub = TelegramHub(mock_identity_manager)
	mock_req.post.return_value.status_code = 200
	from neon_link.models.network import NetworkEvent

	event = NetworkEvent(type="application", recipient_id="123", payload=b"Hello")
	assert await hub.send_event(event) is True


@patch("neon_link.plugins.telegram.get_connection")
def test_handle_message(mock_get_conn, mock_identity_manager):
	import neon_link.plugins.telegram as tg

	tg.ALLOWED_USER_ID = "123"

	hub = TelegramHub(mock_identity_manager)
	hub.check_red_pill_health = MagicMock(return_value=True)
	hub._on_event_callback = AsyncMock()

	msg = {"chat": {"id": "123", "type": "private"}, "text": "/start"}
	hub.send_message = MagicMock()
	hub.handle_message(msg)
	hub.send_message.assert_called_with("123", "⚡ Bünker Neon-Link conectado. Gateway I/O Activo. Esperando inputs.")

	msg["text"] = "/list"
	hub.handle_message(msg)

	msg["text"] = "Hello bot"
	hub.handle_message(msg)
	# the callback should have been called
	assert hub._on_event_callback.called


@patch("neon_link.plugins.telegram.requests")
def test_poll_telegram(mock_req, mock_identity_manager):
	hub = TelegramHub(mock_identity_manager)
	mock_resp = MagicMock()
	mock_resp.status_code = 200
	mock_resp.json.return_value = {"result": [{"update_id": 1, "message": {"chat": {"id": 123}, "text": "Hi"}}]}

	def mock_get(*args, **kwargs):
		hub.running = False
		return mock_resp

	mock_req.get.side_effect = mock_get
	hub.handle_message = MagicMock()

	import neon_link.plugins.telegram as tg

	tg.BOT_TOKEN = "TEST_TOKEN"
	hub.running = True
	hub.poll_telegram()
	hub.handle_message.assert_called_once()


@pytest.mark.asyncio
async def test_start_stop(mock_identity_manager):
	hub = TelegramHub(mock_identity_manager)
	with patch("neon_link.plugins.telegram.threading.Thread") as mock_thread:
		await hub.start()
		mock_thread.assert_called()
		await hub.stop()
		mock_thread.return_value.join.assert_called()
