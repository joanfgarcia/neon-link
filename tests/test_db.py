from unittest.mock import patch

from neon_link.db import get_connection, init_db


def test_init_db_and_get_connection(tmp_path):
	db_path = tmp_path / "test_events.db"

	with patch("neon_link.db.get_db_path", return_value=db_path):
		# Initialize the DB
		init_db()
		assert db_path.exists()

		# Test connection
		conn = get_connection()
		cursor = conn.cursor()

		# Verify tables exist
		cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
		tables = [row[0] for row in cursor.fetchall()]

		expected_tables = ["system_health", "inbox", "outbox", "cascade_mappings", "mls_states", "dead_letters", "telegram_sessions"]
		for table in expected_tables:
			assert table in tables

		conn.close()


def test_telegram_sessions_has_model_and_backend_columns(tmp_path):
	"""RFC §2A/D1/D8: telegram_sessions.model + backend deben existir en una
	instalación fresca (el ALTER de migración no aplica si la tabla no existía
	aún — el CREATE TABLE debe incluirlas)."""
	db_path = tmp_path / "test_events.db"

	with patch("neon_link.db.get_db_path", return_value=db_path):
		init_db()
		conn = get_connection()
		cursor = conn.cursor()
		cursor.execute("PRAGMA table_info(telegram_sessions)")
		cols = {row[1] for row in cursor.fetchall()}
		assert "model" in cols
		assert "backend" in cols
		conn.close()


def test_telegram_sessions_migrates_existing_db(tmp_path):
	"""RFC §2A: una DB antigua sin model/backend se migra vía ALTER."""
	import sqlite3

	from neon_link.db import get_db_path

	db_path = tmp_path / "legacy_events.db"
	conn = sqlite3.connect(str(db_path))
	conn.execute(
		"""CREATE TABLE telegram_sessions (
			channel_user_id TEXT PRIMARY KEY,
			cascade_id TEXT,
			cascade_type TEXT DEFAULT 'interactive',
			updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
		)"""
	)
	conn.commit()
	conn.close()

	with patch("neon_link.db.get_db_path", return_value=db_path):
		init_db()
		conn = get_connection()
		cursor = conn.cursor()
		cursor.execute("PRAGMA table_info(telegram_sessions)")
		cols = {row[1] for row in cursor.fetchall()}
		assert "model" in cols
		assert "backend" in cols
		conn.close()
