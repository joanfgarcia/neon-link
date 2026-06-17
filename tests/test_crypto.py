import os

from neon_link.core.crypto import IdentityManager


def test_identity_manager_autonomous_generation(tmp_path):
	# Forzamos que lea desde un directorio vacío
	os.environ["NEON_LINK_VAULT_DIR"] = str(tmp_path)

	mgr = IdentityManager(fallback_dir=str(tmp_path))

	# Debe generar la identidad "neon_link" (por defecto) si no hay seeds
	identities = mgr.get_identities()
	assert len(identities) == 1
	assert "neon_link" in identities

	# La semilla debe cargar KemKey y SigKey
	kem, sig = identities["neon_link"]
	assert kem is not None
	assert sig is not None


def test_identity_manager_invalid_permissions(tmp_path, caplog):
	import logging

	caplog.set_level(logging.WARNING)

	seed_path = tmp_path / "bad_perms.seed"
	seed_path.write_bytes(os.urandom(32))
	seed_path.chmod(0o777)

	IdentityManager(seed_paths=[str(seed_path)], fallback_dir=str(tmp_path))

	assert "Insecure permissions" in caplog.text
	assert (seed_path.stat().st_mode & 0o777) == 0o600


def test_identity_manager_missing_seed(tmp_path, caplog):
	import logging

	caplog.set_level(logging.ERROR)

	mgr = IdentityManager(seed_paths=["/non/existent/path.seed"], fallback_dir=str(tmp_path))
	assert "not found" in caplog.text
	# El fallback debe haber creado la clave autónoma en tmp_path
	assert os.path.exists(os.path.join(tmp_path, "neon_link.seed"))
	assert "neon_link" in mgr.get_identities()


def test_identity_manager_env_vault_dir(tmp_path, monkeypatch):
	monkeypatch.setenv("NEON_LINK_VAULT_DIR", str(tmp_path))
	mgr = IdentityManager()
	assert mgr.fallback_dir == str(tmp_path)
	assert os.path.exists(os.path.join(tmp_path, "neon_link.seed"))


def test_identity_manager_platformdirs_fallback(tmp_path, monkeypatch):
	# Limpiamos la variable de entorno para forzar el fallback de platformdirs
	monkeypatch.delenv("NEON_LINK_VAULT_DIR", raising=False)
	monkeypatch.setattr("platformdirs.user_data_dir", lambda name: str(tmp_path))

	mgr = IdentityManager()
	expected_dir = os.path.join(str(tmp_path), "keys")
	assert mgr.fallback_dir == expected_dir
	assert os.path.exists(os.path.join(expected_dir, "neon_link.seed"))

