import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from neon_link.models.network import NetworkEvent
from neon_link.plugins.rings import RingsHub


def test_rings_hub_init():
	identity = MagicMock()
	identity.get_identities.return_value = {}
	hub = RingsHub(identity, endpoint_url="ws://127.0.0.1:9999", agent_id="test_agent")
	assert hub.name == "rings"
	assert hub.endpoint_url == "ws://127.0.0.1:9999"
	assert hub.agent_id == "test_agent"


def _create_mock_client():
	mock_client = MagicMock()
	mock_client.connect = AsyncMock()
	mock_client.disconnect = AsyncMock()
	mock_client.register = AsyncMock()
	mock_client.send_message = AsyncMock(return_value={"ok": True, "delivered": True})
	mock_client.dht_get = AsyncMock(return_value="aabbcc")
	mock_client.dht_put = AsyncMock()
	return mock_client


@pytest.mark.asyncio
@patch("neon_link.plugins.rings.RingsClient")
async def test_rings_hub_start_stop(mock_client_class):
	mock_client = _create_mock_client()
	mock_client_class.return_value = mock_client

	identity = MagicMock()
	identity.get_identities.return_value = {}
	hub = RingsHub(identity, endpoint_url="ws://127.0.0.1:9999", agent_id="test_agent")

	await hub.start()
	assert hub.running is True
	mock_client.connect.assert_called_once()
	mock_client.register.assert_called_once_with("test_agent")
	mock_client.set_message_handler.assert_called_once_with(hub._handle_message)

	await hub.stop()
	assert hub.running is False
	mock_client.disconnect.assert_called_once()


@pytest.mark.asyncio
@patch("neon_link.plugins.rings.RingsClient")
async def test_rings_send_event(mock_client_class):
	mock_client = _create_mock_client()
	mock_client_class.return_value = mock_client

	identity = MagicMock()
	identity.get_identities.return_value = {}
	hub = RingsHub(identity, endpoint_url="ws://127.0.0.1:9999", agent_id="test_agent")

	await hub.start()
	event = NetworkEvent(type="application", recipient_id="bob", payload=b"hello")
	success = await hub.send_event(event)

	assert success is True
	mock_client.send_message.assert_called_once_with(
		target_id="bob", payload={"type": "application", "recipient_id": "bob", "payload_hex": b"hello".hex()}
	)


@pytest.mark.asyncio
@patch("neon_link.plugins.rings.RingsClient")
async def test_rings_fetch_key_package(mock_client_class):
	mock_client = _create_mock_client()
	mock_client_class.return_value = mock_client

	identity = MagicMock()
	identity.get_identities.return_value = {}
	hub = RingsHub(identity, endpoint_url="ws://127.0.0.1:9999", agent_id="test_agent")

	await hub.start()

	# Query with invalid key (non-hex or wrong length)
	kp = await hub.fetch_key_package("not_a_key")
	assert kp is None
	mock_client.dht_get.assert_not_called()

	# Query with valid 32-byte hex public key
	hex_key = "a" * 64
	kp = await hub.fetch_key_package(hex_key)
	assert kp == bytes.fromhex("aabbcc")
	mock_client.dht_get.assert_called_once_with(hex_key)


@pytest.mark.asyncio
@patch("neon_link.plugins.rings.RingsClient")
async def test_rings_publish_key_package(mock_client_class):
	mock_client = _create_mock_client()
	mock_client_class.return_value = mock_client

	identity = MagicMock()
	identity.get_identities.return_value = {}
	hub = RingsHub(identity, endpoint_url="ws://127.0.0.1:9999", agent_id="test_agent")

	await hub.start()

	hub.publish_my_key_package(b"mypackage")
	# Allow async task to run
	await asyncio.sleep(0.01)
	mock_client.dht_put.assert_called_once_with(hub.keypair, b"mypackage".hex())


@pytest.mark.asyncio
@patch("neon_link.plugins.rings.RingsClient")
async def test_rings_handle_message(mock_client_class):
	mock_client = _create_mock_client()
	mock_client_class.return_value = mock_client

	identity = MagicMock()
	identity.get_identities.return_value = {}
	hub = RingsHub(identity, endpoint_url="ws://127.0.0.1:9999", agent_id="test_agent")

	cb = AsyncMock()
	hub.register_callback(cb)

	await hub.start()

	# Simulate incoming P2P message
	payload = {"type": "application", "recipient_id": "test_agent", "payload_hex": b"hello_p2p".hex()}
	await hub._handle_message("alice", payload)

	cb.assert_called_once()
	args, _ = cb.call_args
	event = args[2]
	assert event.type == "application"
	assert event.recipient_id == "test_agent"
	assert event.payload == b"hello_p2p"
