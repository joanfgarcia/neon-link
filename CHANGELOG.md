# Changelog

All notable changes to this project will be documented in this file.

## [0.5.1] - Unreleased

### Added
- **XDG Seed Storage Compliance**: Configured `IdentityManager` to store autonomous cryptographic seeds under the standard XDG data directory (`~/.local/share/neon-link/keys/` by default or overridden via `NEON_LINK_VAULT_DIR` env var).
- **Robust Seed Fallback**: Improved initialization to automatically generate a fallback autonomous seed in the vault directory if the specified `seed_paths` are missing or cannot be loaded, preventing startup crash loop.

## [0.5.0] - 2026-06-17

### Added
- **P2P Transport (neon-rings integration)**: Integrated `neon-rings` into `neon-link` as a P2P `NetworkPlugin` (`rings.py`), allowing P2P MLS-encrypted transport.
- **Rings DHT KeyPackage Sharing**: Enabled P2P MLS `KeyPackage` publishing to and fetching from the Rings DHT, securing P2P sessions setup.
- **Rings Configuration**: Added `ENABLE_RINGS` and `RINGS_ENDPOINT_URL` configuration parameters to the environment configuration.

### Fixed
- **Telegram Character Limit & Outbox Deadlock**: Implemented automatic chunking of Telegram messages exceeding 4000 characters with ellipsis continuation (`...`) and series fraction tracking (`\n#/#`). Introduced an outbox retry limit (max 3) and routing of permanently failing messages to `dead_letters` to prevent queue deadlocks. Added auto-migration trigger on daemon startup.

### Changed
- **MLS E2EE support**: Updated `CryptoPipeline` egress and ingress paths to enforce MLS encryption for the `rings` plugin just like the `firebase` channel.

## [0.4.0] - 2026-05-22

### Added
- **systemd Watchdog Integration**: Neon-Link now sends `sd_notify("WATCHDOG=1")` heartbeats from its main loop, enabling systemd `WatchdogSec` to auto-restart the daemon if it hangs. Zero external dependencies — uses raw Unix domain sockets.
- **sd_notify READY signal**: Sends `READY=1` after full initialization, allowing `Type=notify` in the systemd unit for proper startup tracking.

### Fixed
- **Duplicate Service Prevention**: Discovered and eliminated a duplicate `redpill-neonlink.service` that ran alongside `neon-link.service` for 10+ hours, causing 4x Telegram response amplification. Root cause: legacy PyPI-installed service coexisting with dev-project service.

### Removed
- **neon-link-healer** (service + timer + script): Replaced by native systemd `WatchdogSec=3` + `Restart=on-failure`. The healer's curl-based polling was unable to detect the duplicate service incident.

### Changed
- Unit file updated: `Type=simple` → `Type=notify`, added `WatchdogSec=3`, `NotifyAccess=all`, `Restart=on-failure`.

## [0.3.6] - 2026-05-18
### Added
- Timestamp injection into `/list`, `/switch` and text payloads to bypass deduplication.
- `cascade_type` column to SQLite schema for background session isolation.
- Headless Sandbox `/new` command block restored.

## [0.3.5] - 2026-05-18

### Fixed
- **Telegram `/new` Bug**: Fixed an issue where the `/new` command's `NEW_CASCADE` internal payload was being incorrectly overwritten by the default message router.

## [0.3.4] - 2026-05-18

### Added
- **Bot Commands Menu**: Neon-Link now automatically registers the quick commands menu (via `setMyCommands` Telegram API) when starting up, ensuring `/help`, `/new`, `/list`, `/switch` and `/bg` are available in the UI.

## [0.3.3] - 2026-05-18

### Added
- **Headless Commands**: Added `/help` and `/new` commands to the Telegram plugin to initialize and manage headless conversational sessions via Telegram.

## [0.3.2] - 2026-05-09

### Added
- **Session ID Abstraction**: Migrated routing from raw Telegram chat IDs to UUID-based Session IDs (`sessions_mapping`). This securely isolates parallel multi-bot architectures sharing the same SQLite instance and enables platform-agnostic conversation state.

### Fixed
- **Event Router Mode Extraction**: Middleware `_enqueue_inbox` now dynamically extracts the `mode` parameter from decrypted payloads, properly routing `conversational` messages instead of forcing them into the `background` queue.

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
