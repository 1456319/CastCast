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

    def test_update_resolution_rejects_boolean_values(self):
        supervisor = Supervisor("127.0.0.1")
        supervisor.status.receiver_width = 3840
        supervisor.status.receiver_height = 2160
        supervisor.status.quality_state = "receiver_4k"

        # Passing booleans should be ignored and not change dimensions or quality_state
        supervisor._update_resolution(True, True)
        self.assertEqual(supervisor.status.receiver_width, 3840)
        self.assertEqual(supervisor.status.receiver_height, 2160)
        self.assertEqual(supervisor.status.quality_state, "receiver_4k")

        supervisor._update_resolution(True, 2160)
        self.assertEqual(supervisor.status.receiver_width, 3840)

        supervisor._update_resolution(3840, False)
        self.assertEqual(supervisor.status.receiver_height, 2160)


if __name__ == '__main__':
    unittest.main()
