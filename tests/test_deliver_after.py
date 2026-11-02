"""Entrega diferida del outbox (RFC-OBS-006 F2).

Un mensaje con `deliver_after` no se intenta antes de su fecha y, cuando llega,
su edad para el dead-letter se cuenta desde esa fecha — no desde que se escribió.
Si se contara desde `created_at`, un mensaje programado a 14 días moriría en el
primer fallo por "viejo" (24 h de `EGRESS_MAX_AGE_S`).
"""

import sqlite3
import time

import pytest

from neon_link import db as neon_db
from neon_link.core.manager import due_outbox_rows


@pytest.fixture
def conn():
	neon_db.init_db()
	connection = neon_db.get_connection()
	connection.row_factory = sqlite3.Row
	# La DB de la suite es compartida entre tests: cada caso empieza limpio.
	for table in ("outbox", "dead_letters"):
		with __import__("contextlib").suppress(sqlite3.OperationalError):
			connection.execute(f"DELETE FROM {table}")
	connection.commit()
	yield connection
	connection.close()


def _insert(conn, channel="telegram", deliver_after=None, next_attempt_at=None, created_at=None, user="u1"):
	conn.execute(
		"INSERT INTO outbox (channel, channel_user_id, payload, deliver_after, next_attempt_at, created_at)"
		" VALUES (?, ?, '{}', ?, ?, ?)",
		(channel, user, deliver_after, next_attempt_at, created_at),
	)
	conn.commit()


class TestVentana:
	def test_no_aparece_antes_de_su_fecha(self, conn):
		now = time.time()
		_insert(conn, deliver_after=now + 3600)
		assert due_outbox_rows(conn.cursor(), now) == []

	def test_aparece_al_vencer(self, conn):
		now = time.time()
		_insert(conn, deliver_after=now + 3600)
		assert len(due_outbox_rows(conn.cursor(), now + 3601)) == 1

	def test_sin_fecha_sale_ya(self, conn):
		now = time.time()
		_insert(conn, deliver_after=None)
		assert len(due_outbox_rows(conn.cursor(), now)) == 1

	def test_el_backoff_sigue_mandando(self, conn):
		"""`deliver_after` no pisa `next_attempt_at`: un reintento espera lo suyo."""
		now = time.time()
		_insert(conn, deliver_after=None, next_attempt_at=now + 600)
		assert due_outbox_rows(conn.cursor(), now) == []
		assert len(due_outbox_rows(conn.cursor(), now + 601)) == 1


class TestEdad:
	def test_la_edad_cuenta_desde_la_fecha_de_entrega(self, conn):
		"""Programado hace 30 días para hace 1 minuto: su edad es 1 minuto."""
		now = time.time()
		created = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now - 30 * 86400))
		_insert(conn, deliver_after=now - 60, created_at=created)
		row = due_outbox_rows(conn.cursor(), now)[0]
		assert 30 < row["age_s"] < 180

	def test_sin_fecha_la_edad_sigue_siendo_la_de_creacion(self, conn):
		now = time.time()
		created = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(now - 3600))  # created_at es UTC
		_insert(conn, created_at=created)
		row = due_outbox_rows(conn.cursor(), now)[0]
		assert 3500 < row["age_s"] < 3700


class TestCanales:
	def test_el_poll_general_no_toca_soul(self, conn):
		now = time.time()
		_insert(conn, channel="soul", user="alma")
		_insert(conn, channel="telegram")
		rows = due_outbox_rows(conn.cursor(), now)
		assert [r["channel"] for r in rows] == ["telegram"]

	def test_el_poll_de_soul_respeta_su_fecha(self, conn):
		now = time.time()
		_insert(conn, channel="soul", user="alma", deliver_after=now + 3600)
		assert due_outbox_rows(conn.cursor(), now, channel="soul") == []
		assert len(due_outbox_rows(conn.cursor(), now + 3601, channel="soul")) == 1


def test_redrive_dead_letter_no_reespera_su_fecha(conn):
	"""Reenviar un dead letter significa "ahora", no "el día que estaba previsto"."""
	from neon_link.core.manager import redrive_outbox_dead_letters

	now = time.time()
	_insert(conn, deliver_after=now + 99999)
	row_id = conn.execute("SELECT id FROM outbox").fetchone()[0]
	conn.execute("UPDATE outbox SET status='FAILED' WHERE id=?", (row_id,))
	conn.execute(
		"INSERT INTO dead_letters (original_table, original_id, channel, channel_user_id, payload, error_reason)"
		" VALUES ('outbox', ?, 'telegram', 'u1', '{}', 'test')",
		(row_id,),
	)
	conn.commit()
	redrive_outbox_dead_letters(conn)
	again = conn.execute("SELECT deliver_after, status FROM outbox WHERE id=?", (row_id,)).fetchone()
	assert again["status"] == "PENDING"
	assert again["deliver_after"] is None
