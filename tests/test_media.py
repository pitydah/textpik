import tempfile
import unittest
import urllib.error
import urllib.parse
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.textpik_core.media import (
    build_browser_workflow_url,
    import_userscript_workflow,
    media_player_command,
    normalize_magnet,
    normalize_media_url,
    normalize_torrent_servers,
    protect_torrent_server_credentials,
    resolve_torrent_server_credentials,
    send_magnet_to_server,
    check_torrent_server_connection,
)
from src.textpik_core.text import classify_text


MAGNET = "magnet:?xt=urn:btih:" + "a" * 40 + "&dn=TextPik"


class MediaIntegrationTest(unittest.TestCase):
    class Response:
        def __init__(self, body=b"{}", status=200):
            self.body = body
            self.status = status

        def read(self, _limit=-1):
            return self.body

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def test_torrent_password_moves_to_secret_service_and_resolves(self):
        server = {
            "name": "NAS", "type": "qbittorrent",
            "endpoint": "https://nas.local", "username": "textpik",
            "password": "private-password",
        }
        with (
            patch("src.textpik_core.media.shutil.which", return_value="/usr/bin/secret-tool"),
            patch(
                "src.textpik_core.media.subprocess.run",
                return_value=SimpleNamespace(stdout=""),
            ) as runner,
        ):
            secured = protect_torrent_server_credentials(server)
        self.assertEqual(secured["password"], "")
        self.assertTrue(secured["password_ref"])
        self.assertEqual(runner.call_args.kwargs["input"], "private-password")

        with (
            patch("src.textpik_core.media.shutil.which", return_value="/usr/bin/secret-tool"),
            patch(
                "src.textpik_core.media.subprocess.run",
                return_value=SimpleNamespace(stdout="private-password\n"),
            ),
        ):
            resolved = resolve_torrent_server_credentials(secured)
        self.assertEqual(resolved["password"], "private-password")

    class Opener:
        def __init__(self, response):
            self.response = response
            self.requests = []

        def open(self, request, timeout=None):
            self.requests.append((request, timeout))
            return self.response

    def test_magnet_validation_and_context_are_strict(self):
        self.assertEqual(normalize_magnet(MAGNET), MAGNET)
        self.assertIn("magnet", classify_text(MAGNET))
        self.assertEqual(normalize_magnet("magnet:?dn=missing-hash"), "")
        self.assertNotIn("magnet", classify_text("magnet:?dn=missing-hash"))

    def test_media_urls_reject_local_and_script_schemes(self):
        self.assertEqual(normalize_media_url("https://media.local/live.m3u8"), "https://media.local/live.m3u8")
        self.assertIn("stream-url", classify_text("rtsp://camera.local/live"))
        self.assertEqual(normalize_media_url("file:///etc/passwd"), "")
        self.assertEqual(normalize_media_url("javascript:alert(1)"), "")

    def test_torrent_server_settings_are_bounded_and_validated(self):
        servers = normalize_torrent_servers(
            [
                {"name": "NAS", "type": "transmission", "endpoint": "http://nas.local:9091/"},
                {"name": "Bad", "type": "unknown", "endpoint": "file:///tmp/api"},
            ]
        )
        self.assertEqual(len(servers), 1)
        self.assertEqual(servers[0]["endpoint"], "http://nas.local:9091")

    def test_native_server_workflow_options_are_normalized(self):
        server = normalize_torrent_servers(
            [
                {
                    "name": "NAS",
                    "type": "qbittorrent",
                    "endpoint": "https://nas.local/qbt",
                    "default": "yes",
                    "paused": True,
                    "download_dir": " /downloads/linux ",
                    "category": " ISOs ",
                    "tags": "linux, archive",
                    "sequential": 1,
                }
            ]
        )[0]
        self.assertTrue(server["default"])
        self.assertTrue(server["paused"])
        self.assertTrue(server["sequential"])
        self.assertEqual(server["download_dir"], "/downloads/linux")
        self.assertEqual(server["category"], "ISOs")

    def test_userscript_metadata_builds_a_browser_owned_workflow(self):
        with tempfile.TemporaryDirectory() as temporary:
            script = Path(temporary) / "nas.user.js"
            script.write_text(
                "\n".join(
                    (
                        "// ==UserScript==",
                        "// @name NAS importer",
                        "// @match https://nas.local/torrents/*",
                        "// @textpik-url https://nas.local/torrents/add?uri={magnet}&hash={hash}&name={name}",
                        "// ==/UserScript==",
                        "console.log('browser-owned');",
                    )
                ),
                encoding="utf-8",
            )
            imported = import_userscript_workflow(script)
        server = {
            **imported,
            "name": imported["name"],
            "type": "browser",
        }
        url = build_browser_workflow_url(server, MAGNET)
        values = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        self.assertEqual(values["uri"], [MAGNET])
        self.assertEqual(values["hash"], ["a" * 40])
        self.assertEqual(values["name"], ["TextPik"])
        self.assertEqual(imported["script_name"], "nas.user.js")

    def test_userscript_requires_an_explicit_or_derivable_browser_url(self):
        with tempfile.TemporaryDirectory() as temporary:
            script = Path(temporary) / "unsafe.user.js"
            script.write_text(
                "// ==UserScript==\n// @name No target\n// ==/UserScript==\n",
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                import_userscript_workflow(script)

    def test_default_video_desktop_is_used_without_shell(self):
        with tempfile.TemporaryDirectory() as temporary:
            desktop = Path(temporary) / "player.desktop"
            desktop.write_text("[Desktop Entry]\nCategories=AudioVideo;Player;\n", encoding="utf-8")
            with (
                patch("src.textpik_core.media.default_desktop_handler", return_value="player.desktop"),
                patch("src.textpik_core.media._desktop_file", return_value=desktop),
                patch("src.textpik_core.media.shutil.which", side_effect=lambda name: "/usr/bin/gio" if name == "gio" else None),
            ):
                argv, player = media_player_command("https://media.local/video.mp4")
        self.assertEqual(argv, ["gio", "launch", str(desktop), "https://media.local/video.mp4"])
        self.assertEqual(player, "player.desktop")

    def test_configured_media_player_takes_precedence(self):
        with patch(
            "src.textpik_core.media.shutil.which",
            side_effect=lambda name: "/usr/bin/mpv" if name == "mpv" else None,
        ):
            argv, player = media_player_command(
                "https://media.local/video.mp4", "mpv"
            )
        self.assertEqual(argv, ["/usr/bin/mpv", "https://media.local/video.mp4"])
        self.assertEqual(player, "mpv")

    def test_qbittorrent_connection_test_is_non_destructive(self):
        opener = self.Opener(self.Response(b"5.0.4"))
        with patch(
            "src.textpik_core.media.urllib.request.build_opener",
            return_value=opener,
        ):
            result = check_torrent_server_connection(
                {
                    "name": "NAS", "type": "qbittorrent",
                    "endpoint": "https://nas.local/qbt",
                }
            )
        self.assertEqual(result, "qBittorrent 5.0.4")
        request = opener.requests[0][0]
        self.assertIn("/api/v2/app/version", request)
        self.assertNotIn("/torrents/add", request)

    def test_transmission_retries_with_session_id_and_adds_magnet(self):
        conflict = urllib.error.HTTPError(
            "http://nas:9091/transmission/rpc",
            409,
            "Conflict",
            {"X-Transmission-Session-Id": "session-1"},
            None,
        )
        success = self.Response(b'{"result":"success","arguments":{}}')
        with patch(
            "src.textpik_core.media.urllib.request.urlopen",
            side_effect=[conflict, success],
        ) as opener:
            message = send_magnet_to_server(
                {
                    "name": "NAS",
                    "type": "transmission",
                    "endpoint": "http://nas:9091",
                },
                MAGNET,
            )
        self.assertEqual(message, "Magnet enviado a NAS")
        self.assertEqual(opener.call_count, 2)
        retry = opener.call_args_list[1].args[0]
        self.assertEqual(retry.get_header("X-transmission-session-id"), "session-1")
        arguments = json.loads(retry.data)["arguments"]
        self.assertFalse(arguments["paused"])

    def test_qbittorrent_receives_configured_workflow_form(self):
        opener = self.Opener(self.Response(b"Ok."))
        with patch(
            "src.textpik_core.media.urllib.request.build_opener",
            return_value=opener,
        ):
            send_magnet_to_server(
                {
                    "name": "NAS",
                    "type": "qbittorrent",
                    "endpoint": "https://nas.local/qbt",
                    "paused": True,
                    "sequential": True,
                    "download_dir": "/downloads/linux",
                    "category": "ISOs",
                    "tags": "linux, archive",
                },
                MAGNET,
            )
        request, timeout = opener.requests[0]
        values = urllib.parse.parse_qs(request.data.decode())
        self.assertEqual(timeout, 4.0)
        self.assertEqual(values["urls"], [MAGNET])
        self.assertEqual(values["savepath"], ["/downloads/linux"])
        self.assertEqual(values["category"], ["ISOs"])
        self.assertEqual(values["tags"], ["linux, archive"])
        self.assertEqual(values["paused"], ["true"])
        self.assertEqual(values["sequentialDownload"], ["true"])

    def test_transmission_receives_configured_workflow_arguments(self):
        success = self.Response(b'{"result":"success","arguments":{}}')
        with patch(
            "src.textpik_core.media.urllib.request.urlopen",
            return_value=success,
        ) as opener:
            send_magnet_to_server(
                {
                    "name": "NAS",
                    "type": "transmission",
                    "endpoint": "http://nas:9091",
                    "paused": True,
                    "download_dir": "/srv/torrents",
                    "category": "TextPik",
                    "tags": "linux, archive",
                },
                MAGNET,
            )
        arguments = json.loads(opener.call_args.args[0].data)["arguments"]
        self.assertTrue(arguments["paused"])
        self.assertEqual(arguments["download-dir"], "/srv/torrents")
        self.assertEqual(arguments["labels"], ["TextPik", "linux", "archive"])


if __name__ == "__main__":
    unittest.main()
