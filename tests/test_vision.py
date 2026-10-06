"""Camera + person detection. The YOLO maths always runs; the camera loop only if OpenCV is installed."""
import ctypes
import os
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

import numpy as np

from beamcell.vision import Vision, nms, parse_yolo, parse_yolo_all

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


class Objects(unittest.TestCase):
    """YOLO finds people AND objects; objects lying in the bed zone are reported."""

    def yolo_out(self, rows):
        out = np.zeros((84, len(rows)), np.float32)            # YOLO11 layout: x, y, w, h, 80 class scores
        for i, (cx, cy, w, h, cls, score) in enumerate(rows):
            out[:4, i] = (cx, cy, w, h)
            out[4 + cls, i] = score
        return out[None]

    def test_people_and_objects(self):
        from beamcell.vision import COCO, parse_yolo_all, split
        out = self.yolo_out([(320, 200, 60, 200, 0, 0.9),                     # a person, feet at y=300
                             (320, 400, 40, 40, COCO.index("bottle"), 0.8),   # a bottle on the bed
                             (322, 401, 40, 40, COCO.index("bottle"), 0.7),   # the same bottle again (NMS)
                             (60, 60, 30, 30, COCO.index("cup"), 0.8)])       # a cup, off the bed
        dets = parse_yolo_all(out, 640, 640, 640)
        self.assertEqual(sorted(COCO[d[5]] for d in dets), ["bottle", "cup", "person"])
        people, objects = split(dets, [0.15, 0.45, 0.85, 0.85], 640, 640)
        self.assertEqual(len(people), 1)
        self.assertEqual([COCO[o[5]] for o in objects], ["bottle"])

    def test_people_only_parser_unchanged(self):
        out = self.yolo_out([(320, 200, 60, 200, 0, 0.9), (320, 400, 40, 40, 39, 0.8)])
        self.assertEqual(len(parse_yolo(out, 640, 640, 640)), 1)


class FakeCuda:
    """Stands in for libcudart: 'GPU memory' is ordinary memory, so the runner's plumbing can be tested."""

    def __init__(self):
        self.bufs = []

    def cudaStreamCreate(self, ref):
        ref._obj.value = 1
        return 0

    def cudaMalloc(self, ref, size):
        buf = ctypes.create_string_buffer(size.value)
        self.bufs.append(buf)
        ref._obj.value = ctypes.addressof(buf)
        return 0

    def cudaMemcpyAsync(self, dst, src, count, kind, stream):
        ctypes.memmove(dst.value, src.value, count.value)
        return 0

    def cudaStreamSynchronize(self, stream):
        return 0

    def cudaFree(self, ptr):
        return 0

    def cudaStreamDestroy(self, stream):
        return 0


def fake_tensorrt():
    """A tiny stand-in for the tensorrt module: an 'engine' that puts one person where the image is brightest."""
    trt = types.ModuleType("tensorrt")
    trt.__version__ = "10.fake"
    trt.Logger = type("Logger", (), {"WARNING": 2, "__init__": lambda self, level=2: None})
    trt.TensorIOMode = type("TensorIOMode", (), {"INPUT": "in", "OUTPUT": "out"})
    trt.nptype = lambda dtype: np.float32
    shapes = {"images": (1, 3, 64, 64), "output0": (1, 84, 4)}

    class Ctx:
        def __init__(self):
            self.addr = {}

        def set_tensor_address(self, name, ptr):
            self.addr[name] = ptr

        def get_tensor_shape(self, name):
            return shapes[name]

        def set_input_shape(self, name, shape):
            pass

        def execute_async_v3(self, stream):
            img = np.frombuffer((ctypes.c_float * (3 * 64 * 64)).from_address(self.addr["images"]), np.float32)
            img = img.reshape(3, 64, 64).sum(axis=0)
            y, x = np.unravel_index(np.argmax(img), img.shape)
            out = np.frombuffer((ctypes.c_float * (84 * 4)).from_address(self.addr["output0"]), np.float32).reshape(84, 4)
            out[:] = 0
            out[:4, 0] = (x, y, 10, 10)
            out[4, 0] = 0.95                                  # class 0 = person
            return True

    class Engine:
        num_io_tensors = 2

        def get_tensor_name(self, i):
            return ["images", "output0"][i]

        def get_tensor_mode(self, name):
            return "in" if name == "images" else "out"

        def get_tensor_shape(self, name):
            return shapes[name]

        def get_tensor_dtype(self, name):
            return "float32"

        def create_execution_context(self):
            return Ctx()

    trt.Runtime = lambda logger: types.SimpleNamespace(deserialize_cuda_engine=lambda data: Engine())
    return trt


class GpuRunner(unittest.TestCase):
    def test_tensorrt_runner_round_trip(self):
        from beamcell import trt_runner
        with tempfile.NamedTemporaryFile(suffix=".engine") as f, \
                mock.patch.dict(sys.modules, {"tensorrt": fake_tensorrt()}), \
                mock.patch.object(trt_runner, "_cudart", lambda: FakeCuda()):
            runner = trt_runner.TrtRunner(f.name)
            self.assertEqual(runner.size, 64)
            blob = np.zeros((1, 3, 64, 64), np.float32)
            blob[:, :, 40, 12] = 1.0                          # one bright pixel at x=12, y=40
            dets = parse_yolo_all(runner.infer(blob), 64, 64, 64)
            self.assertEqual(len(dets), 1)
            x, y, w, h, score, cls = dets[0]
            self.assertEqual((cls, round(x + w / 2), round(y + h / 2)), (0, 12, 40))
            runner.close()

    def test_not_available_without_tensorrt(self):
        from beamcell import trt_runner
        with mock.patch.dict(sys.modules, {"tensorrt": None}):
            ok, why = trt_runner.available()
        self.assertFalse(ok)
        self.assertIn("TensorRT", why)

    def test_engine_listed_first(self):
        with tempfile.TemporaryDirectory() as d:
            for n in ("yolo11n.onnx", "yolo11n.engine"):
                open(os.path.join(d, n), "w").close()
            self.assertEqual(Vision(d).models(), ["yolo11n.engine", "yolo11n.onnx"])
