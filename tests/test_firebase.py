import pytest
from unittest.mock import MagicMock, patch
from neon_link.plugins.firebase import FirebaseHub
from neon_link.models.network import NetworkEvent

@patch("neon_link.plugins.firebase.firebase_admin")
@patch("neon_link.plugins.firebase.credentials")
def test_firebase_hub_init(mock_cred, mock_admin):
	mock_admin.get_app.side_effect = ValueError("App does not exist")
	identity = MagicMock()
	hub = FirebaseHub(identity)
	assert hub.name == "firebase"
	mock_admin.initialize_app.assert_called()

@pytest.mark.asyncio
@patch("neon_link.plugins.firebase.db")
@patch("neon_link.plugins.firebase.firebase_admin")
@patch("neon_link.plugins.firebase.credentials")
async def test_firebase_send_event(mock_cred, mock_admin, mock_db):
	identity = MagicMock()
	hub = FirebaseHub(identity)
	hub.app = MagicMock()
	
	event = NetworkEvent(type="welcome", recipient_id="bob", payload=b"hello")
	res = await hub.send_event(event)
	
	assert res is True
	mock_db.reference.assert_called()
	
@pytest.mark.asyncio
@patch("neon_link.plugins.firebase.db")
@patch("neon_link.plugins.firebase.firebase_admin")
@patch("neon_link.plugins.firebase.credentials")
async def test_firebase_fetch_key(mock_cred, mock_admin, mock_db):
	identity = MagicMock()
	hub = FirebaseHub(identity)
	hub.app = MagicMock()
	
	mock_ref = MagicMock()
	mock_ref.get.return_value = {"key_package": "deadbeef"}
	mock_db.reference.return_value = mock_ref
	
	res = await hub.fetch_key_package("bob")
	assert res == bytes.fromhex("deadbeef")

def test_firebase_register_callback():
	from unittest.mock import MagicMock
	import neon_link.plugins.firebase as fb
	with patch("neon_link.plugins.firebase.firebase_admin"), patch("neon_link.plugins.firebase.credentials"):
		fb.firebase_admin.get_app.side_effect = ValueError("App does not exist")
		hub = FirebaseHub(MagicMock())
		cb = MagicMock()
		hub.register_callback(cb)
		assert hub._on_event_callback == cb

@patch("neon_link.plugins.firebase.db")
@patch("neon_link.plugins.firebase.firebase_admin")
@patch("neon_link.plugins.firebase.credentials")
def test_firebase_poll(mock_cred, mock_admin, mock_db):
	mock_admin.get_app.side_effect = ValueError("App does not exist")
	identity = MagicMock()
	hub = FirebaseHub(identity)
	hub.app = MagicMock()
	hub.running = True
	
	from unittest.mock import AsyncMock
	hub.register_callback(AsyncMock())
	
	mock_ref = MagicMock()
	mock_ref.get.return_value = {
		"msg1": {"payload": b"hello".hex(), "sender_id": "alice"}
	}
	mock_db.reference.return_value = mock_ref
	
	def stop_loop(*args):
		hub.running = False
		
	with patch("time.sleep", side_effect=stop_loop):
		hub._poll_firebase()
	
	hub._on_event_callback.assert_called()
	mock_ref.child.assert_called_with("msg1")
	mock_ref.child().delete.assert_called()

@pytest.mark.asyncio
async def test_fetch_key_package_no_app():
	hub = FirebaseHub(MagicMock())
	hub.app = None
	assert await hub.fetch_key_package("agent") is None

def test_publish_key_package():
	hub = FirebaseHub(MagicMock())
	hub.app = None
	hub.publish_my_key_package(b"test") # shouldn't crash
	
@pytest.mark.asyncio
@patch("neon_link.plugins.firebase.threading.Thread")
async def test_firebase_threads(mock_thread):
	hub = FirebaseHub(MagicMock())
	await hub.start()
	mock_thread.assert_called()
	
	mock_thread_instance = MagicMock()
	hub.t1 = mock_thread_instance
	await hub.stop()
	mock_thread_instance.join.assert_called()

@pytest.mark.asyncio
async def test_firebase_send_event_no_app():
	hub = FirebaseHub(MagicMock())
	hub.app = None
	event = MagicMock()
	assert await hub.send_event(event) is False

def test_firebase_init_error():
	with patch("neon_link.plugins.firebase.credentials") as m_cred:
		m_cred.Certificate.side_effect = Exception("error")
		import neon_link.plugins.firebase as fb
		with patch("neon_link.plugins.firebase.firebase_admin") as m_admin:
			m_admin.get_app.side_effect = ValueError()
			hub = FirebaseHub(MagicMock())

@pytest.mark.asyncio
async def test_firebase_send_event_error():
	hub = FirebaseHub(MagicMock())
	hub.app = MagicMock()
	with patch("neon_link.plugins.firebase.db.reference", side_effect=Exception("error")):
		await hub.send_event(MagicMock())

def test_publish_key_package_error():
	hub = FirebaseHub(MagicMock())
	hub.app = MagicMock()
	with patch("neon_link.plugins.firebase.db.reference", side_effect=Exception("error")):
		hub.publish_my_key_package(b"test")
