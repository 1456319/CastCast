import json
import socket
import struct
import unittest
from unittest.mock import MagicMock
import pytest

from castcast.channel import (
    CastChannel,
    ChannelClosed,
    DEFAULT_MEDIA_RECEIVER_APP_ID,
    NS_MEDIA,
    PLATFORM_SENDER,
    SHAKA_RECEIVER_APP_ID,
)
from castcast.protobuf import CastMessage

class TestCastChannel(unittest.TestCase):
    def test_send_json(self):
        channel = CastChannel("127.0.0.1")
        channel.send = MagicMock()

        namespace = "test_namespace"
        destination = "test_destination"
        payload = {"key": "value"}

        channel.send_json(namespace, destination, payload)

        channel.send.assert_called_once()
        args, kwargs = channel.send.call_args
        self.assertEqual(len(args), 1)
        message = args[0]
        self.assertIsInstance(message, CastMessage)
        self.assertEqual(message.namespace, namespace)
        self.assertEqual(message.source_id, PLATFORM_SENDER)
        self.assertEqual(message.destination_id, destination)
        self.assertEqual(message.payload_utf8, json.dumps(payload, separators=(",", ":")))

    def test_send_binary(self):
        channel = CastChannel("127.0.0.1")
        channel.send = MagicMock()

        namespace = "test_namespace"
        destination = "test_destination"
        payload = b"test payload"

        channel.send_binary(namespace, destination, payload)

        channel.send.assert_called_once()
        args, kwargs = channel.send.call_args
        self.assertEqual(len(args), 1)
        message = args[0]
        self.assertIsInstance(message, CastMessage)
        self.assertEqual(message.namespace, namespace)
        self.assertEqual(message.source_id, PLATFORM_SENDER)
        self.assertEqual(message.destination_id, destination)
        self.assertEqual(message.payload_binary, payload)


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
        channel.receive(0.1)
    with pytest.raises(socket.timeout):
        channel.receive(0.1)
    msg = channel.receive(0.1)
    assert msg.namespace == NS_MEDIA
    assert msg.payload_utf8 == original.payload_utf8


def test_outbound_frame_exceeding_max_len_raises():
    channel = CastChannel("unused")
    channel._sock = MagicMock()
    oversized = CastMessage("receiver-0", "sender-0", NS_MEDIA, "x" * 70000)
    with pytest.raises(ChannelClosed, match="exceeds 64 KiB"):
        channel.send(oversized)


def test_receiver_app_ids():
    assert DEFAULT_MEDIA_RECEIVER_APP_ID == "CC1AD845"
    assert SHAKA_RECEIVER_APP_ID == "07AEE832"


def test_supervisor_receiver_routing_and_replace_text_tracks():
    from castcast.supervisor import Supervisor, State
    sup = Supervisor("127.0.0.1")
    sup._channel = MagicMock()
    sup._channel.connected = True
    sup._channel.send_json = MagicMock()
    sup._set_state(State.CONNECTED)

    # 1. Local playback routes to DEFAULT_MEDIA_RECEIVER_APP_ID
    sup.load("http://127.0.0.1/video.mp4", title="Local Video")
    assert sup._session.receiver_app_id == DEFAULT_MEDIA_RECEIVER_APP_ID
    assert sup.receiver_app_id == DEFAULT_MEDIA_RECEIVER_APP_ID

    # 2. DRM playback routes to SHAKA_RECEIVER_APP_ID
    sup.load("http://127.0.0.1/video.mpd", title="DRM Video", license_url="https://license.server/widevine")
    assert sup._session.receiver_app_id == SHAKA_RECEIVER_APP_ID
    assert sup.receiver_app_id == SHAKA_RECEIVER_APP_ID

    # 3. replace_text_tracks on Shaka session must not raise RuntimeError and preserve state
    new_tracks = [{"trackId": 1, "type": "TEXT", "name": "English", "subtype": "SUBTITLES"}]
    sup.replace_text_tracks(new_tracks, active_ids=[1])
    assert sup._session.tracks == new_tracks
    assert sup._session.active_track_ids == [1]
    assert sup._session.license_url == "https://license.server/widevine"

