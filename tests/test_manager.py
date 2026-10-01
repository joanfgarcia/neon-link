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
	mock_conn = MagicMock()
	mock_cursor = MagicMock()
	mock_conn.cursor.return_value = mock_cursor
	mock_get_conn.return_value = mock_conn

	import json

	row = {"id": 1, "channel": "telegram", "channel_user_id": "user123", "payload": json.dumps({"text": "Hello"}), "retries": 2}
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
		("outbox", 1, "telegram", "user123", row["payload"], "Failed after 3 retries"),
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
			status TEXT DEFAULT 'PENDING', retries INTEGER DEFAULT 0, created_at TEXT);
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
	conn.execute(
		"INSERT INTO outbox (channel, channel_user_id, payload, created_at) VALUES ('telegram','user123',?, '2026-01-01')", ('{"text":"Hello"}',)
	)
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
	# retries debe haber subido a 1 (no crash, no dead-letter todavía)
	assert check.execute("SELECT retries FROM outbox WHERE id=1").fetchone()[0] == 1
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
