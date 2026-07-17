"""Lightweight magnet, remote torrent and local media integrations."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path


def normalize_magnet(value: str) -> str:
    value = str(value or "").strip()
    if len(value) > 16_384 or not value.casefold().startswith("magnet:?"):
        return ""
    parsed = urllib.parse.urlsplit(value)
    values = urllib.parse.parse_qs(parsed.query, keep_blank_values=False)
    xt = values.get("xt", [])
    if not any(item.casefold().startswith(("urn:btih:", "urn:btmh:")) for item in xt):
        return ""
    return value


def normalize_media_url(value: str) -> str:
    value = str(value or "").strip()
    if len(value) > 16_384:
        return ""
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme.casefold() not in {"http", "https", "rtsp", "rtmp", "mms"}:
        return ""
    return value if parsed.hostname else ""


def default_desktop_handler(mime_type: str) -> str:
    if not shutil.which("xdg-mime"):
        return ""
    try:
        result = subprocess.run(
            ["xdg-mime", "query", "default", mime_type],
            capture_output=True,
            text=True,
            timeout=1,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""


def _desktop_file(desktop_id: str) -> Path | None:
    roots = (
        Path.home() / ".local/share/applications",
        Path("/usr/local/share/applications"),
        Path("/usr/share/applications"),
        Path("/var/lib/flatpak/exports/share/applications"),
        Path.home() / ".local/share/flatpak/exports/share/applications",
    )
    return next((root / desktop_id for root in roots if (root / desktop_id).is_file()), None)


def media_player_command(url: str) -> tuple[list[str], str]:
    url = normalize_media_url(url)
    if not url:
        raise ValueError("El texto seleccionado no es una URL multimedia compatible.")
    desktop_id = default_desktop_handler("video/mp4")
    desktop_file = _desktop_file(desktop_id) if desktop_id else None
    if desktop_file is not None:
        source = desktop_file.read_text(encoding="utf-8", errors="replace")
        if re.search(r"^Categories=.*(?:AudioVideo|Player|Video)", source, re.M | re.I):
            if shutil.which("gio"):
                return ["gio", "launch", str(desktop_file), url], desktop_id
            if shutil.which("gtk-launch"):
                return ["gtk-launch", desktop_id, url], desktop_id
    for executable in ("mpv", "vlc", "celluloid", "haruna", "smplayer"):
        if shutil.which(executable):
            return [executable, url], executable
    raise RuntimeError("No se encontró un reproductor multimedia local compatible.")


def normalize_torrent_servers(value) -> list[dict]:
    if not isinstance(value, list):
        return []
    result = []
    for raw in value[:10]:
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get("type", "")).strip().casefold()
        name = str(raw.get("name", "")).strip()[:64]
        endpoint = str(raw.get("endpoint", "")).strip()[:2048].rstrip("/")
        parsed = urllib.parse.urlsplit(endpoint)
        if kind not in {"qbittorrent", "transmission"} or not name:
            continue
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            continue
        result.append(
            {
                "name": name,
                "type": kind,
                "endpoint": endpoint,
                "username": str(raw.get("username", ""))[:256],
                "password": str(raw.get("password", ""))[:512],
            }
        )
    return result


def send_magnet_to_server(server: dict, magnet: str, timeout: float = 4.0) -> str:
    servers = normalize_torrent_servers([server])
    magnet = normalize_magnet(magnet)
    if not servers or not magnet:
        raise ValueError("Servidor o enlace magnet inválido.")
    server = servers[0]
    if server["type"] == "qbittorrent":
        return _send_qbittorrent(server, magnet, timeout)
    return _send_transmission(server, magnet, timeout)


def _send_qbittorrent(server: dict, magnet: str, timeout: float) -> str:
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(CookieJar())
    )
    endpoint = server["endpoint"]
    if server["username"]:
        payload = urllib.parse.urlencode(
            {"username": server["username"], "password": server["password"]}
        ).encode()
        with opener.open(
            urllib.request.Request(f"{endpoint}/api/v2/auth/login", data=payload),
            timeout=timeout,
        ) as response:
            if response.read(32).strip() != b"Ok.":
                raise RuntimeError("qBittorrent rechazó las credenciales.")
    payload = urllib.parse.urlencode({"urls": magnet}).encode()
    with opener.open(
        urllib.request.Request(f"{endpoint}/api/v2/torrents/add", data=payload),
        timeout=timeout,
    ) as response:
        if response.status not in {200, 201}:
            raise RuntimeError(f"qBittorrent respondió HTTP {response.status}.")
        response.read(256)
    return f"Magnet enviado a {server['name']}"


def _send_transmission(server: dict, magnet: str, timeout: float) -> str:
    endpoint = server["endpoint"]
    if not endpoint.casefold().endswith("/transmission/rpc"):
        endpoint += "/transmission/rpc"
    data = json.dumps(
        {"method": "torrent-add", "arguments": {"filename": magnet}}
    ).encode()
    headers = {"Content-Type": "application/json"}
    if server["username"]:
        import base64

        token = base64.b64encode(
            f"{server['username']}:{server['password']}".encode()
        ).decode()
        headers["Authorization"] = f"Basic {token}"

    def request(session_id=""):
        current = dict(headers)
        if session_id:
            current["X-Transmission-Session-Id"] = session_id
        return urllib.request.urlopen(
            urllib.request.Request(endpoint, data=data, headers=current),
            timeout=timeout,
        )

    try:
        response = request()
    except urllib.error.HTTPError as exc:
        if exc.code != 409:
            raise
        response = request(exc.headers.get("X-Transmission-Session-Id", ""))
    with response:
        body = json.loads(response.read(1_000_001))
    if body.get("result") != "success":
        raise RuntimeError(f"Transmission rechazó el magnet: {body.get('result', 'error')}")
    return f"Magnet enviado a {server['name']}"
