import asyncio
import json
from unittest.mock import MagicMock

import pytest

from neon_link.models.network import NetworkEvent
from neon_link.plugins.base import PermanentEgressError
from neon_link.plugins.soul import SoulHub


def _envelope(event_id="e" * 32, soul="soul-1"):
	return {
		"v": 1,
		"event_id": event_id,
		"mission_id": "repo:sharing",
		"continuity_id": soul,
		"verb": "notify",
		"thread_id": "E-test",
	}


def _event(envelope=None):
	payload = json.dumps(envelope or _envelope()).encode("utf-8")
	return NetworkEvent(type="application", recipient_id="soul-1", payload=payload)


def _fake_redpill(tmp_path, mode: str) -> str:
	"""CLI falso: imprime el informe que el plugin debe interpretar."""
	script = tmp_path / "redpill-fake"
	script.write_text(
		"""#!/usr/bin/env python3
import json, os, sys, time
mode = os.environ.get("SOUL_TEST_MODE", "sent")
if mode == "sleep":
    time.sleep(5)
if mode == "fail":
    print("boom", file=sys.stderr)
    sys.exit(1)
if mode == "retry":
    print(json.dumps({"continuity_id": "soul-1", "deferred": [{"reason": "no_live_body"}]}))
elif mode == "dead":
    print(json.dumps({"continuity_id": "soul-1", "given_up": [{"reason": "expired"}]}))
elif mode == "empty":
    print("{}")
else:
    print(json.dumps({"continuity_id": "soul-1", "handed_off": [{"event_id": "e"}]}))
""",
		encoding="utf-8",
	)
	script.chmod(0o755)
	return str(script)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,expected", [("sent", True), ("retry", False), ("empty", True)])
async def test_send_event_maps_report(tmp_path, monkeypatch, mode, expected):
	monkeypatch.setenv("SOUL_TEST_MODE", mode)
	hub = SoulHub(MagicMock(), redpill_cmd=_fake_redpill(tmp_path, mode), timeout_s=5)
	assert await hub.send_event(_event()) is expected


@pytest.mark.asyncio
async def test_send_event_dead_is_permanent(tmp_path, monkeypatch):
	monkeypatch.setenv("SOUL_TEST_MODE", "dead")
	hub = SoulHub(MagicMock(), redpill_cmd=_fake_redpill(tmp_path, "dead"), timeout_s=5)
	with pytest.raises(PermanentEgressError):
		await hub.send_event(_event())


@pytest.mark.asyncio
async def test_send_event_child_failure_retries(tmp_path, monkeypatch):
	monkeypatch.setenv("SOUL_TEST_MODE", "fail")
	hub = SoulHub(MagicMock(), redpill_cmd=_fake_redpill(tmp_path, "fail"), timeout_s=5)
	assert await hub.send_event(_event()) is False


@pytest.mark.asyncio
async def test_send_event_timeout_retries(tmp_path, monkeypatch):
	monkeypatch.setenv("SOUL_TEST_MODE", "sleep")
	hub = SoulHub(MagicMock(), redpill_cmd=_fake_redpill(tmp_path, "sleep"), timeout_s=0.2)
	assert await hub.send_event(_event()) is False


@pytest.mark.asyncio
async def test_corrupt_envelope_is_permanent():
	hub = SoulHub(MagicMock())
	event = NetworkEvent(type="application", recipient_id="soul-1", payload=b"not json")
	with pytest.raises(PermanentEgressError):
		await hub.send_event(event)


@pytest.mark.asyncio
async def test_missing_fields_is_permanent():
	hub = SoulHub(MagicMock())
	event = NetworkEvent(type="application", recipient_id="soul-1", payload=json.dumps({"v": 1}).encode())
	with pytest.raises(PermanentEgressError):
		await hub.send_event(event)


@pytest.mark.parametrize(
	"mode,expected_status,dead_letters",
	[("sent", "SENT", 0), ("retry", "PENDING", 0), ("dead", "FAILED", 1)],
)
def test_manager_outbox_status(tmp_path, monkeypatch, mode, expected_status, dead_letters):
	"""Integración real manager→plugin→CLI falso→outbox."""
	import sqlite3

	from neon_link import db as neon_db
	from neon_link.core.manager import PluginManager

	db_path = tmp_path / f"events-{mode}.db"
	neon_db.set_db_path(str(db_path))
	neon_db.init_db()
	conn = sqlite3.connect(str(db_path))
	conn.row_factory = sqlite3.Row
	conn.execute(
		"INSERT INTO outbox (message_id, channel, channel_user_id, payload) VALUES (?, ?, ?, ?)",
		("e" * 32, "soul", "soul-1", json.dumps(_envelope())),
	)
	conn.commit()
	row = conn.execute("SELECT *, 0.0 AS age_s FROM outbox WHERE id = 1").fetchone()

	identity = MagicMock()
	identity.get_identities.return_value = {"neon_link": ("kem", "sig")}
	manager = PluginManager(MagicMock(), identity, "test_agent")
	monkeypatch.setenv("SOUL_TEST_MODE", mode)
	hub = SoulHub(identity, redpill_cmd=_fake_redpill(tmp_path, mode), timeout_s=5)
	manager.register(hub)
	manager._resolve_session = lambda sid: sid
	manager._process_outbox_row_contained(asyncio.new_event_loop(), conn.cursor(), row)
	conn.commit()

	status = conn.execute("SELECT status FROM outbox WHERE id = 1").fetchone()[0]
	assert status == expected_status
	letters = conn.execute("SELECT COUNT(*) FROM dead_letters").fetchone()[0]
	assert letters == dead_letters
	conn.close()


def test_manager_passes_raw_payload_for_soul():
	"""El manager debe pasar el sobre completo, no el campo `text`."""
	from neon_link.core.manager import PluginManager

	identity = MagicMock()
	identity.get_identities.return_value = {"neon_link": ("kem", "sig")}
	manager = PluginManager(MagicMock(), identity, "test_agent")
	plugin = MagicMock()
	plugin.name = "soul"
	plugin.raw_payload = True
	manager.plugins["soul"] = plugin
	manager._resolve_session = lambda sid: sid
	captured = {}

	async def fake_egress(plugin_arg, recipient, text):
		captured["recipient"] = recipient
		captured["text"] = text
		return True

	manager.pipeline.process_egress = fake_egress
	row = {
		"id": 1,
		"channel": "soul",
		"channel_user_id": "soul-1",
		"payload": json.dumps(_envelope()),
		"retries": 0,
		"age_s": 0.0,
	}
	manager._process_outbox_row(asyncio.new_event_loop(), MagicMock(), row)
	assert captured["recipient"] == "soul-1"
	assert json.loads(captured["text"])["event_id"] == "e" * 32


def test_reconcile_once_invoca_el_cli(tmp_path):
	script = tmp_path / "redpill-reconcile"
	args_file = tmp_path / "args.txt"
	script.write_text(
		"#!/usr/bin/env python3\n"
		"import json, pathlib, sys\n"
		f"pathlib.Path({str(args_file)!r}).write_text(' '.join(sys.argv[1:]))\n"
		"print(json.dumps({'published': 1, 'failed': 0, 'scanned': 1}))\n",
		encoding="utf-8",
	)
	script.chmod(0o755)
	hub = SoulHub(MagicMock(), redpill_cmd=str(script), timeout_s=5)
	hub._reconcile_once()
	assert "coro reconcile" in args_file.read_text()


def test_egress_soul_tiene_hilo_propio(tmp_path, monkeypatch):
	"""El poller principal excluye soul; el plugin lo procesa en su hilo."""
	import sqlite3
	import threading

	from neon_link import db as neon_db

	db_path = tmp_path / "events.db"
	neon_db.set_db_path(str(db_path))
	neon_db.init_db()
	con = sqlite3.connect(str(db_path))
	con.execute(
		"INSERT INTO outbox (message_id, channel, channel_user_id, payload) VALUES (?, ?, ?, ?)",
		("e" * 32, "soul", "soul-1", json.dumps(_envelope())),
	)
	con.commit()
	con.close()

	called = threading.Event()

	class FakeManager:
		def _process_outbox_row_contained(self, loop, cursor, row):
			called.set()

	monkeypatch.setenv("NEON_LINK_SOUL_RECONCILE_S", "0")
	hub = SoulHub(MagicMock(), manager=FakeManager(), redpill_cmd="true", timeout_s=1)
	asyncio.run(hub.start())
	try:
		assert called.wait(timeout=3.0), "el hilo de egress soul no procesó la fila"
	finally:
		asyncio.run(hub.stop())
