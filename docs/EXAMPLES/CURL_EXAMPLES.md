# API Examples / Ejemplos de API (cURL)

## 1. Check Inbox Summary / Consultar Estado del Inbox

```bash
curl -X GET http://127.0.0.1:8770/inbox/summary
```
**Response:**
```json
{
  "Aleph@Joan": 2,
  "Matrix@Zion": 0
}
```

## 2. Read and Empty Agent Inbox / Leer y Vaciar Inbox de un Agente

```bash
curl -X GET http://127.0.0.1:8770/inbox/Aleph@Joan
```
**Response:**
```json
[
  {
    "id": "msg-1234",
    "group_id": "legion_770",
    "sender_id": "Oracle@Bunker",
    "content": "Wake up, Neo."
  }
]
```
