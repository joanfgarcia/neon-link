import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from neon_link.core.manager import PluginManager


@pytest.fixture
def manager_setup():
	notifier = MagicMock()
	identity = MagicMock()
	# Provide a dummy identity to avoid IndexError
	identity.get_identities.return_value = {"neon_link": ("dummy_kem", "dummy_sig")}
	return PluginManager(notifier, identity, "test_agent")


def test_register_plugin(manager_setup):
	plugin = MagicMock()
	plugin.name = "telegram"
	manager_setup.register(plugin)
	assert manager_setup.get_plugin("telegram") == plugin
	plugin.register_callback.assert_called_once()


@pytest.mark.asyncio
async def test_start_stop_all(manager_setup):
	plugin = MagicMock()
	plugin.name = "telegram"
	plugin.start = AsyncMock()
	plugin.stop = AsyncMock()
	manager_setup.register(plugin)

	await manager_setup.start_all()
	assert manager_setup.running is True
	plugin.start.assert_called_once()

	await manager_setup.stop_all()
	assert manager_setup.running is False
	plugin.stop.assert_called_once()


@patch("neon_link.core.manager.get_connection")
def test_poll_outbox_loop(mock_get_conn, manager_setup):
	mock_conn = MagicMock()
	mock_cursor = MagicMock()
	mock_conn.cursor.return_value = mock_cursor
	mock_get_conn.return_value = mock_conn

	import json

	row = {"id": 1, "channel": "telegram", "channel_user_id": "user123", "payload": json.dumps({"text": "Hello"})}
	mock_cursor.fetchall.return_value = [row]

	plugin = MagicMock()
	plugin.name = "telegram"
	manager_setup.register(plugin)

	from unittest.mock import AsyncMock

	manager_setup.pipeline.process_egress = AsyncMock(return_value=True)
	manager_setup._resolve_session = MagicMock(return_value="user123")
	manager_setup.running = True

	def side_effect(*args):
		manager_setup.running = False

	with patch("time.sleep", side_effect=side_effect):
		manager_setup._poll_outbox_loop()

	manager_setup.pipeline.process_egress.assert_called_once_with(plugin, "user123", "Hello")
	mock_cursor.execute.assert_any_call("UPDATE outbox SET status = 'SENT' WHERE id = ?", (1,))


def test_network_plugin_base():
	import asyncio
	from unittest.mock import MagicMock

	from neon_link.plugins.base import NetworkPlugin

	class TestPlugin(NetworkPlugin):
		async def start(self):
			await super().start()

		async def stop(self):
			await super().stop()

		async def send_event(self, event):
			await super().send_event(event)

		async def fetch_key_package(self, agent_id):
			await super().fetch_key_package(agent_id)

	plugin = TestPlugin("test", MagicMock())

	asyncio.run(plugin.start())
	asyncio.run(plugin.stop())
	asyncio.run(plugin.send_event(MagicMock()))
	asyncio.run(plugin.fetch_key_package("a"))


@patch("neon_link.core.manager.get_connection")
def test_poll_outbox_loop_failures(mock_get_conn, manager_setup):
	"""A failed send older than the age cap is dead-lettered."""
	mock_conn = MagicMock()
	mock_cursor = MagicMock()
	mock_conn.cursor.return_value = mock_cursor
	mock_get_conn.return_value = mock_conn

	import json

	row = {
		"id": 1,
		"channel": "telegram",
		"channel_user_id": "user123",
		"payload": json.dumps({"text": "Hello"}),
		"retries": 2,
		"age_s": 25 * 3600,
	}
	mock_cursor.fetchall.return_value = [row]

	plugin = MagicMock()
	plugin.name = "telegram"
	manager_setup.register(plugin)

	from unittest.mock import AsyncMock

	manager_setup.pipeline.process_egress = AsyncMock(return_value=False)
	manager_setup._resolve_session = MagicMock(return_value="user123")
	manager_setup.running = True

	def side_effect(*args):
		manager_setup.running = False

	with patch("time.sleep", side_effect=side_effect):
		manager_setup._poll_outbox_loop()

	mock_cursor.execute.assert_any_call("UPDATE outbox SET status = 'FAILED' WHERE id = ?", (1,))
	mock_cursor.execute.assert_any_call(
		"INSERT INTO dead_letters (original_table, original_id, channel, channel_user_id, payload, error_reason) VALUES (?, ?, ?, ?, ?, ?)",
		("outbox", 1, "telegram", "user123", row["payload"], "send failed; gave up after 3 attempts (25.0h old)"),
	)


# ── Regression: real sqlite3.Row + per-message containment ───────────────────
# El outbox se lee con row_factory=sqlite3.Row (no dicts). El bug `row.get(...)`
# reventaba el bucle con un AttributeError y BLOQUEABA todos los mensajes
# siguientes. Estos tests usan Rows reales y verifican el aislamiento.


def _real_conn(tmp_path):
	import sqlite3

	conn = sqlite3.connect(str(tmp_path / "events.db"))
	conn.row_factory = sqlite3.Row
	conn.executescript(
		"""
		CREATE TABLE outbox (id INTEGER PRIMARY KEY AUTOINCREMENT, message_id TEXT,
			channel TEXT, channel_user_id TEXT, payload TEXT,
			status TEXT DEFAULT 'PENDING', retries INTEGER DEFAULT 0, next_attempt_at REAL,
			created_at TEXT DEFAULT CURRENT_TIMESTAMP);
		CREATE TABLE dead_letters (id INTEGER PRIMARY KEY AUTOINCREMENT, original_table TEXT,
			original_id INTEGER, channel TEXT, channel_user_id TEXT, payload TEXT, error_reason TEXT);
		"""
	)
	conn.commit()
	return conn


@patch("neon_link.core.manager.get_connection")
def test_poll_uses_real_sqlite_row(mock_get_conn, manager_setup, tmp_path):
	"""Un Row real (retries entero) NO debe romper con AttributeError."""
	conn = _real_conn(tmp_path)
	conn.execute("INSERT INTO outbox (channel, channel_user_id, payload) VALUES ('telegram','user123',?)", ('{"text":"Hello"}',))
	conn.commit()
	mock_get_conn.return_value = conn

	plugin = MagicMock()
	plugin.name = "telegram"
	manager_setup.register(plugin)
	manager_setup.pipeline.process_egress = AsyncMock(return_value=False)
	manager_setup._resolve_session = MagicMock(return_value="user123")
	manager_setup.running = True

	with patch("time.sleep", side_effect=lambda *a: setattr(manager_setup, "running", False)):
		manager_setup._poll_outbox_loop()

	import sqlite3 as _s

	check = _s.connect(str(tmp_path / "events.db"))
	check.row_factory = _s.Row
	# retries debe haber subido a 1 (no crash, no dead-letter todavía) y con backoff
	retries, next_at = check.execute("SELECT retries, next_attempt_at FROM outbox WHERE id=1").fetchone()
	assert retries == 1
	assert next_at > time.time()
	check.close()


@patch("neon_link.core.manager.get_connection")
def test_bad_message_does_not_block_following(mock_get_conn, manager_setup, tmp_path):
	"""Un mensaje con payload corrupto se aísla (FAILED + dead_letter) y NO
	impide que el siguiente se entregue."""
	conn = _real_conn(tmp_path)
	conn.execute("INSERT INTO outbox (channel, channel_user_id, payload, created_at) VALUES ('telegram','bad',?, '2026-01-01')", ("{NOT JSON",))
	conn.execute(
		"INSERT INTO outbox (channel, channel_user_id, payload, created_at) VALUES ('telegram','good',?, '2026-01-02')", ('{"text":"Hola"}',)
	)
	conn.commit()
	mock_get_conn.return_value = conn

	plugin = MagicMock()
	plugin.name = "telegram"
	manager_setup.register(plugin)
	manager_setup.pipeline.process_egress = AsyncMock(return_value=True)
	manager_setup._resolve_session = MagicMock(return_value="user123")
	manager_setup.running = True

	with patch("time.sleep", side_effect=lambda *a: setattr(manager_setup, "running", False)):
		manager_setup._poll_outbox_loop()

	import sqlite3 as _s

	check = _s.connect(str(tmp_path / "events.db"))
	check.row_factory = _s.Row
	statuses = {r["id"]: r["status"] for r in check.execute("SELECT id, status FROM outbox")}
	assert statuses[1] == "FAILED", "el mensaje corrupto debe dead-letterizarse"
	assert statuses[2] == "SENT", "el mensaje bueno debe entregarse pese al corrupto anterior"
	assert check.execute("SELECT COUNT(*) FROM dead_letters").fetchone()[0] == 1
	check.close()


# ── Retry policy: time-based backoff, permanent vs transient, redrive ───────


def _run_once(manager, conn, mock_get_conn, polls=1):
	"""Run the poll loop `polls` times against a real DB (fresh conn each poll)."""
	import sqlite3

	path = conn.execute("PRAGMA database_list").fetchone()[2]

	def _conn():
		c = sqlite3.connect(path)
		c.row_factory = sqlite3.Row
		return c

	mock_get_conn.side_effect = _conn
	remaining = {"n": polls}

	def _sleep(*_):
		remaining["n"] -= 1
		if remaining["n"] <= 0:
			manager.running = False

	manager.running = True
	with patch("time.sleep", side_effect=_sleep):
		manager._poll_outbox_loop()


def _telegram(manager):
	plugin = MagicMock()
	plugin.name = "telegram"
	manager.register(plugin)
	manager._resolve_session = MagicMock(return_value="user123")
	return plugin


def _status(tmp_path):
	import sqlite3

	c = sqlite3.connect(str(tmp_path / "events.db"))
	c.row_factory = sqlite3.Row
	try:
		row = c.execute("SELECT status, retries, next_attempt_at FROM outbox WHERE id=1").fetchone()
		dead = c.execute("SELECT COUNT(*) FROM dead_letters").fetchone()[0]
		return dict(row), dead
	finally:
		c.close()


@patch("neon_link.core.manager.get_connection")
def test_transient_failure_backs_off_instead_of_hammering(mock_get_conn, manager_setup, tmp_path):
	"""Un corte de red corto ya no pierde el mensaje: 3 polls seguidos = 1 intento."""
	conn = _real_conn(tmp_path)
	conn.execute("INSERT INTO outbox (channel, channel_user_id, payload) VALUES ('telegram','u',?)", ('{"text":"hola"}',))
	conn.commit()
	_telegram(manager_setup)
	manager_setup.pipeline.process_egress = AsyncMock(return_value=False)

	_run_once(manager_setup, conn, mock_get_conn, polls=3)

	assert manager_setup.pipeline.process_egress.await_count == 1
	row, dead = _status(tmp_path)
	assert row["status"] == "PENDING" and row["retries"] == 1 and dead == 0


@patch("neon_link.core.manager.get_connection")
def test_transient_exception_is_retried_not_dead_lettered(mock_get_conn, manager_setup, tmp_path):
	conn = _real_conn(tmp_path)
	conn.execute("INSERT INTO outbox (channel, channel_user_id, payload) VALUES ('telegram','u',?)", ('{"text":"hola"}',))
	conn.commit()
	_telegram(manager_setup)
	manager_setup.pipeline.process_egress = AsyncMock(side_effect=ConnectionError("network down"))

	_run_once(manager_setup, conn, mock_get_conn)

	row, dead = _status(tmp_path)
	assert row["status"] == "PENDING" and row["retries"] == 1 and dead == 0


@patch("neon_link.core.manager.get_connection")
def test_permanent_error_dead_letters_immediately(mock_get_conn, manager_setup, tmp_path):
	from neon_link.plugins.base import PermanentEgressError

	conn = _real_conn(tmp_path)
	conn.execute("INSERT INTO outbox (channel, channel_user_id, payload) VALUES ('telegram','u',?)", ('{"text":"hola"}',))
	conn.commit()
	_telegram(manager_setup)
	manager_setup.pipeline.process_egress = AsyncMock(side_effect=PermanentEgressError("chat not found"))

	_run_once(manager_setup, conn, mock_get_conn)

	row, dead = _status(tmp_path)
	assert row["status"] == "FAILED" and dead == 1


@patch("neon_link.core.manager.get_connection")
def test_unknown_channel_waits_for_its_plugin(mock_get_conn, manager_setup, tmp_path):
	"""Canal sin plugin en este proceso: backoff (un reinicio con el plugin lo entrega)."""
	conn = _real_conn(tmp_path)
	conn.execute("INSERT INTO outbox (channel, channel_user_id, payload) VALUES ('rings','u',?)", ('{"text":"hola"}',))
	conn.commit()

	_run_once(manager_setup, conn, mock_get_conn)

	row, dead = _status(tmp_path)
	assert row["status"] == "PENDING" and row["retries"] == 1 and dead == 0


@patch("neon_link.core.manager.get_connection")
def test_aged_out_message_is_dead_lettered_and_redrive_requeues(mock_get_conn, manager_setup, tmp_path):
	import sqlite3

	from neon_link.core.manager import redrive_outbox_dead_letters

	conn = _real_conn(tmp_path)
	conn.execute(
		"INSERT INTO outbox (channel, channel_user_id, payload, created_at) VALUES ('telegram','u',?, datetime('now','-2 days'))",
		('{"text":"hola"}',),
	)
	conn.commit()
	_telegram(manager_setup)
	manager_setup.pipeline.process_egress = AsyncMock(return_value=False)

	_run_once(manager_setup, conn, mock_get_conn)
	row, dead = _status(tmp_path)
	assert row["status"] == "FAILED" and dead == 1

	c = sqlite3.connect(str(tmp_path / "events.db"))
	assert redrive_outbox_dead_letters(c) == 1
	c.close()
	row, dead = _status(tmp_path)
	assert row["status"] == "PENDING" and row["retries"] == 0 and row["next_attempt_at"] is None and dead == 0

