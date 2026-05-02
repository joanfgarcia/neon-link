# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added
- **Phase 4: Omnipresence MVP** (2026-05-02)
  - Implemented Session Binding: Added `/list` and `/switch` commands to `telegram_bot.py`.
  - Added `telegram_sessions` and `cascade_mappings` to the SQLite WAL schema in `db.py`.
  - Enabled Egress routing: the bot now polls the `outbox` table and successfully sends AI-generated messages (or manual system injections) back to the user's mobile device via Telegram.
  - Stabilized the Ingress loop (`poll_telegram`) to parse control commands and queue standard texts into the `events.db` `inbox`.

### Known Issues
- Currently, auto-extraction of conversational LLM responses from the Antigravity IDE requires a deeper hook, as the `notificationContent` field does not natively track raw conversational chat. Workaround: manual injections or specific Tool calls.
