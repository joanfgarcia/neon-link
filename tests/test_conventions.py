import re
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent
TARGET_DIRS = ["src", "scripts", "docs"]
ROOT_FILES = ["README.md", "CHANGELOG.md", "CONVENTIONS.md", "LICENSE"]

def test_conventions_file_naming():
	"""Ensures the codebase adheres to the file naming conventions."""
	violations = []
	candidate_files = []
	for target in TARGET_DIRS:
		target_path = ROOT_DIR / target
		if target_path.exists():
			candidate_files.extend([f for f in target_path.rglob("*") if f.is_file()])
	
	for file_path in candidate_files:
		relative_path = file_path.relative_to(ROOT_DIR)
		
		# 1. Docs directories and markdown files must be UPPERCASE
		if relative_path.parts[0] == "docs":
			if file_path.suffix == ".md":
				stem = file_path.stem
				stem_no_version = re.sub("v\\d+(\\.\\d+)*", "", stem)
				if stem_no_version != stem_no_version.upper():
					violations.append(f"{relative_path} - Markdown file name in docs/ must be UPPER_SNAKE_CASE")
			for part in relative_path.parts[1:-1]: # checking directories inside docs/
				if part != part.upper():
					violations.append(f"{relative_path} - Directory inside docs/ must be UPPERCASE")
					
		# 2. Source directories and files must be lowercase
		elif relative_path.parts[0] == "src":
			if file_path.suffix == ".py":
				if file_path.stem != file_path.stem.lower():
					violations.append(f"{relative_path} - Python file name must be lowercase_with_underscores")
			for part in relative_path.parts[1:-1]:
				if part != part.lower():
					violations.append(f"{relative_path} - Directory inside src/ must be lowercase")
					
	# 3. Root files
	for rf in ROOT_FILES:
		root_f = ROOT_DIR / rf
		if not root_f.exists():
			violations.append(f"{rf} - Canonical root file missing")
			
	if violations:
		error_msg = "\\n".join(violations)
		raise AssertionError(f"Convention Violations Found:\\n{error_msg}")
