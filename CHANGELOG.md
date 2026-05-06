# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added
- **Test Coverage Expansion** (2026-05-06)
  - Stabilized the Neon-Link test suite, reaching **96.31%** total code coverage.
  - Implemented extensive unit and integration tests across `middleware.py`, `firebase.py`, and `telegram.py` handling complex async mocks and threads.
  - Validated adherence to the Sound of Silence protocol and Red-Pill conventions.
- **Pipeline Architecture** (2026-05-06)
  - Decoupled `CryptoPipeline` handling E2E encryption from transport plugins (`FirebaseHub` / `TelegramHub`).

### Fixed
- **SQLite Concurrency Hardening (P1 Audit Fix)**
  - Configured `get_connection()` with `timeout=30.0`, `isolation_level='IMMEDIATE'`, and `PRAGMA busy_timeout=5000` to prevent `database is locked` errors during high-frequency Swarm polling.
  - Added `@with_retry` decorator in `db.py` for defense-in-depth transaction management.

### Changed
- Updated `scripts/prepare_audit.sh` to correctly compile the `NEON_LINK_DIGEST.txt` payload for LLM audits.
- Removed obsolete tracked digest files to clean up the repository.

### Added (Legacy)
- **Phase 4: Omnipresence MVP** (2026-05-02)
  - Implemented Session Binding: Added `/list` and `/switch` commands to `telegram_bot.py`.
  - Added `telegram_sessions` and `cascade_mappings` to the SQLite WAL schema in `db.py`.
  - Enabled Egress routing: the bot now polls the `outbox` table and successfully sends AI-generated messages (or manual system injections) back to the user's mobile device via Telegram.
  - Stabilized the Ingress loop (`poll_telegram`) to parse control commands and queue standard texts into the `events.db` `inbox`.

### Known Issues
- Currently, auto-extraction of conversational LLM responses from the Antigravity IDE requires a deeper hook, as the `notificationContent` field does not natively track raw conversational chat. Workaround: manual injections or specific Tool calls.
