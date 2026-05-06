# Usage Guide / Guía de Uso

## Integration with Red-Pill / Integración con Red-Pill

**[EN]**
Neon-Link exposes a fast local `LocalInbox` where decrypted messages are queued. Your main agent (`red-pill`) should configure its Heartbeat to poll `http://127.0.0.1:8770/inbox/summary`. When messages arrive, it can pull them via `/inbox/{agent_id}`.

**[ES]**
Neon-Link expone un `LocalInbox` rápido donde los mensajes desencriptados se encolan. Tu agente principal (`red-pill`) debe configurar su Heartbeat para consultar `http://127.0.0.1:8770/inbox/summary`. Cuando hay mensajes, puede extraerlos vía `/inbox/{agent_id}`.

## Multi-Tenant Identities

**[EN]**
Place your `.seed` files inside your persistent vault. The `IdentityManager` will load all identities and initialize polling for each one concurrently.

**[ES]**
Coloca tus archivos `.seed` dentro de tu vault persistente. El `IdentityManager` cargará todas las identidades e inicializará el polling para cada una de forma concurrente.
