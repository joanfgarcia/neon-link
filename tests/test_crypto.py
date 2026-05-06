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
	
	mgr = IdentityManager(seed_paths=[str(seed_path)], fallback_dir=str(tmp_path))
	
	assert "Insecure permissions" in caplog.text
	assert (seed_path.stat().st_mode & 0o777) == 0o600
	
def test_identity_manager_missing_seed(tmp_path, caplog):
	import logging
	caplog.set_level(logging.ERROR)
	
	mgr = IdentityManager(seed_paths=["/non/existent/path.seed"], fallback_dir=str(tmp_path))
	assert "not found" in caplog.text
