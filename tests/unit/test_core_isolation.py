import ast
from pathlib import Path

FORBIDDEN_PREFIXES = (
    "adapters",
    "apps",
    "fastapi",
    "sqlalchemy",
    "asyncpg",
    "aiosqlite",
    "httpx",
    "google",
    "groq",
    "paypal_agent_toolkit",
    "channel3_sdk",
)


def test_mandate_core_has_zero_adapter_or_app_imports() -> None:
    """
    Hard architectural rule (Section 3):
    Nothing inside mandate_core may import from adapters/, apps/, or external vendor SDKs.
    """
    core_root = Path(__file__).resolve().parents[2] / "packages" / "core" / "mandate_core"
    py_files = list(core_root.rglob("*.py"))
    assert len(py_files) >= 10

    violations: list[str] = []
    for path in py_files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith(FORBIDDEN_PREFIXES):
                        violations.append(f"{path}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith(FORBIDDEN_PREFIXES):
                    violations.append(f"{path}: from {node.module} import ...")

    assert violations == [], f"Forbidden imports in mandate_core: {violations}"
