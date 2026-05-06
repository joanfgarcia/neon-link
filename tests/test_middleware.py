import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pure_mls.keys import KemKey, SignatureKey
from pure_mls.tree import KeyPackage

from neon_link.core.middleware import CryptoPipeline
from neon_link.models.network import NetworkEvent


@pytest.fixture
def identity_manager_mock():
	mgr = MagicMock()
	kem_key = KemKey.from_private_bytes(os.urandom(32))
	sig_key = SignatureKey.from_private_bytes(os.urandom(32))
	mgr.get_identities.return_value = {"neon_link": (kem_key, sig_key)}
	return mgr


@pytest.fixture
def plugin_mock():
	plugin = MagicMock()
	plugin.name = "firebase"
	return plugin


@pytest.mark.asyncio
async def test_process_egress_auto_create_group(identity_manager_mock, plugin_mock):
	pipeline = CryptoPipeline(identity_manager_mock, "test_agent")

	# Mock SQLite state
	pipeline._get_group_state = MagicMock(return_value=None)
	pipeline._save_group_state = MagicMock()

	# Remote agent's key package
	remote_kem = KemKey.from_private_bytes(os.urandom(32))
	remote_sig = SignatureKey.from_private_bytes(os.urandom(32))
	remote_kp = KeyPackage.create(
		encryption_key=remote_kem.public_bytes(),
		init_key_pub=remote_kem.public_bytes(),
		signature_key=remote_sig.public_bytes(),
		identity=b"remote_agent",
		sign_fn=remote_sig.sign,
	)
	plugin_mock.fetch_key_package = AsyncMock(return_value=remote_kp.to_bytes())
	plugin_mock.send_event = AsyncMock(return_value=True)

	success = await pipeline.process_egress(plugin_mock, "remote_agent", "Hello Crypto!")

	assert success is True
	# Should send two events: one welcome, one application
	assert plugin_mock.send_event.call_count == 2


@pytest.mark.asyncio
async def test_process_egress_non_firebase(identity_manager_mock, plugin_mock):
	pipeline = CryptoPipeline(identity_manager_mock, "test_agent")
	plugin_mock.name = "telegram"
	plugin_mock.send_event = AsyncMock(return_value=True)

	success = await pipeline.process_egress(plugin_mock, "remote_agent", "Hello Plaintext!")
	assert success is True

	# Sends application plaintext directly
	args, _ = plugin_mock.send_event.call_args
	event = args[0]
	assert event.type == "application"
	assert event.payload == b"Hello Plaintext!"


@pytest.mark.asyncio
@patch("neon_link.core.middleware.get_connection")
async def test_process_ingress_plaintext(mock_get_connection, identity_manager_mock, plugin_mock):
	pipeline = CryptoPipeline(identity_manager_mock, "test_agent")
	plugin_mock.name = "telegram"

	mock_conn = MagicMock()
	mock_get_connection.return_value = mock_conn

	event = NetworkEvent(type="application", recipient_id="test_agent", payload=b"Plaintext data")
	await pipeline.process_ingress(plugin_mock, "sender123", event)

	# Verify enqueue
	mock_conn.execute.assert_called_once()
	sql, params = mock_conn.execute.call_args[0]
	assert "INSERT INTO inbox" in sql
	assert "Plaintext data" in params[2]


@pytest.mark.asyncio
@patch("neon_link.core.middleware.get_connection")
async def test_process_ingress_encrypted(mock_get_connection, identity_manager_mock, plugin_mock):
	pipeline = CryptoPipeline(identity_manager_mock, "test_agent")
	plugin_mock.name = "firebase"

	pipeline._get_group_state = MagicMock(return_value=MagicMock())

	# mock group to return a message
	group = pipeline._get_group_state.return_value
	group.decrypt_application_message.return_value = b"Decrypted data"
	group.to_bytes.return_value = b"serialized"
	group.serialize.return_value = b"serialized"

	event = NetworkEvent(type="application", recipient_id="test_agent", payload=b"Encrypted data")

	mock_conn = MagicMock()
	mock_get_connection.return_value = mock_conn

	await pipeline.process_ingress(plugin_mock, "sender123", event)

	mock_conn.execute.assert_called()
	inbox_call = next(call for call in mock_conn.execute.call_args_list if "INSERT INTO inbox" in call[0][0])
	assert "Decrypted data" in inbox_call[0][1][2]


@patch("neon_link.core.middleware.get_connection")
def test_get_group_state_none(mock_get_conn, identity_manager_mock):
	mock_cursor = MagicMock()
	mock_cursor.fetchone.return_value = None
	mock_get_conn.return_value.cursor.return_value = mock_cursor
	pipeline = CryptoPipeline(identity_manager_mock, "test_agent")
	assert pipeline._get_group_state("group1") is None


def test_get_public_key_package(identity_manager_mock):
	pipeline = CryptoPipeline(identity_manager_mock, "test_agent")
	kp = pipeline.get_public_key_package()
	assert isinstance(kp, bytes)


def test_pipeline_init_no_identities():
	identity_manager_mock = MagicMock()
	identity_manager_mock.get_identities.return_value = {}
	with pytest.raises(ValueError):
		CryptoPipeline(identity_manager_mock, "test_agent")


@pytest.mark.asyncio
@patch("neon_link.core.middleware.get_connection")
async def test_process_egress_firebase_no_key(mock_get_conn, identity_manager_mock, plugin_mock):
	mock_conn = MagicMock()
	mock_get_conn.return_value = mock_conn
	pipeline = CryptoPipeline(identity_manager_mock, "test_agent")
	plugin_mock.name = "firebase"
	plugin_mock.fetch_key_package = AsyncMock(return_value=None)
	plugin_mock.send_event = AsyncMock(return_value=True)
	pipeline._get_group_state = MagicMock(return_value=None)
	res = await pipeline.process_egress(plugin_mock, "user1", "payload")
	assert res is True


@pytest.mark.asyncio
@patch("neon_link.core.middleware.get_connection")
async def test_process_ingress_welcome(mock_get_conn, identity_manager_mock, plugin_mock):
	mock_conn = MagicMock()
	mock_get_conn.return_value = mock_conn
	pipeline = CryptoPipeline(identity_manager_mock, "test_agent")
	plugin_mock.name = "firebase"
	event = NetworkEvent(type="welcome", recipient_id="test", payload=b"welcome")
	with patch("neon_link.core.middleware.MLSMessage") as mock_msg, patch("neon_link.core.middleware.MLSGroup") as mock_group:
		mock_msg.from_bytes.return_value.unwrap_welcome.return_value = MagicMock()
		await pipeline.process_ingress(plugin_mock, "sender", event)
		mock_group.join.assert_called()


@pytest.mark.asyncio
@patch("neon_link.core.middleware.get_connection")
async def test_process_ingress_update(mock_get_conn, identity_manager_mock, plugin_mock):
	mock_conn = MagicMock()
	mock_get_conn.return_value = mock_conn
	pipeline = CryptoPipeline(identity_manager_mock, "test_agent")
	plugin_mock.name = "firebase"
	event = NetworkEvent(type="update", recipient_id="test", payload=b"update")
	pipeline._get_group_state = MagicMock(return_value=MagicMock())
	with patch("neon_link.core.middleware.MLSMessage"):
		await pipeline.process_ingress(plugin_mock, "sender", event)


@pytest.mark.asyncio
async def test_process_ingress_app_unknown_group(identity_manager_mock, plugin_mock):
	pipeline = CryptoPipeline(identity_manager_mock, "test_agent")
	plugin_mock.name = "firebase"
	event = NetworkEvent(type="application", recipient_id="test", payload=b"app")
	pipeline._get_group_state = MagicMock(return_value=None)
	await pipeline.process_ingress(plugin_mock, "sender", event)


@pytest.mark.asyncio
async def test_process_egress_error(identity_manager_mock, plugin_mock):
	pipeline = CryptoPipeline(identity_manager_mock, "test_agent")
	plugin_mock.name = "firebase"
	group = MagicMock()
	group.encrypt_application_message.side_effect = Exception("err")
	pipeline._get_group_state = MagicMock(return_value=group)
	assert await pipeline.process_egress(plugin_mock, "user1", "payload") is False


@pytest.mark.asyncio
async def test_process_ingress_welcome_error(identity_manager_mock, plugin_mock):
	pipeline = CryptoPipeline(identity_manager_mock, "test_agent")
	plugin_mock.name = "firebase"
	event = NetworkEvent(type="welcome", recipient_id="test", payload=b"welcome")
	with patch("neon_link.core.middleware.MLSMessage", side_effect=Exception("err")):
		await pipeline.process_ingress(plugin_mock, "sender", event)


@pytest.mark.asyncio
async def test_process_ingress_update_error(identity_manager_mock, plugin_mock):
	pipeline = CryptoPipeline(identity_manager_mock, "test_agent")
	plugin_mock.name = "firebase"
	event = NetworkEvent(type="update", recipient_id="test", payload=b"update")
	pipeline._get_group_state = MagicMock(return_value=MagicMock())
	with patch("neon_link.core.middleware.MLSMessage", side_effect=Exception("err")):
		await pipeline.process_ingress(plugin_mock, "sender", event)


@pytest.mark.asyncio
async def test_process_ingress_app_error(identity_manager_mock, plugin_mock):
	pipeline = CryptoPipeline(identity_manager_mock, "test_agent")
	plugin_mock.name = "firebase"
	event = NetworkEvent(type="application", recipient_id="test", payload=b"app")
	group = MagicMock()
	group.decrypt_application_message.side_effect = Exception("err")
	pipeline._get_group_state = MagicMock(return_value=group)
	await pipeline.process_ingress(plugin_mock, "sender", event)
