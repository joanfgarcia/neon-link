from unittest.mock import patch

from neon_link.db import get_connection, init_db


def test_init_db_and_get_connection(tmp_path):
	db_path = tmp_path / "test_events.db"

	with patch("neon_link.db.DB_PATH", db_path):
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
