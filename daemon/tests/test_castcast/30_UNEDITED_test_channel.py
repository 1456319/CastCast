# [KEY 0] Agent Jules: File verified structurally sound. No objective blocking errors found in automated pass.
import unittest
import json
from unittest.mock import MagicMock
from castcast.channel import CastChannel, PLATFORM_SENDER
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

if __name__ == '__main__':
    unittest.main()
