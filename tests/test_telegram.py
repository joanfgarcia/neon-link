import pytest
import json
from unittest.mock import patch, MagicMock
from neon_link.plugins.telegram import TelegramHub

@patch("neon_link.plugins.telegram.requests")
def test_send_message(mock_req):
	hub = TelegramHub()
	hub.send_message("123", "Hello")
	mock_req.post.assert_called_once()

@patch("neon_link.plugins.telegram.get_connection")
def test_handle_message(mock_get_conn):
	mock_conn = MagicMock()
	mock_get_conn.return_value = mock_conn
	
	import neon_link.plugins.telegram as tg
	tg.ALLOWED_USER_ID = "123"
	
	hub = TelegramHub()
	hub.check_red_pill_health = MagicMock(return_value=True)
	
	msg = {
		"chat": {"id": "123", "type": "private"},
		"text": "/start"
	}
	hub.send_message = MagicMock()
	hub.handle_message(msg)
	hub.send_message.assert_called_with("123", "⚡ Bünker Neon-Link conectado. Gateway I/O Activo. Esperando inputs.")
	
	msg["text"] = "/list"
	hub.handle_message(msg)
	
	msg["text"] = "Hello bot"
	hub.handle_message(msg)
	mock_conn.execute.assert_called()

@patch("neon_link.plugins.telegram.requests")
def test_poll_telegram(mock_req):
	hub = TelegramHub()
	
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
	hub.poll_telegram()
		
	hub.handle_message.assert_called_once()

@patch("neon_link.plugins.telegram.get_connection")
def test_poll_outbox(mock_get_conn):
	mock_conn = MagicMock()
	mock_cursor = MagicMock()
	mock_conn.cursor.return_value = mock_cursor
	mock_get_conn.return_value = mock_conn
	
	mock_cursor.fetchall.return_value = [
		{"id": 1, "channel_user_id": "123", "payload": json.dumps({"text": "Reply"})}
	]
	
	hub = TelegramHub()
	hub.send_message = MagicMock()
	
	def stop_loop(*args, **kwargs):
		hub.running = False
		
	with patch("neon_link.plugins.telegram.time.sleep", side_effect=stop_loop):
		hub.poll_outbox()
		
	hub.send_message.assert_called_with("123", "Reply")
	mock_cursor.execute.assert_any_call("UPDATE outbox SET status = 'SENT' WHERE id = ?", (1,))

@patch("neon_link.plugins.telegram.get_connection")
def test_check_red_pill_health(mock_get_conn):
	mock_conn = MagicMock()
	mock_cursor = MagicMock()
	mock_get_conn.return_value = mock_conn
	mock_conn.cursor.return_value = mock_cursor
	
	hub = TelegramHub()
	
	# health ok
	mock_cursor.fetchone.return_value = (50,)
	assert hub.check_red_pill_health() is True
	
	# health bad
	mock_cursor.fetchone.return_value = (70,)
	assert hub.check_red_pill_health() is False

@patch("neon_link.plugins.telegram.threading.Thread")
def test_threads(mock_thread):
	hub = TelegramHub()
	hub.start_threads()
	mock_thread.assert_called()
	
	mock_thread_instance = MagicMock()
	hub.t1 = mock_thread_instance
	hub.t2 = mock_thread_instance
	hub.stop_threads()
	mock_thread_instance.join.assert_called()

@patch("neon_link.plugins.telegram.get_connection")
def test_handle_message_branches(mock_get_conn):
	mock_conn = MagicMock()
	mock_cursor = MagicMock()
	mock_get_conn.return_value = mock_conn
	mock_conn.cursor.return_value = mock_cursor
	mock_cursor.fetchone.return_value = (50,)
	
	hub = TelegramHub()
	import neon_link.plugins.telegram as tg
	tg.ALLOWED_USER_ID = "123"
	
	msg = {"chat": {"id": "444", "type": "private"}, "text": "test"}
	hub.handle_message(msg) # Unauthorized
	
	msg = {"chat": {"id": "123", "type": "private"}, "text": "/switch 1"}
	hub.handle_message(msg)
	
	msg = {"chat": {"id": "123", "type": "private"}, "text": "/switch"}
	hub.handle_message(msg)
	
	msg = {"chat": {"id": "123", "type": "private"}, "text": "/bg hello"}
	hub.handle_message(msg)
	
	msg = {"chat": {"id": "123", "type": "group"}, "text": "@bot test"}
	tg.os.environ["TELEGRAM_BOT_USERNAME"] = "bot"
	hub.handle_message(msg)

@patch("neon_link.plugins.telegram.requests")
def test_send_message_error(mock_req):
	mock_req.post.side_effect = Exception("error")
	TelegramHub().send_message("123", "msg")

@patch("neon_link.plugins.telegram.requests")
def test_poll_telegram_error(mock_req):
	mock_req.get.side_effect = Exception("error")
	hub = TelegramHub()
	import neon_link.plugins.telegram as tg
	tg.BOT_TOKEN = "TEST_TOKEN"
	def stop_loop(*args, **kwargs): hub.running = False
	with patch("neon_link.plugins.telegram.time.sleep", side_effect=stop_loop):
		hub.poll_telegram()

@patch("neon_link.plugins.telegram.get_connection")
def test_poll_outbox_error(mock_get):
	mock_get.side_effect = Exception("error")
	hub = TelegramHub()
	def stop_loop(*args, **kwargs): hub.running = False
	with patch("neon_link.plugins.telegram.time.sleep", side_effect=stop_loop):
		hub.poll_outbox()
