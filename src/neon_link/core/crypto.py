import logging
import os
import stat
from typing import Dict, Tuple

from pure_mls.keys import KemKey, SignatureKey

logger = logging.getLogger(__name__)

class IdentityManager:
    """
    Gestor Criptográfico de Neon-Link (Multi-tenant orgánico).
    Carga múltiples identidades (seeds) o genera una autónoma si no hay configuración.
    """

    def __init__(self, seed_paths: list[str] = None, fallback_dir: str = "storage"):
        self.identities: Dict[str, Tuple[KemKey, SignatureKey]] = {}
        self.fallback_dir = fallback_dir
        
        if not seed_paths:
            logger.info("No identity paths provided. Using autonomous fallback.")
            self._generate_fallback_identity()
        else:
            for path in seed_paths:
                self.load_identity(path)

    def _ensure_secure_file(self, path: str):
        if not os.path.exists(path):
            return
        file_stat = os.stat(path)
        if file_stat.st_mode & (stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH | stat.S_IWOTH):
            logger.warning(f"Insecure permissions on seed {path}. Fixing to 600.")
            os.chmod(path, 0o600)

    def load_identity(self, path: str):
        """Carga una identidad (32-byte seed) desde un archivo."""
        path = os.path.expanduser(path)
        if not os.path.exists(path):
            logger.error(f"Identity seed not found at {path}")
            return

        self._ensure_secure_file(path)
        with open(path, "rb") as f:
            seed = f.read(32)

        kem_key = KemKey.from_private_bytes(seed)
        sig_key = SignatureKey.from_private_bytes(seed)
        
        # Usar el nombre del archivo (sin extensión) como alias interno
        alias = os.path.basename(path).split(".")[0]
        self.identities[alias] = (kem_key, sig_key)
        logger.info(f"Loaded identity '{alias}' from {path}")

    def _generate_fallback_identity(self):
        """Genera una identidad autónoma si no se inyecta ninguna externa."""
        os.makedirs(self.fallback_dir, mode=0o700, exist_ok=True)
        fallback_path = os.path.join(self.fallback_dir, "neon_link.seed")
        
        if os.path.exists(fallback_path):
            self.load_identity(fallback_path)
            return

        logger.info("Generating new autonomous seed for neon-link...")
        seed = os.urandom(32)
        
        tmp_path = fallback_path + ".tmp"
        fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(seed)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, fallback_path)
        
        self.load_identity(fallback_path)

    def get_identities(self) -> Dict[str, Tuple[KemKey, SignatureKey]]:
        return self.identities
