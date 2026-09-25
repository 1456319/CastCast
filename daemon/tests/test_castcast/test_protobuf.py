import unittest
from castcast.protobuf import encode_varint

class TestProtobuf(unittest.TestCase):
    def test_encode_varint(self):
        # Happy paths
        self.assertEqual(encode_varint(0), b'\x00')
        self.assertEqual(encode_varint(1), b'\x01')
        self.assertEqual(encode_varint(127), b'\x7f')
        self.assertEqual(encode_varint(128), b'\x80\x01')
        self.assertEqual(encode_varint(300), b'\xac\x02')
        self.assertEqual(encode_varint(16384), b'\x80\x80\x01')

        # Error conditions
        with self.assertRaises(ValueError) as context:
            encode_varint(-1)
        self.assertEqual(str(context.exception), "negative varint")

        with self.assertRaises(ValueError) as context:
            encode_varint(-100)
        self.assertEqual(str(context.exception), "negative varint")

if __name__ == '__main__':
    unittest.main()
