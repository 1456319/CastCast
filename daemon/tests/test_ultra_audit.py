"""Regressions for protocol, quality and synchronization audit findings.

No real Cast device, provider account, TLS tunnel or encrypted media is used.
"""
import copy
import http.client
import io
import json
import os
import socket
import struct
import subprocess
import threading
import time
from http.server import ThreadingHTTPServer
from unittest.mock import MagicMock, patch
from urllib.parse import urlsplit

import pytest

from castcast.channel import CastChannel, ChannelClosed, NS_MEDIA, NS_CONNECTION, NS_SHAKA, DEFAULT_MEDIA_RECEIVER_APP_ID, SHAKA_RECEIVER_APP_ID
from castcast.protobuf import CastMessage
from castcast.supervisor import Supervisor, State
from castcast.service import CastService
from castcast.mediaserver import MediaServer, _LicenseHandler, _ProxyRedirect, _validate_proxy_target, transform_dash_manifest
from castcast.probe import probe, _normalise_level, _normalise_container, MediaInfo, VideoStream
from castcast.capability import evaluate
from castcast.remux import Remuxer, RemuxPlan, RemuxJob, build_plan


@pytest.fixture
def supervisor():
    sup = Supervisor("192.168.1.25")
    sup._channel = MagicMock()
    sup._app_transport_id = "transport-1"
    sup.status.app_id = DEFAULT_MEDIA_RECEIVER_APP_ID
    sup._state = State.READY
    sup.status.state = "ready"
    return sup


@pytest.fixture
def service(tmp_path):
    svc = CastService({"media_roots": [str(tmp_path / "media")], "work_dir": str(tmp_path / "state")})
    os.makedirs(svc.media_roots[0])
    return svc


def item(path, item_id=None):
    result = {"media": {"contentId": "http://192.168.1.2/" + path, "contentType": "video/mp4", "customData": {"sourcePath": path}, "tracks": [{"trackId": 3}]}, "autoplay": True}
    if item_id is not None:
        result["itemId"] = item_id
    return result


def last_media(sup):
    return [c.args[2] for c in sup._channel.send_json.call_args_list if c.args[0] == NS_MEDIA][-1]


def test_partial_cast_frame_survives_socket_timeout():
    original = CastMessage("receiver-0", "sender-0", NS_MEDIA, '{"type":"MEDIA_STATUS","status":[]}')
    body = original.encode()
    wire = struct.pack("!I", len(body)) + body
    class FragmentedSocket:
        def __init__(self):
            self.data = [wire[:2], socket.timeout(), wire[2:9], socket.timeout(), wire[9:]]
        def settimeout(self, timeout):
            pass
        def recv(self, count):
            chunk = self.data.pop(0)
            if isinstance(chunk, Exception):
                raise chunk
            if len(chunk) > count:
                self.data.insert(0, chunk[count:])
            return chunk[:count]
    channel = CastChannel("unused")
    channel._sock = FragmentedSocket()
    with pytest.raises(socket.timeout):
        channel.receive(.1)
    with pytest.raises(socket.timeout):
        channel.receive(.1)
    assert channel.receive(.1).payload_utf8 == original.payload_utf8
    assert not channel._receive_buffer


def test_oversize_cast_command_is_rejected_before_socket_write():
    channel = CastChannel("unused")
    channel._sock = MagicMock()
    with pytest.raises(ChannelClosed, match="64 KiB"):
        channel.send_json(NS_MEDIA, "app", {"large": "x" * 65536})
    channel._sock.sendall.assert_not_called()


def test_replacing_playing_media_sends_load(supervisor):
    supervisor._state = State.PLAYING
    supervisor.load("http://media/new.mp4")
    assert last_media(supervisor)["type"] == "LOAD"
    assert supervisor.status.state == "loading"


def test_drm_selects_shaka_instead_of_queue_receiver(supervisor):
    supervisor.load("http://media/video.mpd", license_url="https://license.example", require_4k=True)
    messages = [c.args[2] for c in supervisor._channel.send_json.call_args_list]
    assert any(p.get("type") == "LAUNCH" and p["appId"] == SHAKA_RECEIVER_APP_ID for p in messages)
    assert not any(p.get("type") == "LOAD" for p in messages)


def test_queue_restore_strips_ids_preserves_index_time_pause(supervisor):
    original = [item("a", 51), item("b", 97)]
    supervisor.queue_load(original, start_index=1, position=83.5, autoplay=False)
    command = last_media(supervisor)
    assert command["type"] == "QUEUE_LOAD"
    assert command["startIndex"] == 1 and command["currentTime"] == 83.5
    assert command["items"][1]["autoplay"] is False
    assert all("itemId" not in i for i in command["items"])
    assert original[0]["itemId"] == 51
    assert "mediaSessionId" not in command


def test_partial_status_retains_tracks_and_current_queue_metadata(supervisor):
    supervisor.queue_load([item("a"), item("b")])
    remote = [item("a", 15), item("b", 28)]
    supervisor._handle_media({"type": "MEDIA_STATUS", "status": [{"mediaSessionId": 9, "items": remote, "currentItemId": 28, "playerState": "PAUSED", "activeTrackIds": [3]}]})
    supervisor._handle_media({"type": "MEDIA_STATUS", "status": [{"currentTime": 2}]})
    assert supervisor.status.source_path == "b"
    assert supervisor.status.content_url.endswith("/b")
    assert supervisor.status.text_tracks == 1
    assert supervisor.status.active_track_ids == [3]
    assert supervisor.status.state == "paused"


def test_native_finish_does_not_invoke_unrelated_auto_advance(supervisor):
    supervisor._on_finished = MagicMock()
    supervisor.queue_load([item("a")])
    supervisor._handle_media({"type": "MEDIA_STATUS", "status": [{"playerState": "IDLE", "idleReason": "FINISHED"}]})
    supervisor._on_finished.assert_not_called()


def test_stale_app_messages_and_platform_close(supervisor):
    assert supervisor._handle(CastMessage("old-app", "sender-0", NS_CONNECTION, '{"type":"CLOSE"}'))
    assert supervisor._app_transport_id == "transport-1"
    assert supervisor._handle(CastMessage("old-app", "sender-0", NS_MEDIA, '{"type":"MEDIA_STATUS","status":[{"mediaSessionId":666}]}'))
    assert supervisor._media_session_id is None
    assert not supervisor._handle(CastMessage("receiver-0", "sender-0", NS_CONNECTION, '{"type":"CLOSE"}'))


def test_shaka_track_zero_uses_actual_receiver_track(supervisor):
    supervisor.status.app_id = SHAKA_RECEIVER_APP_ID
    track = {"id": 0, "language": "en", "active": False}
    supervisor._handle_shaka({"type": "update", "update": {"player": {"getTextTracks": [track]}}})
    supervisor.set_active_tracks([0])
    call = supervisor._channel.send_json.call_args.args
    assert call[0] == NS_SHAKA
    assert call[2] == {"type": "call", "targetName": "player", "methodName": "selectTextTrack", "args": [track]}
    assert supervisor.status.active_track_ids == []


def test_required_4k_pauses_receiver_reported_1080(supervisor):
    supervisor.load("http://media/movie.mp4", require_4k=True)
    supervisor._handle_media({"type": "MEDIA_STATUS", "status": [{"mediaSessionId": 1, "playerState": "PLAYING", "videoInfo": {"width": 1920, "height": 1080}}]})
    assert last_media(supervisor)["type"] == "PAUSE"
    assert supervisor.status.quality_state == "below_4k"
    assert "4K required" in supervisor.status.last_error


def test_loading_has_bounded_timeout(supervisor):
    supervisor.load("http://media/movie.mp4")
    supervisor._load_sent_at = time.monotonic() - 46
    supervisor._maybe_poll_status()
    assert supervisor.status.state == "load_failed"


def test_identical_position_updates_do_not_mask_stall(supervisor):
    supervisor.load("http://media/movie.mp4")
    status = {"type": "MEDIA_STATUS", "status": [{"mediaSessionId": 1, "playerState": "PLAYING", "currentTime": 10}]}
    supervisor._handle_media(status)
    supervisor._last_progress_at = time.monotonic() - 100
    supervisor._handle_media(status)
    supervisor._maybe_poll_status()
    assert supervisor.status.stream_stalls == 1


def test_caption_reload_keeps_full_queue_and_paused_position(supervisor):
    supervisor.queue_load([item("a"), item("b")], start_index=1, position=50, autoplay=False)
    supervisor._state = State.PAUSED
    supervisor.replace_text_tracks([{"trackId": 7}], [7])
    command = last_media(supervisor)
    assert command["type"] == "QUEUE_LOAD" and len(command["items"]) == 2
    assert command["startIndex"] == 1 and command["currentTime"] == 50
    assert command["items"][1]["activeTrackIds"] == [7]
    assert command["items"][1]["autoplay"] is False


def test_trash_waits_for_ack_and_matches_full_source(service, tmp_path):
    source = tmp_path / "media" / "movie.mp4"
    source.write_bytes(b"keep until ack")
    sup = MagicMock()
    sup._session.queue_items = [item(str(source), 2), item("other/movie.mp4", 3)]
    service.supervisor = sup
    sup.wait_for_request.side_effect = RuntimeError("rejected")
    with pytest.raises(RuntimeError, match="rejected"):
        service.trash(str(source))
    assert source.exists()
    sup.queue_remove.assert_called_once_with([2])
    sup.wait_for_request.side_effect = None
    result = service.trash(str(source))
    assert not source.exists() and os.path.exists(result["trashed"])


def test_nested_trash_and_persisted_order(service, tmp_path):
    root = tmp_path / "media"
    a, b = root / "a.mp4", root / "b.mp4"
    a.write_bytes(b"a"); b.write_bytes(b"b")
    service.reorder_library([str(b), str(a)])
    reloaded = CastService(service.config)
    assert [i["path"] for i in reloaded.library()] == [str(b), str(a)]
    nested = root / "series" / "episode.mp4"
    nested.parent.mkdir(); nested.write_bytes(b"episode")
    result = service.trash(str(nested))
    assert result["trashed"] in [i["path"] for i in service.get_trash()]


def test_issued_file_urls_distinguish_roots_and_hide_unissued_files(tmp_path):
    roots = [tmp_path / "one", tmp_path / "two"]
    for n, root in enumerate(roots):
        root.mkdir(); (root / "same.mp4").write_bytes(str(n).encode())
    secret = roots[0] / "audit.log"; secret.write_text("private")
    server = MediaServer(roots, bind="127.0.0.1")
    server.start()
    try:
        urls = [server.url_for(str(r / "same.mp4")) for r in roots]
        assert urls[0] != urls[1]
        conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=2)
        for n, url in enumerate(urls):
            conn.request("GET", urlsplit(url).path, headers={"Range": "bytes=0-0"})
            response = conn.getresponse()
            assert response.status == 206 and response.read() == str(n).encode()
        conn.request("GET", f"/{server.root_token}/r0/audit.log")
        response = conn.getresponse(); assert response.status == 404; response.read()
        conn.close()
    finally:
        server.stop()


def test_license_listener_never_exposes_media_even_with_spoofed_host(tmp_path):
    server = MediaServer([tmp_path])
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _LicenseHandler)
    httpd.media_server = server
    thread = threading.Thread(target=httpd.serve_forever, daemon=True); thread.start()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=2)
        conn.request("GET", "/proxy/?url=anything", headers={"Host": "127.0.0.1"})
        response = conn.getresponse(); assert response.status == 404; response.read()
        conn.request("OPTIONS", "/amazon/license", headers={"Origin": "https://shaka-player-demo.appspot.com"})
        response = conn.getresponse(); assert response.status == 204
        assert response.getheader("Content-Length") == "0"; response.read()
        conn.request("POST", "/amazon/license?title_id=unknown&token=" + server.license_token, body=b"challenge")
        response = conn.getresponse(); assert response.status == 404
        assert response.getheader("Content-Length") == "0"; response.read()
        conn.close()
    finally:
        httpd.shutdown(); httpd.server_close()


def test_dns_and_redirect_validation_reject_control_targets():
    with patch("castcast.mediaserver.socket.getaddrinfo", return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))]):
        with pytest.raises(ValueError):
            _validate_proxy_target("http://rebind.example/api")
        import urllib.request
        with pytest.raises(ValueError):
            _ProxyRedirect().redirect_request(urllib.request.Request("https://media.example"), None, 302, "", {}, "http://rebind.example/status")


def test_probe_level_and_matroska_aliases():
    assert _normalise_level("hevc", 153) == 5.1
    assert _normalise_level("h264", 42) == 4.2
    assert _normalise_container("matroska,webm", "movie.mkv") == "matroska"
    assert _normalise_container("matroska,webm", "movie.webm") == "webm"


@pytest.mark.parametrize("video", [VideoStream(codec="h264", width=3840, height=2160, profile="High"), VideoStream(codec="hevc", width=3840, height=2160, profile="Rext", pix_fmt="yuv444p10le"), VideoStream(codec="h264", width=1920, height=1080, fps=120)])
def test_unsupported_video_is_not_treated_as_a_lossless_fix(video):
    result = evaluate(MediaInfo(path="a.mp4", container="mp4", video=[video]))
    assert result.needs_processing and result.video_action == "transcode"
    assert not result.will_be_4k


def test_queue_prepares_complete_order_before_any_load(service):
    service.supervisor = MagicMock()
    ready = {"verdict": {"needs_processing": False}, "media": {}}
    plan = RemuxPlan("second.mkv", "second.cast.mp4", args=["-c:v", "copy"])
    needs = {"verdict": {"needs_processing": True, "video_action": "copy"}, "plan": plan.to_dict(), "media": {}}
    gate, started, loaded = threading.Event(), threading.Event(), threading.Event()
    prepared = set()
    def preflight(path):
        return needs if path == "second.mkv" and path not in prepared else ready
    def run(plan, **kwargs):
        started.set(); assert gate.wait(3)
        prepared.add(plan.input_path)
        return RemuxJob(plan=plan, state="done")
    service.preflight = preflight
    service._remuxer.run = run
    service._scavenge_all_local_subtitles = lambda *args: []
    service.media_server.url_for = lambda path: "http://media/" + path
    service.supervisor.queue_load.side_effect = lambda *args, **kwargs: loaded.set()
    paths = ["first.mp4", "second.mkv", "third.mp4"]
    result = service.queue(paths)
    try:
        assert started.wait(1) and result["queued"] == 0
        service.supervisor.queue_load.assert_not_called()
    finally:
        gate.set()
    assert loaded.wait(3)
    actual = service.supervisor.queue_load.call_args.args[0]
    assert [i["media"]["customData"]["sourcePath"] for i in actual] == paths


def test_remux_real_4k_hevc_preserves_stream_and_publishes_atomically(tmp_path):
    source = tmp_path / "source.mkv"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=black:s=3840x2160:r=2", "-frames:v", "2", "-c:v", "libx265", "-preset", "ultrafast", "-x265-params", "pools=2:frame-threads=1:level-idc=5.1", "-pix_fmt", "yuv420p10le", "-color_primaries", "bt2020", "-color_trc", "smpte2084", "-colorspace", "bt2020nc", str(source)], check=True, capture_output=True, timeout=45)
    info = probe(str(source)); verdict = evaluate(info)
    assert info.primary_video.level == 5.1 and info.primary_video.is_4k
    plan = build_plan(info, verdict, str(tmp_path / "work"))
    assert plan and plan.lossless_video
    job = Remuxer().run(plan, duration_s=1)
    assert job.state == "done", job.error
    output = probe(plan.output_path)
    assert output.primary_video.is_4k and output.primary_video.color_transfer == "smpte2084"
    assert not evaluate(output).needs_processing
    assert not list((tmp_path / "work").glob("*.partial.*"))
    # Verify decoded frames match; file container bytes naturally differ.
    def hashes(path):
        result = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-map", "0:v:0", "-f", "framemd5", "-"], check=True, capture_output=True, timeout=30)
        return [line.rsplit(b",", 1)[-1] for line in result.stdout.splitlines() if not line.startswith(b"#")]
    assert hashes(str(source)) == hashes(plan.output_path)
    complete = open(plan.output_path, "rb").read()
    broken = copy.deepcopy(plan); broken.args += ["-definitely-invalid-option"]
    failed = Remuxer().run(broken)
    assert failed.state == "failed"
    assert open(plan.output_path, "rb").read() == complete


def test_control_api_rejects_browser_origin_and_invalid_numbers(service):
    from castcast.api import ApiServer
    api = ApiServer(service, host="127.0.0.1", port=0)
    api.start()
    service.trash = MagicMock()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", api.port, timeout=2)
        conn.request("POST", "/trash", body='{"path":"/media/movie.mp4"}', headers={"Origin": "https://untrusted.example", "Content-Type": "application/json"})
        response = conn.getresponse(); assert response.status == 403; response.read()
        service.trash.assert_not_called()
        conn.request("POST", "/seek", body='{"position":NaN}', headers={"Origin": "http://localhost", "Content-Type": "application/json"})
        response = conn.getresponse(); assert response.status == 400; response.read()
        conn.request("OPTIONS", "/queue", headers={"Origin": "http://localhost"})
        response = conn.getresponse(); assert response.status == 204
        assert response.getheader("Access-Control-Allow-Origin") == "http://localhost"
        response.read(); conn.close()
    finally:
        api.stop()


def test_proxy_hls_rewrites_keys_maps_audio_and_signed_children(service):
    from castcast.mediaserver import _Handler
    handler = _Handler.__new__(_Handler)
    handler.server = MagicMock(media_server=service.media_server)
    service.media_server._httpd = MagicMock(server_address=("127.0.0.1", 9999))
    url = service.media_server.proxy_url_for("https://cdn.example/master.m3u8?signature=original")
    handler.path = urlsplit(url).path + "?" + urlsplit(url).query
    handler.headers = {"Host": "192.168.1.2:9999"}
    handler.wfile = io.BytesIO()
    handler.send_response = MagicMock(); handler.send_header = MagicMock(); handler.end_headers = MagicMock()
    manifest = b'#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="key?sig=abc"\n#EXT-X-MAP:URI="init.mp4"\n#EXT-X-MEDIA:TYPE=AUDIO,URI="audio.m3u8"\nvideo.m3u8?token=abc\n'
    response = MagicMock(headers={"Content-Type": "application/vnd.apple.mpegurl"})
    response.geturl.return_value = "https://cdn.example/redirect/master.m3u8?signature=new"
    response.read.return_value = manifest
    response.__enter__.return_value = response
    opener = MagicMock(); opener.open.return_value = response
    with patch("castcast.mediaserver._validate_proxy_target"), patch("urllib.request.build_opener", return_value=opener):
        handler._serve_proxy()
    rewritten = handler.wfile.getvalue().decode()
    assert rewritten.count("/proxy/?") == 4
    assert rewritten.count("token=" + service.media_server.root_token) == 4
    assert "AES-128" in rewritten  # Encryption is retained, not removed.


def test_unsolicited_request_zero_is_not_a_stale_command(supervisor):
    supervisor.load("http://media/movie.mp4")
    supervisor._handle_media({"type": "MEDIA_STATUS", "requestId": 0, "status": [{"mediaSessionId": 8, "playerState": "PLAYING", "currentTime": 12}]})
    assert supervisor.status.state == "playing"
    assert supervisor.status.position == 12
