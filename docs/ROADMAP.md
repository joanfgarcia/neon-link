# Neon-Link Roadmap 🗺️

Este documento rastrea las observaciones técnicas y mejoras planificadas para Neon-Link, basadas en las auditorías de grado "Sovereign" (Ecosistema Bünker).

## Fase 5: Omnipresence Hardening (Optimizaciones P3)

La auditoría v0.2.0 de Grok determinó que el sistema es apto para producción (Sovereign-Grade), pero delineó varias mejoras menores (P3) de resiliencia y escalabilidad para futuras iteraciones:

### 1. Concurrencia y Event Loops (Telegram)
- **Problema**: El callback de ingreso de Telegram ejecuta `asyncio.run(...)` directamente desde el hilo de polling. Aunque funcional, puede generar condiciones de carrera bajo estrés severo.
- **Solución**: Sustituir la invocación directa por una cola _thread-safe_ (`asyncio.Queue`) o mediante el uso de `loop.call_soon_threadsafe(...)` para despachar los eventos al _event loop_ principal del `PluginManager`.

### 2. Soporte Multi-Identidad Completo
- **Problema**: Actualmente, `CryptoPipeline` toma por defecto la primera identidad disponible (`self.identity_mgr.identities[0]`). Es aceptable para el modelo de tenant actual, pero limitante para topologías multi-agente complejas.
- **Solución**: Extender `CryptoPipeline` y el esquema de base de datos para mapear `group_id` a un `identity_alias` específico en cada mensaje/transacción.

### 3. Optimización de Transporte (Firebase)
- **Problema**: FirebaseHub realiza _polling_ destructivo (`get()` seguido de `delete()`). Funciona bien para volúmenes moderados, pero bajo cargas masivas de mensajes genera sobrecarga (overhead).
- **Solución**: Investigar y, si es estable, transicionar al modelo de _listeners_ del SDK de Firebase (`db.reference().listen(...)`) para una arquitectura de notificaciones push puras, en lugar de polling.

### 4. Alineación de Almacenamiento (LocalInbox vs SQLite)
- **Problema**: La API actual lee del `LocalInbox` (memoria RAM), mientras que el pipeline persiste simultáneamente en SQLite. Esto genera una ligera divergencia de estado si el servicio se reinicia.
- **Solución**: Unificar el flujo para que `/inbox` consulte siempre a SQLite, o convertir `LocalInbox` en un caché de paso (_write-through cache_) estrictamente sincronizado con la base de datos persistente.

### 5. Telemetría y Observabilidad
- **Métricas**: Implementar un nuevo endpoint `/metrics` en el servidor FastAPI que exponga:
  - Profundidad de colas de Inbox y Outbox.
  - Número de Epoch actual de los grupos MLS.
  - _Throughput_ de mensajes procesados por minuto (TPM).

### 6. Protocolo de Silencio (Logging Estricto)
- **Mejora**: Actualmente se registran metadatos de las operaciones. Para entornos extremadamente hostiles, implementar un nivel de logging `SILENT_MODE` o `PROTOCOL_OF_SILENCE=true` que reduzca drásticamente o redecte todos los metadatos antes de enviarlos a `stdout`.

### 7. Documentación Criptográfica
- **Mejora**: Añadir un documento detallado en `docs/CORE/MLS_OPERATIONS.md` que detalle el ciclo de vida del grupo, cómo se propagan las propuestas/commits de `pure-mls`, y el funcionamiento del _epoch ratcheting_ (Forward Secrecy).

### 8. Arquitectura de Plugins: Transición a un Modelo Desacoplado (HECHO)
- **Estado Real**: **[MIGRADO]**. La estrategia inicial dictaba mantener un "Monolito de Traducción" temporalmente. Sin embargo, debido al crecimiento del protocolo P2P (Rings), hemos aplicado el patrón _Anti-Corruption Layer_ de manera proactiva.
- **Solución Implementada**: `neon-link` ahora delega implementaciones complejas a repositorios soberanos independientes (ej. `neon-rings`), integrándolos como dependencias formales. Esto reduce la fricción de mantenimiento interno y aísla los fallos de red.
