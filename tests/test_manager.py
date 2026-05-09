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
