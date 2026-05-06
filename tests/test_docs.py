import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent


def test_readme_links_resolve():
	"""Valida que todos los enlaces a archivos locales en README.md resuelven correctamente."""
	readme_path = PROJECT_ROOT / "README.md"
	assert readme_path.exists(), "README.md debe existir en la raíz"

	content = readme_path.read_text(encoding="utf-8")

	# Busca patrones tipo [Texto](docs/guides/usage.md)
	links = re.findall(r"\[.+?\]\((.+?)\)", content)

	for link in links:
		# Ignoramos enlaces HTTP externos
		if link.startswith("http://") or link.startswith("https://"):
			continue

		target_path = PROJECT_ROOT / link
		assert target_path.exists(), f"El enlace roto encontrado en README: {link}"
