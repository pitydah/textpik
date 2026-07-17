import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from src.textpik_core.media import (
    media_player_command,
    normalize_magnet,
    normalize_media_url,
    normalize_torrent_servers,
    send_magnet_to_server,
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


if __name__ == "__main__":
    unittest.main()
