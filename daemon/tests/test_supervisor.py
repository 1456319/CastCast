import unittest
from unittest.mock import MagicMock
from castcast.supervisor import Supervisor

class TestSupervisor(unittest.TestCase):
    def test_play_calls_media_command_with_play(self):
        """Verify play calls _media_command with {'type': 'PLAY'}"""
        supervisor = Supervisor("127.0.0.1")
        supervisor._media_command = MagicMock()

        supervisor.play()

        supervisor._media_command.assert_called_once_with({"type": "PLAY"})

    def test_invalid_media_session_id_for_pause_is_not_load_failed(self):
        events = []
        logs = []
        supervisor = Supervisor("127.0.0.1", on_event=lambda k, p: events.append((k, p)), logger=logs.append)
        supervisor._channel = MagicMock()
        supervisor._channel.connected = True
        supervisor._app_transport_id = "transport-1"
        supervisor._media_session_id = 8

        request_id = supervisor.pause()
        self.assertIsNotNone(request_id)

        handled = supervisor._handle_media({
            "type": "INVALID_REQUEST",
            "requestId": request_id,
            "reason": "INVALID_MEDIA_SESSION_ID",
        })

        self.assertTrue(handled)
        self.assertNotEqual(supervisor.status.state, "load_failed")
        self.assertIsNone(supervisor.status.media_session_id)
        self.assertIn(("command_failed", {"reason": "INVALID_MEDIA_SESSION_ID", "request": "PAUSE"}), events)
        self.assertTrue(any("media command failed: PAUSE" in line for line in logs))

    def test_invalid_request_for_load_is_load_failed(self):
        events = []
        supervisor = Supervisor("127.0.0.1", on_event=lambda k, p: events.append((k, p)))
        request_id = supervisor._next_request_id("LOAD")

        supervisor._handle_media({
            "type": "INVALID_REQUEST",
            "requestId": request_id,
            "reason": "INVALID_MEDIA_SESSION_ID",
        })

        self.assertEqual(supervisor.status.state, "load_failed")
        self.assertIn(("load_failed", {"reason": "INVALID_MEDIA_SESSION_ID", "request": "LOAD"}), events)

    def test_seek_sends_playback_start_and_clamps_duration(self):
        supervisor = Supervisor("127.0.0.1")
        supervisor._media_command = MagicMock()
        supervisor.status.duration = 100.0

        supervisor.seek(50.0)
        supervisor._media_command.assert_called_with({
            "type": "SEEK",
            "currentTime": 50.0,
            "resumeState": "PLAYBACK_START",
        })

        # Clamping to duration - 2.0s
        supervisor.seek(99.5)
        supervisor._media_command.assert_called_with({
            "type": "SEEK",
            "currentTime": 98.0,
            "resumeState": "PLAYBACK_START",
        })

        # Clamping negative to 0.0
        supervisor.seek(-10.0)
        supervisor._media_command.assert_called_with({
            "type": "SEEK",
            "currentTime": 0.0,
            "resumeState": "PLAYBACK_START",
        })

    def test_snapshot_sanitizes_nan_and_inf_for_valid_json(self):
        import json
        import math
        supervisor = Supervisor("127.0.0.1")
        supervisor.status.duration = float("nan")
        supervisor.status.position = float("nan")
        supervisor.status.volume = float("inf")

        snap = supervisor.snapshot()
        self.assertFalse(math.isnan(snap["duration"]))
        self.assertFalse(math.isnan(snap["position"]))
        self.assertFalse(math.isinf(snap["volume"]))
        self.assertEqual(snap["duration"], 0.0)
        self.assertEqual(snap["position"], 0.0)
        self.assertEqual(snap["volume"], 0.0)

        # Must serialize with allow_nan=False without raising ValueError
        json_str = json.dumps(snap, allow_nan=False)
        self.assertNotIn("NaN", json_str)
        self.assertNotIn("Infinity", json_str)

    def test_handle_media_status_sanitizes_nan_duration_and_time(self):
        import math
        supervisor = Supervisor("127.0.0.1")
        supervisor._handle_media({
            "type": "MEDIA_STATUS",
            "status": [{
                "mediaSessionId": 1,
                "playerState": "PLAYING",
                "currentTime": float("nan"),
                "media": {
                    "duration": float("nan"),
                },
                "volume": {
                    "level": float("nan"),
                }
            }]
        })
        self.assertFalse(math.isnan(supervisor.status.duration))
        self.assertFalse(math.isnan(supervisor.status.position))
        self.assertFalse(math.isnan(supervisor.status.volume))
        self.assertEqual(supervisor.status.duration, 0.0)
        self.assertEqual(supervisor.status.position, 0.0)
        self.assertEqual(supervisor.status.volume, 0.0)

    def test_api_json_sanitizes_nested_tuples_and_floats(self):
        import io
        import json
        import math
        from castcast.api import _Handler

        handler = _Handler.__new__(_Handler)
        handler.wfile = io.BytesIO()
        handler.headers = {}
        handler.send_response = lambda code: None
        handler.send_header = lambda k, v: None
        handler.end_headers = lambda: None
        handler._cors = lambda: None

        payload = {
            "coords": (float("nan"), float("inf"), 42.0),
            "nested": [{"val": (float("-inf"), 1.0)}]
        }
        handler._json(payload)
        output = handler.wfile.getvalue().decode("utf-8")
        parsed = json.loads(output)
        self.assertEqual(parsed["coords"], [0.0, 0.0, 42.0])
        self.assertEqual(parsed["nested"][0]["val"], [0.0, 1.0])

    def test_load_while_playing_sends_load_to_active_transport(self):
        from castcast.supervisor import State, NS_MEDIA
        supervisor = Supervisor("127.0.0.1")
        supervisor._channel = MagicMock()
        supervisor._channel.connected = True
        supervisor._app_transport_id = "transport-123"
        supervisor._media_session_id = 42
        supervisor._state = State.PLAYING

        supervisor.load("http://example.com/next.mpd", title="Next Video")

        # Verify LOAD was sent to transport-123 instead of being dropped
        sent_calls = [
            c for c in supervisor._channel.send_json.call_args_list
            if c.args[0] == NS_MEDIA and c.args[1] == "transport-123" and c.args[2].get("type") == "LOAD"
        ]
        self.assertEqual(len(sent_calls), 1)
        self.assertEqual(supervisor._state, State.LOADING)

    def test_poll_media_status_recovers_missing_session_id(self):
        from castcast.supervisor import State, NS_MEDIA
        supervisor = Supervisor("127.0.0.1")
        supervisor._channel = MagicMock()
        supervisor._channel.connected = True
        supervisor._app_transport_id = "transport-123"
        supervisor._media_session_id = None
        supervisor._state = State.PLAYING
        supervisor._last_status_poll = 0.0

        supervisor._maybe_poll_status()

        # Should send GET_STATUS without requiring mediaSessionId
        sent_calls = [
            c for c in supervisor._channel.send_json.call_args_list
            if c.args[0] == NS_MEDIA and c.args[1] == "transport-123" and c.args[2].get("type") == "GET_STATUS"
        ]
        self.assertEqual(len(sent_calls), 1)


    def test_load_while_loading_sends_load_to_active_transport(self):
        from castcast.supervisor import State, NS_MEDIA
        supervisor = Supervisor("127.0.0.1")
        supervisor._channel = MagicMock()
        supervisor._channel.connected = True
        supervisor._app_transport_id = "transport-123"
        supervisor._media_session_id = None
        supervisor._state = State.LOADING

        supervisor.load("http://example.com/rapid_tap.mpd", title="Rapid Tap Replacement")

        # Verify LOAD was sent to transport-123 instead of being dropped
        sent_calls = [
            c for c in supervisor._channel.send_json.call_args_list
            if c.args[0] == NS_MEDIA and c.args[1] == "transport-123" and c.args[2].get("type") == "LOAD"
        ]
        self.assertEqual(len(sent_calls), 1)
        self.assertEqual(supervisor._state, State.LOADING)

    def test_poll_media_status_recovers_missing_session_id_when_paused(self):
        from castcast.supervisor import State, NS_MEDIA
        supervisor = Supervisor("127.0.0.1")
        supervisor._channel = MagicMock()
        supervisor._channel.connected = True
        supervisor._app_transport_id = "transport-123"
        supervisor._media_session_id = None
        supervisor._state = State.PAUSED
        supervisor._last_status_poll = 0.0

        supervisor._maybe_poll_status()

        # Should send GET_STATUS without requiring mediaSessionId even when paused
        sent_calls = [
            c for c in supervisor._channel.send_json.call_args_list
            if c.args[0] == NS_MEDIA and c.args[1] == "transport-123" and c.args[2].get("type") == "GET_STATUS"
        ]
        self.assertEqual(len(sent_calls), 1)


if __name__ == '__main__':
    unittest.main()

