# Usage Guide / Guía de Uso

## Integration with Red-Pill / Integración con Red-Pill

**[EN]**
Neon-Link exposes a fast local `LocalInbox` where decrypted messages are queued. Your main agent (`red-pill`) should configure its Heartbeat to poll `http://127.0.0.1:8770/inbox/summary`. When messages arrive, it can pull them via `/inbox/{agent_id}`.

**[ES]**
Neon-Link expone un `LocalInbox` rápido donde los mensajes desencriptados se encolan. Tu agente principal (`red-pill`) debe configurar su Heartbeat para consultar `http://127.0.0.1:8770/inbox/summary`. Cuando hay mensajes, puede extraerlos vía `/inbox/{agent_id}`.

## Multi-Tenant Identities

**[EN]**
Place your `.seed` files inside your persistent vault directory. By default, the vault is located in the standard XDG directory `~/.local/share/neon-link/keys/` (on Linux), or you can override it using the `NEON_LINK_VAULT_DIR` environment variable. The `IdentityManager` will load all identities and initialize polling for each one concurrently.

**[ES]**
Coloca tus archivos `.seed` dentro de tu directorio de vault persistente. Por defecto, el vault se encuentra en la ruta estándar XDG `~/.local/share/neon-link/keys/` (en Linux), o puedes cambiarlo usando la variable de entorno `NEON_LINK_VAULT_DIR`. El `IdentityManager` cargará todas las identidades e inicializará el polling para cada una de forma concurrente.

