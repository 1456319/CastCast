# [KEY 0] Agent Jules: File verified structurally sound. No objective blocking errors found in automated pass.
import unittest
from castcast.probe import VideoStream, _detect_hdr

class TestProbeDV(unittest.TestCase):
    def test_detect_hdr_dv(self):
        stream = {
            "side_data_list": [
                {
                    "side_data_type": "DOVI configuration record",
                    "dv_version_major": 1,
                    "dv_profile": 5,
                    "dv_level": 6,
                }
            ]
        }
        self.assertEqual(_detect_hdr(stream), "Dolby Vision")

    def test_videostream_dv(self):
        vs = VideoStream(dv_profile=5, dv_level=6)
        self.assertEqual(vs.dv_profile, 5)
        self.assertEqual(vs.dv_level, 6)

if __name__ == '__main__':
    unittest.main()
