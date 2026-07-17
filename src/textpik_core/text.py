"""Fast, desktop-independent text classification and command preparation."""

from __future__ import annotations

import ipaddress
import json
import re
import shlex
from urllib.parse import parse_qs, quote_plus, urlparse


def build_command_argv(template: str, text: str) -> list[str]:
    """Substitute selected text without merging or shell-expanding arguments."""
    raw_marker = "__TEXTPIK_SELECTED_TEXT__"
    url_marker = "__TEXTPIK_SELECTED_TEXT_URL__"
    prepared = (
        template.replace("{url}", url_marker)
        .replace("{}", raw_marker)
        .replace("***", raw_marker)
    )
    argv = shlex.split(prepared)

    result = []
    for argument in argv:
        if raw_marker in argument and argument.startswith(("http://", "https://")):
            argument = argument.replace(raw_marker, quote_plus(text))
        else:
            argument = argument.replace(raw_marker, text)
        result.append(argument.replace(url_marker, quote_plus(text)))
    return result


def normalize_url(text: str) -> str:
    """Return an HTTP(S) URL for safe URL-like text, otherwise an empty string."""
    url = text.strip()
    if not url or any(char.isspace() for char in url):
        return ""
    explicit_scheme = url.lower().startswith(("http://", "https://"))
    if not explicit_scheme and "@" in url:
        return ""
    if not explicit_scheme:
        url = f"https://{url}"
    parsed = urlparse(url)
    if not parsed.hostname:
        return ""
    hostname = parsed.hostname
    if hostname != "localhost":
        try:
            ipaddress.ip_address(hostname)
        except ValueError:
            labels = hostname.rstrip(".").split(".")
            if len(labels) < 2:
                return ""
            if not all(
                label
                and len(label) <= 63
                and not label.startswith("-")
                and not label.endswith("-")
                and all(char.isalnum() or char == "-" for char in label)
                for label in labels
            ):
                return ""
            if len(labels[-1]) < 2 or not labels[-1].isalpha():
                return ""
    return url


def classify_text(text: str) -> frozenset[str]:
    """Classify selected text using deterministic rules with no I/O."""
    stripped = text.strip()
    if not stripped:
        return frozenset()

    types = {"text"}
    if stripped.casefold().startswith("magnet:?"):
        query = urlparse(stripped).query
        values = parse_qs(query)
        if any(
            item.casefold().startswith(("urn:btih:", "urn:btmh:"))
            for item in values.get("xt", [])
        ):
            types.add("magnet")
    if re.fullmatch(r"[^\W\d_]+(?:[-'’][^\W\d_]+)?", stripped, re.UNICODE):
        types.add("word")
    if normalize_url(stripped):
        types.add("url")
    parsed_stream = urlparse(stripped)
    if parsed_stream.scheme.casefold() in {"rtsp", "rtmp", "mms"} and parsed_stream.hostname:
        types.add("stream-url")
    if re.fullmatch(r"[\w.%+-]+@[\w.-]+\.[A-Za-z]{2,}", stripped):
        types.add("email")
    if re.fullmatch(r"(?:\d{1,3}\.){3}\d{1,3}", stripped):
        octets = stripped.split(".")
        if all(int(octet) <= 255 for octet in octets):
            types.add("ip")
    if re.fullmatch(r"[\d\s,.+\-*/^()%=<>]+", stripped) and any(
        char.isdigit() for char in stripped
    ):
        types.add("number")
    if re.fullmatch(r"#[0-9a-fA-F]{3,8}", stripped):
        types.add("color")
    if re.fullmatch(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}",
        stripped,
    ):
        types.add("uuid")
    if re.fullmatch(r"[0-9a-fA-F]{32}|[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", stripped):
        types.add("hash")
    if stripped[:1] in "[{" and stripped[-1:] in "]}":
        try:
            json.loads(stripped)
            types.add("json")
        except (ValueError, TypeError):
            pass
    if re.fullmatch(r"-?\d{1,3}(?:\.\d+)?\s*,\s*-?\d{1,3}(?:\.\d+)?", stripped):
        latitude, longitude = (float(value.strip()) for value in stripped.split(","))
        if -90 <= latitude <= 90 and -180 <= longitude <= 180:
            types.add("coordinates")
    if re.fullmatch(r"10\.\d{4,9}/\S+", stripped, re.IGNORECASE):
        types.add("doi")
    compact_isbn = re.sub(r"[-\s]", "", stripped)
    if re.fullmatch(r"(?:\d{9}[\dXx]|97[89]\d{10})", compact_isbn):
        types.add("isbn")
    if re.fullmatch(r"(?:\$|€|£|¥|CLP|USD|EUR|GBP)\s*\d[\d.,]*", stripped, re.I):
        types.add("currency")
    if re.fullmatch(
        r"(?:\d{4}-\d{2}-\d{2}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
        stripped,
    ):
        types.add("date")
    if re.fullmatch(r"(?:~?/|\./|\.\./)[^\0\n]+", stripped):
        types.add("path")
    if re.search(r"(?:error|exception|traceback|segmentation fault|failed:)", stripped, re.I):
        types.add("error")

    code_tokens = (
        "def ",
        "class ",
        "if ",
        "for ",
        "while ",
        "import ",
        "from ",
        "const ",
        "let ",
        "var ",
        "function ",
        "return ",
        "async ",
        "await ",
    )
    lines = text.splitlines()
    if any(token in text for token in code_tokens) or (
        len(lines) > 2 and any(line.startswith((" ", "\t")) for line in lines)
    ):
        types.add("code")
    return frozenset(types)
