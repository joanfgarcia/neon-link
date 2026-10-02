"""Aislamiento de la suite: ningún test toca la config, los datos ni la red reales.

Se fija ANTES de importar neon_link (este módulo carga primero): `platformdirs`
resuelve config/datos/claves bajo un HOME/XDG temporal y `NEON_LINK_DB_PATH`
apunta a un events.db desechable. Sin esto, `start_daemon()` migraba el
events.db del operador e `IdentityManager` leía su directorio de claves.
"""

import os
import tempfile

import pytest

_SANDBOX = tempfile.mkdtemp(prefix="neon-link-tests-")
for _var, _sub in (
	("HOME", "home"),
	("XDG_CONFIG_HOME", "config"),
	("XDG_DATA_HOME", "data"),
	("XDG_STATE_HOME", "state"),
	("XDG_CACHE_HOME", "cache"),
):
	os.environ[_var] = os.path.join(_SANDBOX, _sub)
os.environ["NEON_LINK_DB_PATH"] = os.path.join(_SANDBOX, "data", "neon-link", "events.db")
os.environ.pop("NEON_LINK_VAULT_DIR", None)
os.environ.pop("NEON_LINK_SEED_PATHS", None)


@pytest.fixture(autouse=True)
def _no_real_http(monkeypatch):
	"""HTTP real bloqueado: los tests que lo necesitan mockean `requests` en su módulo."""

	def _blocked(*args, **kwargs):
		raise RuntimeError("[TEST ISOLATION] real HTTP is blocked in tests")

	monkeypatch.setattr("requests.sessions.Session.request", _blocked)
