"""
Camera + person detection for the safety zone (optional - the cell runs without it).

    Camera   USB webcam (source 0, 1, ...), Jetson CSI camera (source "csi"), or a video file.
    Detector YOLO (an ONNX model in models/, run with OpenCV's DNN module - no PyTorch needed)
             or, with no model, OpenCV's built-in HOG people detector (no download at all).
    Safety   if a person's feet are inside the zone, a SAFETY STOP latches. The app pauses
             the machine; it only restarts after the zone is clear AND someone presses Reset -
             the same as a light curtain on a real machine.

Everything heavy (OpenCV, the camera) is only loaded when the camera is switched on, to keep
memory free on a 4 GB Jetson.
"""
import glob
import os
import threading
import time

import numpy as np

CSI_PIPELINE = ("nvarguscamerasrc ! video/x-raw(memory:NVMM),width=1280,height=720,framerate=30/1 ! "
                "nvvidconv ! video/x-raw,format=BGRx ! videoconvert ! video/x-raw,format=BGR ! appsink drop=1")
PERSON = 0                 # COCO class number for "person"


def _cv2():
    try:
        import cv2
        return cv2
    except ImportError:
        return None


def nms(boxes, scores, iou=0.45):
    """Non-maximum suppression (numpy): keep the best box of each overlapping group."""
    if len(boxes) == 0:
        return []
    b = np.asarray(boxes, float)
    x1, y1, x2, y2 = b[:, 0], b[:, 1], b[:, 0] + b[:, 2], b[:, 1] + b[:, 3]
    area = (x2 - x1) * (y2 - y1)
    order = np.argsort(scores)[::-1]
    keep = []
    while order.size:
        i = order[0]
        keep.append(int(i))
        xx1, yy1 = np.maximum(x1[i], x1[order[1:]]), np.maximum(y1[i], y1[order[1:]])
        xx2, yy2 = np.minimum(x2[i], x2[order[1:]]), np.minimum(y2[i], y2[order[1:]])
        inter = np.clip(xx2 - xx1, 0, None) * np.clip(yy2 - yy1, 0, None)
        overlap = inter / (area[i] + area[order[1:]] - inter + 1e-9)
        order = order[1:][overlap < iou]
    return keep


def parse_yolo(output, frame_w, frame_h, size, conf=0.4):
    """YOLO output -> person boxes [(x, y, w, h, score)] in frame pixels.
    Handles YOLOv8/YOLO11 (1, 84, N) and YOLOv5 (1, N, 85) layouts."""
    out = np.squeeze(np.asarray(output))
    if out.ndim != 2:
        return []
    if out.shape[0] in (84, 85) and out.shape[1] not in (84, 85):
        out = out.T                                      # v8 / 11 come as (84, N)
    if out.shape[1] == 85:                               # v5: x, y, w, h, objectness, 80 classes
        scores = out[:, 4] * out[:, 5 + PERSON]
        boxes = out[:, :4]
    else:                                                # v8 / 11: x, y, w, h, 80 classes
        scores = out[:, 4 + PERSON]
        boxes = out[:, :4]
    keep = scores > conf
    boxes, scores = boxes[keep], scores[keep]
    sx, sy = frame_w / size, frame_h / size
    xywh = [((cx - w / 2) * sx, (cy - h / 2) * sy, w * sx, h * sy) for cx, cy, w, h in boxes]
    return [tuple(xywh[i]) + (float(scores[i]),) for i in nms(xywh, scores)]


class Vision:
    def __init__(self, models_dir):
        self.models_dir = models_dir
        self.lock = threading.Lock()
        self.enabled = False
        self.source = None
        self.zone = [0.15, 0.25, 0.85, 1.0]     # x0, y0, x1, y1 as fractions of the image
        self.people = []                        # [(x, y, w, h, score)] in the last frame
        self.in_zone = False
        self.latched = False
        self.detector = "none"
        self.message = "camera off"
        self.fps = 0.0
        self._jpeg = None
        self._thread = None
        self._stop = threading.Event()

    # ---------------------------------------------------------------- info
    def models(self):
        return sorted(os.path.basename(p) for p in glob.glob(os.path.join(self.models_dir, "*.onnx")))

    def capabilities(self):
        cv2 = _cv2()
        return {"opencv": cv2.__version__ if cv2 else None, "yolo_models": self.models()}

    def status(self):
        with self.lock:
            return {"enabled": self.enabled, "source": self.source, "detector": self.detector,
                    "people": len(self.people), "in_zone": self.in_zone, "safety_stop": self.latched,
                    "zone": self.zone, "fps": round(self.fps, 1), "message": self.message,
                    "has_frame": self._jpeg is not None}

    def jpeg(self):
        with self.lock:
            return self._jpeg

    # ---------------------------------------------------------------- control
    def configure(self, body):
        if "zone" in body:
            z = [float(v) for v in body["zone"]]
            if len(z) == 4 and 0 <= z[0] < z[2] <= 1 and 0 <= z[1] < z[3] <= 1:
                self.zone = z
        if body.get("reset"):
            with self.lock:
                if self.in_zone:
                    self.message = "can't reset: someone is still in the zone"
                else:
                    self.latched = False
                    self.message = "safety reset"
        if "enabled" in body:
            if body["enabled"]:
                self._start(body.get("source", self.source if self.source is not None else 0), body.get("model"))
            else:
                self._halt()
                self.message = "camera off"
        return dict(self.status(), message=self.message)

    def _halt(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
        self._thread = None
        with self.lock:
            self.enabled = False
            self._jpeg = None
            self.people = []
            self.in_zone = False

    def _start(self, source, model=None):
        self._halt()
        if _cv2() is None:
            self.message = "OpenCV (cv2) isn't installed - camera not available"
            return
        self._stop.clear()
        self.source = source
        self._thread = threading.Thread(target=self._run, args=(source, model), daemon=True)
        self._thread.start()
        with self.lock:
            self.enabled = True
            self.message = "starting camera..."

    # ---------------------------------------------------------------- the camera loop
    def _open(self, cv2, source):
        if str(source).lower() == "csi":
            return cv2.VideoCapture(CSI_PIPELINE, cv2.CAP_GSTREAMER)
        if str(source).isdigit():
            cap = cv2.VideoCapture(int(source))
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            return cap
        return cv2.VideoCapture(str(source))

    def _make_detector(self, cv2, model):
        models = self.models()
        name = model if model in models else (models[0] if models else None)
        if name:
            try:
                net = cv2.dnn.readNetFromONNX(os.path.join(self.models_dir, name))
                size = 320 if "320" in name else 640
                self.detector = f"YOLO ({name}, {size}px, OpenCV DNN)"

                def detect(frame):
                    blob = cv2.dnn.blobFromImage(frame, 1 / 255.0, (size, size), swapRB=True, crop=False)
                    net.setInput(blob)
                    return parse_yolo(net.forward(), frame.shape[1], frame.shape[0], size)
                return detect
            except Exception as e:                     # noqa: BLE001 - fall back to HOG
                self.message = f"couldn't load {name} ({e}); using HOG"
        if not hasattr(cv2, "HOGDescriptor"):            # OpenCV 5 moved HOG out of the main module
            self.detector = "none - put a YOLO .onnx model in models/"
            return lambda frame: []
        hog = cv2.HOGDescriptor()
        hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
        self.detector = "HOG people detector (OpenCV built-in)"

        def detect(frame):
            scale = 400 / frame.shape[1]
            small = cv2.resize(frame, (400, int(frame.shape[0] * scale)))
            rects, weights = hog.detectMultiScale(small, winStride=(8, 8), padding=(8, 8), scale=1.05)
            return [(x / scale, y / scale, w / scale, h / scale, float(s))
                    for (x, y, w, h), s in zip(rects, np.ravel(weights)) if s > 0.5]
        return detect

    def _run(self, source, model):
        try:
            self._loop(source, model)
        except Exception as e:                         # noqa: BLE001 - never kill the server
            with self.lock:
                self.enabled = False
                self.message = f"camera error: {e}"

    def _loop(self, source, model):
        cv2 = _cv2()
        cap = self._open(cv2, source)
        if not cap or not cap.isOpened():
            with self.lock:
                self.enabled = False
                self.message = f"can't open camera {source!r}"
            return
        detect = self._make_detector(cv2, model)
        with self.lock:
            self.message = "camera on"
        is_file = not str(source).isdigit() and str(source).lower() != "csi"
        t_last = time.time()
        while not self._stop.is_set():
            ok, frame = cap.read()
            if not ok:
                if is_file:                               # loop a video file
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    continue
                with self.lock:
                    self.message = "camera stopped sending pictures"
                break
            if frame.shape[1] > 640:
                frame = cv2.resize(frame, (640, int(frame.shape[0] * 640 / frame.shape[1])))
            people = detect(frame)
            H, W = frame.shape[:2]
            zx0, zy0, zx1, zy1 = self.zone
            in_zone = any(zx0 * W <= x + w / 2 <= zx1 * W and zy0 * H <= y + h <= zy1 * H for x, y, w, h, _ in people)
            colour = (0, 0, 255) if in_zone else (0, 200, 0)
            cv2.rectangle(frame, (int(zx0 * W), int(zy0 * H)), (int(zx1 * W) - 1, int(zy1 * H) - 1), colour, 2)
            for x, y, w, h, s in people:
                cv2.rectangle(frame, (int(x), int(y)), (int(x + w), int(y + h)), (0, 165, 255), 2)
                cv2.putText(frame, f"person {s:.2f}", (int(x), max(12, int(y) - 4)), cv2.FONT_HERSHEY_SIMPLEX,
                            0.45, (0, 165, 255), 1)
            ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
            now = time.time()
            with self.lock:
                self.people = people
                self.in_zone = in_zone
                if in_zone:
                    self.latched = True
                if ok:
                    self._jpeg = buf.tobytes()
                self.fps = 0.8 * self.fps + 0.2 / max(now - t_last, 1e-3)
            t_last = now
            if is_file:
                time.sleep(0.05)
        cap.release()
        with self.lock:
            self.enabled = False
