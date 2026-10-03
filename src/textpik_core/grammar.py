"""On-demand LanguageTool client with bounded responses and no resident worker."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GrammarSuggestion:
    offset: int
    length: int
    message: str
    replacements: tuple[str, ...]
    rule_id: str = ""


class LanguageToolService:
    def __init__(self, endpoint: str = "http://127.0.0.1:8010/v2/check", timeout: float = 4.0):
        parsed = urllib.parse.urlparse(endpoint)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("unsupported LanguageTool endpoint")
        self.endpoint = endpoint
        self.timeout = max(0.5, min(15.0, timeout))

    def check(self, text: str, language: str = "auto") -> tuple[GrammarSuggestion, ...]:
        if not text.strip() or len(text) > 20_000:
            return ()
        payload = urllib.parse.urlencode({"text": text, "language": language}).encode()
        request = urllib.request.Request(self.endpoint, data=payload)
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            raise ValueError("LanguageTool response too large")
        body = json.loads(raw)
        suggestions = []
        for match in body.get("matches", [])[:100]:
            replacements = tuple(
                str(item.get("value", ""))[:200]
                for item in match.get("replacements", [])[:5]
                if item.get("value")
            )
            suggestions.append(
                GrammarSuggestion(
                    max(0, int(match.get("offset", 0))),
                    max(0, int(match.get("length", 0))),
                    str(match.get("message", ""))[:500],
                    replacements,
                    str(match.get("rule", {}).get("id", ""))[:100],
                )
            )
        return tuple(suggestions)


def apply_suggestions(text: str, suggestions, *, first_only: bool = False) -> str:
    applicable = [item for item in suggestions if item.replacements]
    if first_only:
        applicable = applicable[:1]
    result = text
    for item in sorted(applicable, key=lambda value: value.offset, reverse=True):
        if item.offset + item.length <= len(result):
            result = result[: item.offset] + item.replacements[0] + result[item.offset + item.length :]
    return result
