"""Lazy optional providers invoked only after an explicit user action."""

from __future__ import annotations

import json
import re
import subprocess
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from threading import Event


@dataclass(frozen=True, slots=True)
class ProviderResponse:
    text: str
    provider: str
    model: str = ""


class OllamaProvider:
    def __init__(self, endpoint: str = "http://127.0.0.1:11434/api/generate", timeout: float = 30.0):
        if not endpoint.startswith(("http://127.0.0.1:", "http://localhost:")):
            raise ValueError("Ollama endpoint must be local")
        self.endpoint = endpoint
        self.timeout = max(1.0, min(120.0, timeout))

    def generate(self, text: str, *, task: str = "rewrite", model: str, cancelled: Event | None = None) -> ProviderResponse:
        if cancelled and cancelled.is_set():
            raise RuntimeError("cancelled")
        instructions = {
            "rewrite": "Reescribe con claridad, conservando el significado.",
            "summarize": "Resume de forma fiel y breve.",
            "simplify": "Simplifica el texto sin perder información esencial.",
            "tasks": "Extrae una lista breve de tareas accionables.",
            "explain": "Explica el contenido de forma precisa.",
        }
        if task not in instructions:
            raise ValueError("unsupported Ollama task")
        if not text.strip() or len(text) > 200_000:
            raise ValueError("invalid Ollama input")
        if not re.fullmatch(r"[A-Za-z0-9_.:/-]{1,100}", model):
            raise ValueError("invalid Ollama model")
        payload = json.dumps({
            "model": model,
            "prompt": f"{instructions[task]}\n\n{text}",
            "stream": False,
            "format": "json",
        }).encode()
        request = urllib.request.Request(self.endpoint, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            raw = response.read(2_000_001)
        if len(raw) > 2_000_000 or (cancelled and cancelled.is_set()):
            raise RuntimeError("response too large or cancelled")
        body = json.loads(raw)
        if not isinstance(body, dict):
            raise RuntimeError("invalid Ollama response")
        value = str(body.get("response", ""))
        try:
            structured = json.loads(value)
            value = str(structured.get("text", structured.get("result", value)))
        except (ValueError, AttributeError):
            pass
        return ProviderResponse(value[:200_000], "ollama", model)


class TesseractProvider:
    def __init__(self, executable: str = "tesseract", timeout: float = 20.0):
        self.executable = executable
        self.timeout = max(2.0, min(60.0, timeout))

    def recognize(self, image: Path, languages: str = "eng") -> ProviderResponse:
        image = image.expanduser().resolve()
        if not image.is_file() or image.stat().st_size > 50 * 1024 * 1024:
            raise ValueError("invalid OCR image")
        if not re.fullmatch(r"[A-Za-z0-9_+.-]{1,100}", languages):
            raise ValueError("invalid OCR languages")
        result = subprocess.run(
            [self.executable, str(image), "stdout", "-l", languages],
            capture_output=True,
            text=True,
            timeout=self.timeout,
            check=False,
        )
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or "OCR failed")
        return ProviderResponse(result.stdout[:500_000].strip(), "tesseract")
