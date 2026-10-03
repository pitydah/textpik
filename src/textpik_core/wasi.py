"""Explicit WASI execution through an optional external sandbox runtime."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

MAX_INPUT_BYTES = 500_000
MAX_MEMORY_BYTES = 64 * 1024 * 1024


def run_wasi(module: Path, text: str, *, timeout_ms: int = 2000) -> str:
    runtime = shutil.which("wasmtime")
    if runtime is None:
        raise RuntimeError("wasmtime is not installed")
    module = module.expanduser().resolve()
    if not module.is_file() or module.suffix != ".wasm" or module.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("invalid WASI module")
    if len(text.encode("utf-8")) > MAX_INPUT_BYTES:
        raise ValueError("WASI input is too large")
    result = subprocess.run(
        [
            runtime,
            "run",
            "-W",
            f"max-memory-size={MAX_MEMORY_BYTES},max-memories=1,max-tables=4,max-instances=4",
            str(module),
        ],
        input=text,
        capture_output=True,
        text=True,
        timeout=max(0.1, min(10.0, timeout_ms / 1000)),
        check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip()[:1000] or "WASI action failed")
    return result.stdout[:500_000]
