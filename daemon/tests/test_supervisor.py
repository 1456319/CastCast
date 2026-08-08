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

if __name__ == '__main__':
    unittest.main()
