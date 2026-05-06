# Neon-Link 🌐

**Agnostic, Zero-Trust Communication Hub / Hub de Mensajería Agnóstico y Zero-Trust**

---

## English (EN)

Neon-Link is a decoupled, stateless microservice designed to act as a universal communication hub for the Red-Pill architecture. It manages external network interactions (such as Firebase polling) and zero-trust cryptographic identities (via `pure-mls`), ensuring the core systems remain isolated from external network complexities.

### Core Philosophy
1. **Sovereignty**: Neon-Link does not "own" the cryptographic keys. Keys are injected via a `.seed` file mounted at runtime.
2. **Multi-Tenant**: A single Neon-Link instance can multiplex connections for multiple Agent Identities.
3. **Protocol of Silence**: The service does not log sensitive message contents to `stdout`.
4. **Offline First**: Messages are decrypted and queued in a local, fast in-memory inbox for the core system to poll at its own pace.

### Quick Start
To run Neon-Link locally and securely (bound to `127.0.0.1:8770`):
```bash
./start.sh
```

For more details, check our [Usage Guide](docs/GUIDES/USAGE.md) and [Examples](docs/EXAMPLES/CURL_EXAMPLES.md).

---

## Español (ES)

Neon-Link es un microservicio desacoplado y sin estado (stateless) diseñado para actuar como hub universal de comunicaciones para la arquitectura Red-Pill. Gestiona las interacciones con redes externas (como el polling de Firebase) y las identidades criptográficas zero-trust (vía `pure-mls`), asegurando que los sistemas principales se mantengan aislados de las complejidades de red.

### Filosofía Central
1. **Soberanía**: Neon-Link no es "dueño" de las llaves criptográficas. Las llaves se inyectan mediante un archivo `.seed` en tiempo de ejecución.
2. **Multi-Tenant**: Una única instancia de Neon-Link puede multiplexar conexiones para múltiples Identidades de Agente.
3. **Protocolo de Silencio**: El servicio no registra contenidos de mensajes sensibles en `stdout`.
4. **Offline First**: Los mensajes se desencriptan y se encolan en un inbox local y rápido en memoria, para que el sistema principal los consulte a su propio ritmo.

### Inicio Rápido
Para levantar Neon-Link localmente de forma segura (mapeado a `127.0.0.1:8770`):
```bash
./start.sh
```

Para más detalles, consulta nuestra [Guía de Uso](docs/GUIDES/USAGE.md) y los [Ejemplos](docs/EXAMPLES/CURL_EXAMPLES.md).
