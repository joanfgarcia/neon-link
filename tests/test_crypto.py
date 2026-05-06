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
