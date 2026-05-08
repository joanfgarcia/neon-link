# Changelog

All notable changes to this project will be documented in this file.

## [0.3.1] - 2026-05-08

### Added
- **OS-Agnostic Config**: Migrated to `platformdirs` for standardized configuration and database paths (`~/.config/neon-link`, `~/.local/share/neon-link`).
- **CLI Commands**: Added robust `neon-link init` and `neon-link help` commands.

## [0.3.0] - 2026-05-08
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
- **Egress Polling Unification (P1 Audit Fix)**
  - Refactored `TelegramHub` to subclass `NetworkPlugin`.
  - Removed duplicate `poll_outbox` thread in Telegram, allowing `PluginManager`'s main loop to handle all outbound traffic synchronously via `CryptoPipeline`.
- **E2EE Deduplication & State Hardening (P2 Audit Fix)**
  - Added `message_id` with `UNIQUE` constraint to SQLite `inbox` & `outbox` via `db.py`.
  - Modified `CryptoPipeline` to deduplicate ingress using SHA-256 hash `INSERT OR IGNORE`.
  - Implemented Epoch ratcheting: Egress now explicitly generates and sends `group.update_key()` Commit payloads before Application messages to enforce Forward Secrecy.
- **Telegram Environment Sanitization (P2 Audit Fix)**
  - Removed insecure "REPLACE_ME" hardcoded fallback values for Telegram credentials.
- **Observability & Network Resilience (P3 Audit Fix)**
  - Added `/health` FastAPI endpoint to monitor broker status and SQLite connectivity.
  - Implemented Exponential Backoff in Firebase polling loop to prevent network storming on jitter/timeouts.
- **Configurable Database Path**
  - Exposed SQLite path via `NEON_LINK_DB_PATH` in `.env` to prevent hardcoded paths in production.

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
