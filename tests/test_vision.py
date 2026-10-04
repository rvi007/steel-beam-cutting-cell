"""Camera + person detection. The YOLO maths always runs; the camera loop only if OpenCV is installed."""
import os
import tempfile
import time
import unittest

import numpy as np

from beamcell.vision import Vision, nms, parse_yolo

try:
    import cv2
except ImportError:
    cv2 = None


class Yolo(unittest.TestCase):
    def test_v8_output(self):
        out = np.zeros((1, 84, 3), np.float32)
        out[0, :4, 0] = [320, 320, 100, 200]; out[0, 4, 0] = 0.9            # a person
        out[0, :4, 1] = [322, 318, 104, 204]; out[0, 4, 1] = 0.6            # same person again
        out[0, :4, 2] = [100, 100, 50, 50]; out[0, 6, 2] = 0.95             # a car
        people = parse_yolo(out, 1280, 720, 640)
        self.assertEqual(len(people), 1)
        x, y, w, h, s = people[0]
        self.assertAlmostEqual(float(x), 540)
        self.assertAlmostEqual(float(w), 200)

    def test_v5_output(self):
        out = np.zeros((1, 2, 85), np.float32)
        out[0, 0, :4] = [320, 320, 100, 200]; out[0, 0, 4] = 0.9; out[0, 0, 5] = 0.95
        self.assertEqual(len(parse_yolo(out, 640, 640, 640)), 1)

    def test_nms(self):
        self.assertEqual(nms([(0, 0, 10, 10), (1, 1, 10, 10), (50, 50, 5, 5)], np.array([0.9, 0.8, 0.7])), [0, 2])


@unittest.skipIf(cv2 is None, "OpenCV not installed")
class Camera(unittest.TestCase):
    def test_video_file_and_zone(self):
        path = os.path.join(tempfile.mkdtemp(), "clip.avi")
        w = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"MJPG"), 10, (320, 240))
        for i in range(10):
            w.write(np.full((240, 320, 3), 40 + i * 10, np.uint8))
        w.release()
        v = Vision(tempfile.mkdtemp())
        v.configure({"enabled": True, "source": path})
        for _ in range(60):
            if v.status()["has_frame"]:
                break
            time.sleep(0.1)
        st = v.status()
        v.configure({"zones": {"danger": [0.2, 0.2, 0.8, 0.8], "warning": [0.5, 0, 0.4, 1]}, "enabled": False})
        self.assertTrue(st["has_frame"], st)
        self.assertEqual(v.status()["zones"]["danger"], [0.2, 0.2, 0.8, 0.8])
        self.assertNotEqual(v.status()["zones"]["warning"], [0.5, 0, 0.4, 1])   # bad box ignored
        self.assertFalse(v.status()["enabled"])

    def test_missing_camera(self):
        v = Vision(tempfile.mkdtemp())
        v.configure({"enabled": True, "source": "/no/such/video.mp4"})
        for _ in range(30):
            if not v.status()["enabled"]:
                break
            time.sleep(0.1)
        self.assertIn("no such video file", v.status()["message"])



class Finding(unittest.TestCase):
    def test_list_cameras_and_help(self):
        from beamcell.vision import Vision, list_cameras
        cams = list_cameras()                                 # whatever this computer has (often none)
        self.assertTrue(all(c["kind"] in ("usb", "csi") for c in cams))
        msg = Vision._no_camera_help([], ["tried /dev/video0"])
        self.assertIn("no camera found", msg)
        self.assertIn("/dev/video", msg)
        self.assertIn("doctor", msg)


if __name__ == "__main__":
    unittest.main()
