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
To initialize the configuration in your user directory (OS-agnostic):
```bash
uv run neon-link init
```
To run Neon-Link locally and securely:
```bash
uv run neon-link start
```

### Configuration & Dependency Injection
Neon-Link is designed to be fully platform-agnostic. All paths and credentials must be provided explicitly to avoid hardcoded environments.

**As a Daemon:**
Run `uv run neon-link init`. This will create `~/.config/neon-link/.env` (or OS equivalent) and initialize the `events.db` queue in the same directory. Fill in the required variables (e.g., `NEON_LINK_AGENT_ID`). The daemon will fail-fast if these are missing.

**As a Library (Plugin for Red-Pill):**
You can inject dependencies dynamically at runtime without relying on `.env` files:
```python
import neon_link.db
from neon_link.plugins.telegram import TelegramHub

# 1. Inject Database Path dynamically
neon_link.db.set_db_path("/absolute/path/to/cortex.db")

# 2. Inject credentials directly to plugins
t_hub = TelegramHub(identity_manager, bot_token="TOKEN", allowed_user_id="ID")
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
Para inicializar la configuración en tu directorio de usuario (Agnóstico al SO):
```bash
uv run neon-link init
```
Para levantar Neon-Link localmente de forma segura:
```bash
uv run neon-link start
```

### Configuración e Inyección de Dependencias
Neon-Link está diseñado para ser totalmente agnóstico a la plataforma. No hay rutas absolutas duras ni credenciales por defecto.

**Como Daemon:**
Ejecuta `uv run neon-link init`. Esto creará `~/.config/neon-link/.env` (o el equivalente de tu SO) e inicializará la cola `events.db` en el mismo directorio. Rellena las variables requeridas (ej. `NEON_LINK_AGENT_ID`). El daemon fallará rápidamente (Fail-Fast) si alguna configuración crítica falta.

**Como Librería (Plugin para Red-Pill):**
Puedes inyectar las dependencias de forma dinámica en tiempo de ejecución sin usar archivos `.env`:
```python
import neon_link.db
from neon_link.plugins.telegram import TelegramHub

# 1. Inyectar la ruta a la base de datos de manera explícita
neon_link.db.set_db_path("/ruta/absoluta/hacia/cortex.db")

# 2. Inyectar credenciales directamente en la instancia
t_hub = TelegramHub(identity_manager, bot_token="TOKEN", allowed_user_id="ID")
```

Para más detalles, consulta nuestra [Guía de Uso](docs/GUIDES/USAGE.md) y los [Ejemplos](docs/EXAMPLES/CURL_EXAMPLES.md).
