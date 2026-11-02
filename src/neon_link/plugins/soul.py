"""SoulHub — canal interno `soul` (S2.1, red-pill).

Qué es
------
Un plugin **local**, sin red ni cripto, que entrega los sobres del coro al
cuerpo vivo de un alma. No es un canal externo: no habla con Telegram, Firebase
ni `neon-rings`. Vive en el mismo broker (outbox/DLQ/redrive) para que el estado
de entrega tenga un solo dueño.

Contrato
--------
- El payload del outbox es el **sobre** JSON: `{event_id, mission_id,
continuity_id, verb, thread_id, reply_to, hop, hop_max, expects_reply,
value_class, expires_at}`. El texto **no** viaja: vive en `mission_events`.
- La entrega la hace red-pill, no este plugin: se invoca su puerto local
(`red-pill session deliver --event <id> --broker --json`) y se traduce el
informe:
- `handed_off` / `skipped` → SENT (el transporte lo tomó o el receptor dijo no)
- `deferred` (sin cuerpo, sin punto de inyección, claim ajeno) → RETRY
- `given_up` → DEAD (`PermanentEgressError`)
- informe vacío → SENT (el evento ya era terminal; no se reentrega)
- El puerto exige `--broker` + `REDPILL_BROKER=1` para no abrir el push a un CLI
cualquiera. El plugin lo pone en el entorno del subproceso.

Aislamiento de egress
-------------------
`red-pill session deliver` puede tardar (abre un turno en el arnés). Por eso el
canal `soul` tiene su **propio hilo de egress**: el poller principal del manager
excluye `channel='soul'`, y un `soul` lento no retrasa Telegram/Firebase/rings.
El timeout sigue existiendo (`NEON_LINK_SOUL_TIMEOUT_S`, 120 s).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shlex
import subprocess
import threading
import time

from neon_link.models.network import NetworkEvent
from neon_link.plugins.base import NetworkPlugin, PermanentEgressError

logger = logging.getLogger(__name__)

CHANNEL = "soul"


class SoulHub(NetworkPlugin):
	"""Entrega local de sobres del coro; sin red, sin MLS, sin texto."""

	# El manager debe pasar el payload crudo (el sobre), no el campo `text`.
	raw_payload = True

	def __init__(
		self,
		identity_manager,
		*,
		redpill_cmd: str | None = None,
		timeout_s: float | None = None,
		manager=None,
	):
		super().__init__(CHANNEL, identity_manager)
		self.redpill_cmd: str = redpill_cmd or os.getenv("NEON_LINK_SOUL_REDPILL") or "red-pill"
		self.timeout_s: float = float(timeout_s or os.getenv("NEON_LINK_SOUL_TIMEOUT_S") or "120")
		self.reconcile_s: float = float(os.getenv("NEON_LINK_SOUL_RECONCILE_S") or "60")
		self.manager = manager
		self._stop = threading.Event()
		self._thread: threading.Thread | None = None
		self._egress_thread: threading.Thread | None = None

	async def start(self):
		# Hilo propio: el daemon no mantiene el event loop de asyncio corriendo
		# entre pulsos, así que un create_task aquí nunca se ejecutaría.
		if self.reconcile_s > 0 and self._thread is None:
			self._thread = threading.Thread(target=self._reconcile_loop, daemon=True)
			self._thread.start()
		if self.manager is not None and self._egress_thread is None:
			self._egress_thread = threading.Thread(target=self._egress_loop, daemon=True)
			self._egress_thread.start()
		logger.info("[SoulHub] canal interno listo (sin red)")

	async def stop(self):
		self._stop.set()
		for thread in (self._thread, self._egress_thread):
			if thread is not None:
				thread.join(timeout=2.0)
		self._thread = None
		self._egress_thread = None
		logger.info("[SoulHub] canal interno detenido")

	def _egress_loop(self) -> None:
		"""Procesa solo `channel='soul'`; el poller principal ya lo excluye."""
		import sqlite3

		from neon_link.db import get_connection

		loop = asyncio.new_event_loop()
		try:
			while not self._stop.wait(1.0):
				conn = None
				try:
					conn = get_connection()
					conn.row_factory = sqlite3.Row
					cursor = conn.cursor()
					from neon_link.core.manager import due_outbox_rows

					pending = due_outbox_rows(cursor, time.time(), channel="soul", limit=1)
					if not pending:
						continue
					row = pending[0]
					self.manager._process_outbox_row_contained(loop, cursor, row)
					conn.commit()
				except Exception as e:
					logger.debug(f"[SoulHub] egress soul falló: {e}")
				finally:
					if conn is not None:
						conn.close()
		finally:
			loop.close()

	def _reconcile_loop(self) -> None:
		"""Despierta `mission_events -> outbox` periódicamente (no bloquea egress)."""
		while not self._stop.wait(max(1.0, self.reconcile_s)):
			try:
				self._reconcile_once()
			except Exception as e:
				logger.debug(f"[SoulHub] reconcile falló: {e}")

	def _reconcile_once(self) -> None:
		cmd = [*shlex.split(self.redpill_cmd), "coro", "reconcile", "--json", "--hours", "24"]
		try:
			res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
		except Exception as e:
			logger.debug(f"[SoulHub] no se pudo lanzar reconcile: {e}")
			return
		if res.returncode != 0:
			logger.warning(f"[SoulHub] reconcile rc={res.returncode}: {(res.stderr or '')[:160]}")
			return
		try:
			report = json.loads(res.stdout or "{}")
		except Exception:
			return
		if report.get("published"):
			logger.info(f"[SoulHub] reconcile: publicados={report.get('published')} fallidos={report.get('failed')} leídos={report.get('scanned')}")

	async def fetch_key_package(self, agent_id: str) -> bytes | None:
		"""No hay red ni MLS: el canal es local."""
		return None

	async def send_event(self, event: NetworkEvent) -> bool:
		envelope = self._parse(event)
		event_id = str(envelope.get("event_id") or "").strip()
		soul = str(envelope.get("continuity_id") or event.recipient_id or "").strip()
		if not event_id or not soul:
			raise PermanentEgressError("sobre sin event_id/continuity_id")

		cmd = [
			*shlex.split(self.redpill_cmd),
			"session",
			"deliver",
			"--continuity",
			soul,
			"--event",
			event_id,
			"--broker",
			"--json",
		]
		env = {**os.environ, "REDPILL_BROKER": "1"}
		try:
			proc = await asyncio.create_subprocess_exec(
				*cmd,
				stdout=asyncio.subprocess.PIPE,
				stderr=asyncio.subprocess.PIPE,
				env=env,
			)
		except FileNotFoundError:
			logger.error(f"[SoulHub] no encuentro el CLI de red-pill: {self.redpill_cmd!r}")
			return False
		except Exception as e:
			logger.error(f"[SoulHub] no se pudo lanzar red-pill: {e}")
			return False

		try:
			stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self.timeout_s)
		except TimeoutError:
			proc.kill()
			await proc.wait()
			logger.warning(f"[SoulHub] timeout {self.timeout_s:.0f}s entregando {event_id[:12]}")
			return False

		if proc.returncode != 0:
			logger.warning(f"[SoulHub] red-pill rc={proc.returncode} para {event_id[:12]}: {(stderr or b'').decode('utf-8', 'replace')[:200]}")
			return False

		report = self._report(stdout)
		if report.get("given_up"):
			reason = ", ".join(str(x.get("reason") or "") for x in report["given_up"])
			raise PermanentEgressError(f"given_up: {reason or 'sin motivo'}")
		if report.get("deferred"):
			reasons = ", ".join(str(x.get("reason") or "") for x in report["deferred"])
			logger.info(f"[SoulHub] {event_id[:12]} diferido: {reasons or 'sin motivo'}")
			return False
		# handed_off, skipped o informe vacío (ya terminal): cerrar como SENT.
		return True

	@staticmethod
	def _parse(event: NetworkEvent) -> dict:
		try:
			data = json.loads(event.payload.decode("utf-8"))
		except Exception as e:
			raise PermanentEgressError(f"sobre corrupto: {e}") from e
		if not isinstance(data, dict):
			raise PermanentEgressError(f"sobre no es objeto: {type(data).__name__}")
		return data

	@staticmethod
	def _report(stdout: bytes) -> dict:
		try:
			data = json.loads((stdout or b"{}").decode("utf-8"))
		except Exception:
			return {}
		return data if isinstance(data, dict) else {}
