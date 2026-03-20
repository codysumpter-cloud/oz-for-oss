from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[4]
WORKFLOWS_DIR = ROOT / ".github" / "workflows"
PYTHON_DIR = ROOT / ".github" / "python"


def validate_python_sources() -> None:
    for path in PYTHON_DIR.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        compile(source, str(path), "exec")


def validate_workflows() -> None:
    for path in WORKFLOWS_DIR.glob("*.yml"):
        yaml.safe_load(path.read_text(encoding="utf-8"))


def main() -> int:
    validate_python_sources()
    validate_workflows()
    return 0
