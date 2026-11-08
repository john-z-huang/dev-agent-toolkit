from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]

SCRIPT = ROOT / "scripts" / "setup-codex-mcp.py"

SPEC = importlib.util.spec_from_file_location("setup_codex_mcp", SCRIPT)

assert SPEC is not None and SPEC.loader is not None

setup = importlib.util.module_from_spec(SPEC)

sys.modules[SPEC.name] = setup

SPEC.loader.exec_module(setup)


def config(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path
