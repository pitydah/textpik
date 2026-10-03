"""Lightweight magnet, remote torrent and local media integrations."""

from __future__ import annotations

import json
import hashlib
import re
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path


USERSCRIPT_MAX_BYTES = 256 * 1024
WORKFLOW_PLACEHOLDERS = ("{magnet}", "{hash}", "{name}")


def protect_torrent_server_credentials(server: dict) -> dict:
    """Move a torrent password to Secret Service when available."""
    server = dict(server)
    password = str(server.get("password", ""))
    if not password or not shutil.which("secret-tool"):
        return server
    identity = "|".join(
        str(server.get(key, "")) for key in ("type", "endpoint", "username", "name")
    )
    reference = hashlib.sha256(identity.encode()).hexdigest()[:32]
    try:
        subprocess.run(
            [
                "secret-tool", "store", "--label=TextPik torrent server",
                "application", "textpik", "torrent-server", reference,
            ],
            input=password, text=True, capture_output=True, timeout=5, check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return server
    server["password"] = ""
    server["password_ref"] = reference
    return server


def resolve_torrent_server_credentials(server: dict) -> dict:
    server = dict(server)
    reference = str(server.get("password_ref", ""))
    if server.get("password") or not reference or not shutil.which("secret-tool"):
        return server
    try:
        result = subprocess.run(
            [
                "secret-tool", "lookup", "application", "textpik",
                "torrent-server", reference,
            ],
            capture_output=True, text=True, timeout=3, check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return server
    server["password"] = result.stdout.rstrip("\n")[:512]
    return server


def delete_torrent_server_credentials(server: dict) -> None:
    reference = str(server.get("password_ref", ""))
    if not reference or not shutil.which("secret-tool"):
        return
    try:
        subprocess.run(
            [
                "secret-tool", "clear", "application", "textpik",
                "torrent-server", reference,
            ],
            capture_output=True, text=True, timeout=3, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        pass


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


def media_player_command(url: str, preferred: str = "auto") -> tuple[list[str], str]:
    url = normalize_media_url(url)
    if not url:
        raise ValueError("El texto seleccionado no es una URL multimedia compatible.")
    preferred = str(preferred or "auto").strip()
    if preferred != "auto":
        if not re.fullmatch(r"[A-Za-z0-9_.+-]{1,80}", preferred):
            raise ValueError("El reproductor configurado no es válido.")
        executable = shutil.which(preferred)
        if not executable:
            raise RuntimeError(f"El reproductor configurado no está instalado: {preferred}")
        return [executable, url], preferred
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


def _as_bool(value, fallback: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes", "on", "si", "sí"}
    return fallback


def normalize_browser_workflow_template(value: str) -> str:
    template = str(value or "").strip()[:16_384]
    probe = template
    for placeholder in WORKFLOW_PLACEHOLDERS:
        probe = probe.replace(placeholder, "textpik")
    if "{" in probe or "}" in probe:
        return ""
    parsed = urllib.parse.urlsplit(probe)
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
        return ""
    return template if "{magnet}" in template else ""


def import_userscript_workflow(path: str | Path) -> dict:
    """Read safe userscript metadata without evaluating its JavaScript."""
    source_path = Path(path).expanduser().resolve()
    if source_path.suffix.casefold() not in {".js", ".user.js"}:
        raise ValueError("Selecciona un userscript JavaScript (.user.js o .js).")
    try:
        if source_path.stat().st_size > USERSCRIPT_MAX_BYTES:
            raise ValueError("El userscript supera el límite de 256 KiB.")
        source = source_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise ValueError(f"No se pudo leer el userscript: {exc}") from exc

    metadata: dict[str, list[str]] = {}
    in_header = False
    for raw_line in source.splitlines()[:500]:
        line = raw_line.strip()
        if line == "// ==UserScript==":
            in_header = True
            continue
        if line == "// ==/UserScript==":
            break
        if not in_header:
            continue
        match = re.match(r"//\s*@([\w-]+)\s+(.+?)\s*$", line)
        if match:
            metadata.setdefault(match.group(1).casefold(), []).append(match.group(2))

    name = next(iter(metadata.get("name", [])), source_path.stem).strip()[:64]
    template = next(
        iter(metadata.get("textpik-url", []) or metadata.get("textpik-template", [])),
        "",
    )
    if not template:
        candidates = metadata.get("match", []) + metadata.get("include", [])
        for candidate in candidates:
            if not candidate.casefold().startswith(("http://", "https://")):
                continue
            parsed = urllib.parse.urlsplit(candidate)
            if not parsed.hostname or "*" in parsed.netloc:
                continue
            base = candidate.rstrip("*")
            separator = "&" if "?" in base else "?"
            template = f"{base}{separator}textpik_magnet={{magnet}}"
            break
    template = normalize_browser_workflow_template(template)
    if not template:
        raise ValueError(
            "El userscript necesita @textpik-url con una URL HTTP(S) que incluya {magnet}."
        )
    return {
        "name": name,
        "browser_url_template": template,
        "script_name": source_path.name[:128],
        "script_path": str(source_path)[:4096],
    }


def build_browser_workflow_url(server: dict, magnet: str) -> str:
    normalized = normalize_torrent_servers([server])
    magnet = normalize_magnet(magnet)
    if not normalized or normalized[0]["type"] != "browser" or not magnet:
        raise ValueError("Flujo de navegador o enlace magnet inválido.")
    server = normalized[0]
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(magnet).query)
    exact_topic = next(iter(query.get("xt", [])), "")
    info_hash = exact_topic.rsplit(":", 1)[-1] if exact_topic else ""
    display_name = next(iter(query.get("dn", [])), "")
    replacements = {
        "{magnet}": urllib.parse.quote(magnet, safe=""),
        "{hash}": urllib.parse.quote(info_hash, safe=""),
        "{name}": urllib.parse.quote(display_name, safe=""),
    }
    url = server["browser_url_template"]
    for placeholder, value in replacements.items():
        url = url.replace(placeholder, value)
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("El userscript produjo una URL de navegador inválida.")
    return url


def normalize_torrent_servers(value) -> list[dict]:
    if not isinstance(value, list):
        return []
    result = []
    for raw in value[:10]:
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get("type", "")).strip().casefold()
        name = str(raw.get("name", "")).strip()[:64]
        if kind not in {"qbittorrent", "transmission", "browser"} or not name:
            continue
        common = {
            "name": name,
            "type": kind,
            "default": _as_bool(raw.get("default", False)),
            "paused": _as_bool(raw.get("paused", False)),
            "download_dir": str(raw.get("download_dir", "")).strip()[:1024],
            "category": str(raw.get("category", "")).strip()[:128],
            "tags": str(raw.get("tags", "")).strip()[:256],
            "sequential": _as_bool(raw.get("sequential", False)),
        }
        if kind == "browser":
            template = normalize_browser_workflow_template(
                raw.get("browser_url_template", "")
            )
            if not template:
                continue
            result.append(
                {
                    **common,
                    "endpoint": "",
                    "username": "",
                    "password": "",
                    "password_ref": "",
                    "browser_url_template": template,
                    "script_name": str(raw.get("script_name", "")).strip()[:128],
                    "script_path": str(raw.get("script_path", "")).strip()[:4096],
                }
            )
            continue
        endpoint = str(raw.get("endpoint", "")).strip()[:2048].rstrip("/")
        parsed = urllib.parse.urlsplit(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            continue
        result.append(
            {
                **common,
                "endpoint": endpoint,
                "username": str(raw.get("username", ""))[:256],
                "password": str(raw.get("password", ""))[:512],
                "password_ref": str(raw.get("password_ref", ""))[:64],
                "browser_url_template": "",
                "script_name": "",
                "script_path": "",
            }
        )
    return result


def send_magnet_to_server(server: dict, magnet: str, timeout: float = 4.0) -> str:
    servers = normalize_torrent_servers([server])
    magnet = normalize_magnet(magnet)
    if not servers or not magnet:
        raise ValueError("Servidor o enlace magnet inválido.")
    server = servers[0]
    if server["type"] == "browser":
        raise ValueError("Los flujos de userscript deben abrirse en el navegador.")
    server = resolve_torrent_server_credentials(server)
    if server.get("password_ref") and not server.get("password"):
        raise RuntimeError("No se pudo desbloquear la contraseña del servidor.")
    if server["type"] == "qbittorrent":
        return _send_qbittorrent(server, magnet, timeout)
    return _send_transmission(server, magnet, timeout)


def check_torrent_server_connection(server: dict, timeout: float = 3.0) -> str:
    servers = normalize_torrent_servers([server])
    if not servers:
        raise ValueError("Configuración de servidor inválida.")
    server = resolve_torrent_server_credentials(servers[0])
    if server["type"] == "browser":
        return "Plantilla de userscript válida"
    endpoint = server["endpoint"]
    password = server.get("password", "")
    manager = urllib.request.HTTPPasswordMgrWithDefaultRealm()
    manager.add_password(None, endpoint, server.get("username", ""), password)
    opener = urllib.request.build_opener(urllib.request.HTTPBasicAuthHandler(manager))
    if server["type"] == "qbittorrent":
        cookies = CookieJar()
        opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(cookies),
            urllib.request.HTTPBasicAuthHandler(manager),
        )
        if server.get("username") or password:
            payload = urllib.parse.urlencode(
                {"username": server.get("username", ""), "password": password}
            ).encode()
            with opener.open(
                urllib.request.Request(f"{endpoint}/api/v2/auth/login", data=payload),
                timeout=timeout,
            ) as response:
                if response.read(128).strip() != b"Ok.":
                    raise RuntimeError("qBittorrent rechazó las credenciales.")
        with opener.open(f"{endpoint}/api/v2/app/version", timeout=timeout) as response:
            version = response.read(128).decode(errors="replace").strip()
        return f"qBittorrent {version or 'disponible'}"
    rpc = endpoint if endpoint.casefold().endswith("/transmission/rpc") else endpoint + "/transmission/rpc"
    data = json.dumps({"method": "session-get"}).encode()
    request = urllib.request.Request(rpc, data=data, headers={"Content-Type": "application/json"})
    try:
        response = opener.open(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        session_id = exc.headers.get("X-Transmission-Session-Id", "") if exc.code == 409 else ""
        if not session_id:
            raise
        request.add_header("X-Transmission-Session-Id", session_id)
        response = opener.open(request, timeout=timeout)
    with response:
        body = json.loads(response.read(100_001))
    if body.get("result") != "success":
        raise RuntimeError("Transmission rechazó la conexión.")
    version = body.get("arguments", {}).get("version", "")
    return f"Transmission {version or 'disponible'}"


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
    values = {"urls": magnet}
    if server["download_dir"]:
        values["savepath"] = server["download_dir"]
    if server["category"]:
        values["category"] = server["category"]
    if server["tags"]:
        values["tags"] = server["tags"]
    if server["paused"]:
        values["paused"] = "true"
    if server["sequential"]:
        values["sequentialDownload"] = "true"
    payload = urllib.parse.urlencode(values).encode()
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
    arguments = {"filename": magnet, "paused": server["paused"]}
    if server["download_dir"]:
        arguments["download-dir"] = server["download_dir"]
    labels = [value.strip() for value in server["tags"].split(",") if value.strip()]
    if server["category"]:
        labels.insert(0, server["category"])
    if labels:
        arguments["labels"] = list(dict.fromkeys(labels))[:16]
    data = json.dumps({"method": "torrent-add", "arguments": arguments}).encode()
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
