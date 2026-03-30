from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path


TESTS_DIR = Path(__file__).resolve().parent
SRC_DIR = TESTS_DIR.parent
REQUIREMENTS_PATH = SRC_DIR / "requirements.txt"
GITHUB_API_PATH = SRC_DIR / "oz_workflows" / "github_api.py"


def imported_top_level_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".")[0])
    return modules


def declared_requirements(path: Path) -> set[str]:
    requirements: set[str] = set()
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("git+"):
            continue
        normalized = re.split(r"[<>=!~]", line.split("[", 1)[0], maxsplit=1)[0]
        requirements.add(normalized.strip().lower().replace("_", "-"))
    return requirements


class DirectDependencyDeclarationTest(unittest.TestCase):
    def test_github_api_direct_imports_are_declared(self) -> None:
        imports = imported_top_level_modules(GITHUB_API_PATH)
        if "httpx" not in imports:
            self.skipTest("github_api.py no longer imports httpx directly")

        requirements = declared_requirements(REQUIREMENTS_PATH)
        self.assertIn("httpx", requirements)


if __name__ == "__main__":
    unittest.main()
