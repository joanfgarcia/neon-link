from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from neon_link.core.crypto import IdentityManager
from neon_link.plugins.telegram import TelegramHub


@pytest.fixture
def mock_identity_manager():
	return MagicMock(spec=IdentityManager)


@patch("neon_link.plugins.telegram.requests")
def test_send_message(mock_req, mock_identity_manager):
	hub = TelegramHub(mock_identity_manager, bot_token="TEST_TOKEN", allowed_user_id="123")
	hub.send_message("123", "Hello")
	mock_req.post.assert_called_once()


@pytest.mark.asyncio
@patch("neon_link.plugins.telegram.requests")
async def test_send_event(mock_req, mock_identity_manager):
	hub = TelegramHub(mock_identity_manager, bot_token="TEST_TOKEN", allowed_user_id="123")
	mock_req.post.return_value.status_code = 200
	from neon_link.models.network import NetworkEvent

	event = NetworkEvent(type="application", recipient_id="123", payload=b"Hello")
	assert await hub.send_event(event) is True


@patch("neon_link.plugins.telegram.get_connection")
def test_handle_message(mock_get_conn, mock_identity_manager):
	hub = TelegramHub(mock_identity_manager, bot_token="TEST_TOKEN", allowed_user_id="123")
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
	hub = TelegramHub(mock_identity_manager, bot_token="TEST_TOKEN", allowed_user_id="123")
	mock_resp = MagicMock()
	mock_resp.status_code = 200
	mock_resp.json.return_value = {"result": [{"update_id": 1, "message": {"chat": {"id": 123}, "text": "Hi"}}]}

	def mock_get(*args, **kwargs):
		hub.running = False
		return mock_resp

	mock_req.get.side_effect = mock_get
	hub.handle_message = MagicMock()

	hub.running = True
	hub.poll_telegram()
	hub.handle_message.assert_called_once()


@pytest.mark.asyncio
async def test_start_stop(mock_identity_manager):
	hub = TelegramHub(mock_identity_manager, bot_token="TEST_TOKEN", allowed_user_id="123")
	with patch("neon_link.plugins.telegram.threading.Thread") as mock_thread:
		await hub.start()
		mock_thread.assert_called()
		await hub.stop()
		mock_thread.return_value.join.assert_called()


def test_split_message(mock_identity_manager):
	hub = TelegramHub(mock_identity_manager, bot_token="TEST_TOKEN", allowed_user_id="123")
	chunks = hub._split_message("hello")
	assert chunks == ["hello"]

	long_msg = "A" * 4500
	chunks = hub._split_message(long_msg)
	assert len(chunks) == 2
	assert chunks[0].endswith("...\n1/2")
	assert chunks[1].startswith("...")
	assert chunks[1].endswith("\n2/2")


@pytest.mark.asyncio
@patch("neon_link.plugins.telegram.requests")
async def test_send_event_has_timeout(mock_req, mock_identity_manager):
	"""Sin timeout un POST colgado bloqueaba el hilo de egress para siempre."""
	hub = TelegramHub(mock_identity_manager, bot_token="T", allowed_user_id="123")
	mock_req.post.return_value.status_code = 200
	from neon_link.models.network import NetworkEvent

	await hub.send_event(NetworkEvent(type="application", recipient_id="123", payload=b"Hello"))
	assert mock_req.post.call_args.kwargs["timeout"]


@pytest.mark.asyncio
@patch("neon_link.plugins.telegram.requests")
async def test_send_event_rejection_is_permanent(mock_req, mock_identity_manager):
	from neon_link.models.network import NetworkEvent
	from neon_link.plugins.base import PermanentEgressError

	hub = TelegramHub(mock_identity_manager, bot_token="T", allowed_user_id="123")
	mock_req.post.return_value.status_code = 400
	mock_req.post.return_value.text = '{"description":"Bad Request: chat not found"}'
	with pytest.raises(PermanentEgressError):
		await hub.send_event(NetworkEvent(type="application", recipient_id="999", payload=b"Hello"))


@pytest.mark.asyncio
@patch("neon_link.plugins.telegram.asyncio.sleep", new_callable=AsyncMock)
@patch("neon_link.plugins.telegram.requests")
async def test_send_event_retry_resumes_after_delivered_chunks(mock_req, _sleep, mock_identity_manager):
	"""Un reintento no reenvía los trozos ya entregados de un mensaje largo."""
	from neon_link.models.network import NetworkEvent

	hub = TelegramHub(mock_identity_manager, bot_token="T", allowed_user_id="123")
	ok, err = MagicMock(status_code=200), MagicMock(status_code=502, text="bad gateway")
	event = NetworkEvent(type="application", recipient_id="123", payload=("x" * 9000).encode())

	mock_req.post.side_effect = [ok, err]
	assert await hub.send_event(event) is False
	mock_req.post.side_effect = [ok, ok]
	assert await hub.send_event(event) is True

	sent = [c.kwargs["json"]["text"] for c in mock_req.post.call_args_list]
	assert len(sent) == 4
	assert sent[0].endswith("1/3") and sent[2].endswith("2/3") and sent[3].endswith("3/3")
	assert not hub._chunk_progress


def test_ingest_failure_keeps_offset_so_telegram_redelivers(mock_identity_manager):
	"""Si encolar falla (DB bloqueada), el offset NO avanza: Telegram lo reenvía."""
	hub = TelegramHub(mock_identity_manager, bot_token="T", allowed_user_id="123")
	hub.handle_message = MagicMock(side_effect=RuntimeError("database is locked"))
	attempts: dict[int, int] = {}
	with patch("neon_link.plugins.telegram.time.sleep"):
		assert hub._ingest_update({"update_id": 10, "message": {}}, attempts) is False
	assert hub.offset == 0 and attempts == {10: 1}

	hub.handle_message = MagicMock()
	assert hub._ingest_update({"update_id": 10, "message": {}}, attempts) is True
	assert hub.offset == 11 and attempts == {}


def test_ingest_gives_up_after_max_attempts(mock_identity_manager):
	from neon_link.plugins import telegram as tg

	hub = TelegramHub(mock_identity_manager, bot_token="T", allowed_user_id="123")
	hub.handle_message = MagicMock(side_effect=RuntimeError("boom"))
	attempts = {5: tg._MAX_INGRESS_ATTEMPTS - 1}
	assert hub._ingest_update({"update_id": 5, "message": {}}, attempts) is True
	assert hub.offset == 6 and attempts == {}


@patch("neon_link.plugins.telegram.requests")
def test_poll_backs_off_on_http_errors(mock_req, mock_identity_manager):
	"""409/5xx: log + espera creciente, no un bucle caliente contra la API."""
	hub = TelegramHub(mock_identity_manager, bot_token="T", allowed_user_id="123")
	hub.running = True
	mock_req.get.return_value = MagicMock(status_code=409, text="Conflict")
	sleeps = []

	def _sleep(s):
		sleeps.append(s)
		if len(sleeps) == 3:
			hub.running = False

	with patch("neon_link.plugins.telegram.time.sleep", side_effect=_sleep):
		hub.poll_telegram()
	assert sleeps == [1.0, 2.0, 4.0]


def test_health_check_never_raises(mock_identity_manager):
	hub = TelegramHub(mock_identity_manager, bot_token="T", allowed_user_id="123")
	with patch("neon_link.plugins.telegram.get_connection", side_effect=RuntimeError("database is locked")):
		assert hub.check_red_pill_health() is True
