"""
Camera + person detection for the safety zone (optional - the cell runs without it).

    Camera   "auto" (finds one: USB cameras first, then a Jetson CSI camera), a USB camera
             number (0, 1, ... = /dev/video0, /dev/video1 ...), "csi", or a video file.
    Detector best first:
               1. YOLO on the GPU with TensorRT (a models/*.engine built on the Jetson - see
                  tools/make_trt_engine.sh): fast, and it also finds OBJECTS, not only people,
               2. YOLO on the CPU (a models/*.onnx run with OpenCV's DNN module - no PyTorch needed),
               3. with no model, OpenCV's built-in HOG people detector (no download at all).
    Zones    WARNING zone: someone near the cell - the machine slows down.
             DANGER zone: someone at the machine - protective stop (the safety controller,
             beamcell/safety.py, latches it until the zone is clear and Reset is pressed).
             BED zone: the roller bed. An object YOLO recognises lying there (a bag, a bottle, a tool,
             a phone...) is reported as "object on the bed"; with safety.camera_object_stop = true
             in config/cell.toml it stops the machine (OBJECT stop, beamcell/safety.py).
             A person counts as "in" a zone when their feet (bottom of the box) are inside it;
             an object when the middle of its box is.
             This is an extra layer of protection, not a safety-rated device.

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
COCO = ("person bicycle car motorcycle airplane bus train truck boat traffic_light fire_hydrant stop_sign "
        "parking_meter bench bird cat dog horse sheep cow elephant bear zebra giraffe backpack umbrella handbag tie "
        "suitcase frisbee skis snowboard sports_ball kite baseball_bat baseball_glove skateboard surfboard tennis_racket "
        "bottle wine_glass cup fork knife spoon bowl banana apple sandwich orange broccoli carrot hot_dog pizza donut cake "
        "chair couch potted_plant bed dining_table toilet tv laptop mouse remote keyboard cell_phone microwave oven toaster "
        "sink refrigerator book clock vase scissors teddy_bear hair_drier toothbrush").split()
# things that must not be lying on the bed when the hands move (COCO has no "spanner", so the
# nearest everyday objects stand in for tools, rags and bags left behind)
BED_OBJECTS = {COCO.index(n) for n in ("backpack", "umbrella", "handbag", "suitcase", "sports_ball", "baseball_bat",
                                         "bottle", "cup", "knife", "scissors", "cell_phone", "laptop", "mouse",
                                         "remote", "keyboard", "book", "chair", "bench", "toothbrush", "hair_drier")}
CSI_NAMES = ("vi-output", "imx", "ov5", "ar0", "tegra")   # how Jetson CSI sensors name their /dev/video node


def list_cameras():
    """The cameras Linux can see: [{dev, index, name, kind: usb|csi, main}].
    `main` is False for the extra metadata node a USB camera adds (it can't give pictures)."""
    out = []
    for dev in sorted(glob.glob("/dev/video*"), key=lambda d: int("".join(c for c in d if c.isdigit()) or 0)):
        n = dev.replace("/dev/video", "")
        if not n.isdigit():
            continue
        sysfs = f"/sys/class/video4linux/video{n}"
        name = _read(os.path.join(sysfs, "name")) or "camera"
        main = _read(os.path.join(sysfs, "index")) in ("", "0")
        kind = "csi" if any(k in name.lower() for k in CSI_NAMES) else "usb"
        out.append({"dev": dev, "index": int(n), "name": name, "kind": kind, "main": main})
    return out


def _read(path):
    try:
        with open(path) as fh:
            return fh.read().strip()
    except OSError:
        return ""


def in_video_group():
    """Can this user open cameras? (Linux: member of the 'video' group, or root.)"""
    try:
        import grp
        if os.geteuid() == 0:
            return True
        return grp.getgrnam("video").gr_gid in os.getgroups()
    except (ImportError, KeyError, AttributeError):
        return True


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


def parse_yolo_all(output, frame_w, frame_h, size, conf=0.4):
    """YOLO output -> every detection [(x, y, w, h, score, class)] in frame pixels.
    Handles YOLOv8/YOLO11 (1, 84, N) and YOLOv5 (1, N, 85) layouts."""
    out = np.squeeze(np.asarray(output, dtype=np.float32))
    if out.ndim != 2:
        return []
    if out.shape[0] in (84, 85) and out.shape[1] not in (84, 85):
        out = out.T                                      # v8 / 11 come as (84, N)
    if out.shape[1] == 85:                               # v5: x, y, w, h, objectness, 80 classes
        cls_scores = out[:, 5:] * out[:, 4:5]
    else:                                                # v8 / 11: x, y, w, h, 80 classes
        cls_scores = out[:, 4:]
    cls = np.argmax(cls_scores, axis=1)
    scores = cls_scores[np.arange(len(cls)), cls]
    keep = scores > conf
    boxes, scores, cls = out[keep, :4], scores[keep], cls[keep]
    sx, sy = frame_w / size, frame_h / size
    xywh = [((cx - w / 2) * sx, (cy - h / 2) * sy, w * sx, h * sy) for cx, cy, w, h in boxes]
    # one NMS per class: shift each class's boxes far apart so they never suppress each other
    shifted = [(x + 10000 * c, y, w, h) for (x, y, w, h), c in zip(xywh, cls)]
    return [tuple(xywh[i]) + (float(scores[i]), int(cls[i])) for i in nms(shifted, scores)]


def parse_yolo(output, frame_w, frame_h, size, conf=0.4):
    """YOLO output -> person boxes [(x, y, w, h, score)] in frame pixels."""
    return [d[:5] for d in parse_yolo_all(output, frame_w, frame_h, size, conf) if d[5] == PERSON]


def split(detections, bed_zone, frame_w, frame_h):
    """(people, objects on the bed) from all detections."""
    people = [d[:5] for d in detections if d[5] == PERSON]
    z = bed_zone
    objects = [d for d in detections if d[5] in BED_OBJECTS
               and z[0] * frame_w <= d[0] + d[2] / 2 <= z[2] * frame_w and z[1] * frame_h <= d[1] + d[3] / 2 <= z[3] * frame_h]
    return people, objects


class Vision:
    def __init__(self, models_dir):
        self.models_dir = models_dir
        self.lock = threading.Lock()
        self.enabled = False
        self.source = None
        self.zones = {"warning": [0.05, 0.15, 0.95, 1.0], "danger": [0.25, 0.35, 0.75, 1.0], "bed": [0.15, 0.45, 0.85, 0.85]}
        self.people = []                        # [(x, y, w, h, score)] in the last frame
        self.objects = []                       # [(x, y, w, h, score, class)] lying on the bed
        self.in_warning = False
        self.in_danger = False
        self.last_frame = 0.0
        self.detector = "none"
        self.message = "camera off"
        self.fps = 0.0
        self._jpeg = None
        self._thread = None
        self._stop = threading.Event()

    # ---------------------------------------------------------------- info
    def models(self):
        """YOLO models in models/: GPU engines (.engine) first, then .onnx."""
        engines = sorted(os.path.basename(p) for p in glob.glob(os.path.join(self.models_dir, "*.engine")))
        return engines + sorted(os.path.basename(p) for p in glob.glob(os.path.join(self.models_dir, "*.onnx")))

    def capabilities(self):
        cv2 = _cv2()
        from beamcell.trt_runner import available
        gpu, why = available()
        return {"opencv": cv2.__version__ if cv2 else None, "yolo_models": self.models(),
                "tensorrt": why if gpu else None, "tensorrt_why": None if gpu else why}

    def status(self):
        with self.lock:
            return {"enabled": self.enabled, "source": self.source, "detector": self.detector,
                    "people": len(self.people), "in_warning": self.in_warning, "in_danger": self.in_danger,
                    "objects_on_bed": [COCO[o[5]].replace("_", " ") for o in self.objects], "bed_blocked": bool(self.objects),
                    "zones": self.zones, "fps": round(self.fps, 1), "message": self.message,
                    "has_frame": self._jpeg is not None,
                    "frame_age": round(time.time() - self.last_frame, 2) if self.last_frame else None}

    def jpeg(self):
        with self.lock:
            return self._jpeg

    # ---------------------------------------------------------------- control
    def configure(self, body):
        for name, z in (body.get("zones") or {}).items():
            z = [float(v) for v in z]
            if name in self.zones and len(z) == 4 and 0 <= z[0] < z[2] <= 1 and 0 <= z[1] < z[3] <= 1:
                self.zones[name] = z
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
            self.objects = []
            self.in_warning = self.in_danger = False
            self.last_frame = 0.0

    def _start(self, source, model=None):
        self._halt()
        if _cv2() is None:
            self.message = ("OpenCV (cv2) isn't installed for this Python - on the Jetson: sudo apt install python3-opencv")
            return
        self._stop.clear()
        self.source = source
        with self.lock:                                   # before the thread: it may fail at once
            self.enabled = True
            self.message = "starting camera..."
        self._thread = threading.Thread(target=self._run, args=(source, model), daemon=True)
        self._thread.start()

    # ---------------------------------------------------------------- the camera loop
    def _open(self, cv2, source):
        """Open a camera. Returns (capture or None, what was tried / why it failed)."""
        src = str(source).strip().lower()
        if src in ("", "auto"):
            cams = list_cameras()
            tried = []
            for cam in [c for c in cams if c["kind"] == "usb" and c["main"]]:
                cap = self._open_usb(cv2, cam["index"])
                if cap is not None:
                    self.source = cam["index"]
                    return cap, f"USB camera {cam['dev']} ({cam['name']})"
                tried.append(f"{cam['dev']} ({cam['name']}) gave no picture")
            if any(c["kind"] == "csi" for c in cams) or not cams:
                cap, why = self._open_csi(cv2)
                if cap is not None:
                    self.source = "csi"
                    return cap, "Jetson CSI camera"
                tried.append(why)
            return None, self._no_camera_help(cams, tried)
        if src == "csi":
            return self._open_csi(cv2)
        if src.isdigit():
            cam = next((c for c in list_cameras() if c["index"] == int(src)), None)
            if cam and cam["kind"] == "csi":
                return None, (f"/dev/video{src} is a CSI camera ({cam['name']}) - it can't be read like a webcam. "
                              "Choose 'Jetson CSI camera' (or Auto).")
            if cam and not cam["main"]:
                return None, f"/dev/video{src} is the extra info channel of a USB camera - try /dev/video{int(src) - 1}"
            cap = self._open_usb(cv2, int(src))
            return (cap, f"USB camera /dev/video{src}") if cap is not None else \
                (None, self._no_camera_help(list_cameras(), [f"/dev/video{src} didn't open or gave no picture"]))
        if not os.path.exists(str(source)):
            return None, f"no such video file: {source}"
        cap = cv2.VideoCapture(str(source))
        return (cap, f"video file {source}") if cap.isOpened() else (None, f"can't read the video file {source}")

    @staticmethod
    def _open_usb(cv2, index):
        """A USB (UVC) camera through V4L2 - the direct way on Linux - asking for MJPG 640x480,
        which every webcam can do without filling the USB bus. It must give a picture to count."""
        for backend in ([cv2.CAP_V4L2] if hasattr(cv2, "CAP_V4L2") else []) + [cv2.CAP_ANY]:
            cap = cv2.VideoCapture(index, backend)
            if not cap.isOpened():
                cap.release()
                continue
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            for _ in range(20):                           # cameras need a moment to warm up
                ok, _frame = cap.read()
                if ok:
                    return cap
                time.sleep(0.05)
            cap.release()
        return None

    @staticmethod
    def _open_csi(cv2):
        if "GStreamer:                   YES" not in cv2.getBuildInformation() and \
                "GStreamer: YES" not in cv2.getBuildInformation().replace("  ", ""):
            return None, ("this OpenCV was built without GStreamer, so it can't read a CSI camera - use the Jetson's "
                          "own OpenCV (sudo apt install python3-opencv), not 'pip install opencv-python'")
        cap = cv2.VideoCapture(CSI_PIPELINE, cv2.CAP_GSTREAMER)
        if cap.isOpened():
            ok, _frame = cap.read()
            if ok:
                return cap, "Jetson CSI camera"
        cap.release()
        return None, ("the CSI camera didn't start - check the ribbon cable (blue side), that the camera is "
                      "enabled (sudo /opt/nvidia/jetson-io/jetson-io.py), and try: nvgstcapture-1.0")

    @staticmethod
    def _no_camera_help(cams, tried):
        parts = list(tried)
        if not cams:
            parts.append("Linux sees no camera (no /dev/video*): plug the USB camera in (try another port, "
                         "not through an unpowered hub) or check the CSI ribbon cable, then reboot")
        if not in_video_group():
            parts.append("your user isn't in the 'video' group: sudo usermod -aG video $USER, then log out and in")
        parts.append("python3 -m beamcell.doctor lists what it can see")
        return "no camera found: " + "; ".join(parts)

    def _make_detector(self, cv2, model):
        """detect(frame) -> all detections [(x, y, w, h, score, class)]. The best one available:
        a TensorRT engine on the GPU, then YOLO on the CPU, then HOG (people only)."""
        models = self.models()
        if model == "none":                              # the operator picked the built-in detector
            name = None
        else:
            name = model if model in models else (models[0] if models else None)
        if name and name.endswith(".engine"):
            try:
                from beamcell.trt_runner import TrtRunner
                runner = TrtRunner(os.path.join(self.models_dir, name))
                size = runner.size
                self.detector = f"YOLO on the GPU (TensorRT, {name}, {size}px) - people and objects"

                def detect(frame):
                    blob = cv2.dnn.blobFromImage(frame, 1 / 255.0, (size, size), swapRB=True, crop=False)
                    return parse_yolo_all(runner.infer(blob), frame.shape[1], frame.shape[0], size)
                return detect
            except Exception as e:                     # noqa: BLE001 - fall back to the CPU
                self.message = f"couldn't run {name} on the GPU ({e}); using the CPU"
                onnx = [m for m in models if m.endswith(".onnx")]
                name = onnx[0] if onnx else None
        if name:
            try:
                net = cv2.dnn.readNetFromONNX(os.path.join(self.models_dir, name))
                size = 320 if "320" in name else 640
                where = "CPU"
                try:                                     # an OpenCV built with CUDA can use the GPU
                    if cv2.cuda.getCudaEnabledDeviceCount() > 0:
                        net.setPreferableBackend(cv2.dnn.DNN_BACKEND_CUDA)
                        net.setPreferableTarget(cv2.dnn.DNN_TARGET_CUDA_FP16)
                        where = "GPU (OpenCV CUDA)"
                except Exception:                      # noqa: BLE001 - no CUDA in this OpenCV
                    pass
                self.detector = f"YOLO on the {where} ({name}, {size}px, OpenCV DNN) - people and objects"

                def detect(frame):
                    blob = cv2.dnn.blobFromImage(frame, 1 / 255.0, (size, size), swapRB=True, crop=False)
                    net.setInput(blob)
                    return parse_yolo_all(net.forward(), frame.shape[1], frame.shape[0], size)
                return detect
            except Exception as e:                     # noqa: BLE001 - fall back to HOG
                self.message = f"couldn't load {name} ({e}); using HOG"
        if not hasattr(cv2, "HOGDescriptor"):            # OpenCV 5 moved HOG out of the main module
            self.detector = "none - put a YOLO model in models/"
            return lambda frame: []
        hog = cv2.HOGDescriptor()
        hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
        self.detector = "HOG people detector (OpenCV built-in, CPU) - people only"

        def detect(frame):
            scale = 400 / frame.shape[1]
            small = cv2.resize(frame, (400, int(frame.shape[0] * scale)))
            rects, weights = hog.detectMultiScale(small, winStride=(8, 8), padding=(8, 8), scale=1.05)
            return [(x / scale, y / scale, w / scale, h / scale, float(s), PERSON)
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
        cap, what = self._open(cv2, source)
        if cap is None:
            with self.lock:
                self.enabled = False
                self.message = what
            return
        detect = self._make_detector(cv2, model)
        with self.lock:
            self.message = f"camera on - {what}"
        is_file = what.startswith("video file")
        t_last = time.time()
        misses = 0
        while not self._stop.is_set():
            ok, frame = cap.read()
            if not ok:
                if is_file:                               # loop a video file
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    continue
                misses += 1
                if misses < 30:                           # a few dropped frames are normal
                    time.sleep(0.05)
                    continue
                with self.lock:
                    self.message = "camera stopped sending pictures (unplugged? USB power?)"
                break
            misses = 0
            if frame.shape[1] > 640:
                frame = cv2.resize(frame, (640, int(frame.shape[0] * 640 / frame.shape[1])))
            H, W = frame.shape[:2]
            people, objects = split(detect(frame), self.zones["bed"], W, H)
            feet = [(x + w / 2, y + h) for x, y, w, h, _ in people]

            def inside(z):
                return any(z[0] * W <= fx <= z[2] * W and z[1] * H <= fy <= z[3] * H for fx, fy in feet)
            in_warning, in_danger = inside(self.zones["warning"]), inside(self.zones["danger"])
            for name, colour in (("bed", (255, 0, 200)), ("warning", (0, 190, 255)), ("danger", (0, 0, 255))):
                z = self.zones[name]
                hit = {"danger": in_danger, "warning": in_warning, "bed": bool(objects)}[name]
                cv2.rectangle(frame, (int(z[0] * W), int(z[1] * H)), (int(z[2] * W) - 1, int(z[3] * H) - 1),
                              colour if hit else (0, 200, 0), 3 if hit else 1)
                cv2.putText(frame, name.upper(), (int(z[0] * W) + 4, int(z[1] * H) + 16), cv2.FONT_HERSHEY_SIMPLEX,
                            0.5, colour if hit else (0, 200, 0), 1)
            for x, y, w, h, s in people:
                cv2.rectangle(frame, (int(x), int(y)), (int(x + w), int(y + h)), (255, 120, 0), 2)
                cv2.putText(frame, f"person {s:.2f}", (int(x), max(12, int(y) - 4)), cv2.FONT_HERSHEY_SIMPLEX,
                            0.45, (255, 120, 0), 1)
            for x, y, w, h, sc, c in objects:
                cv2.rectangle(frame, (int(x), int(y)), (int(x + w), int(y + h)), (255, 0, 200), 2)
                cv2.putText(frame, f"{COCO[c].replace('_', ' ')} {sc:.2f}", (int(x), max(12, int(y) - 4)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 0, 200), 1)
            ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
            now = time.time()
            with self.lock:
                self.people = people
                self.objects = objects
                self.in_warning, self.in_danger = in_warning or in_danger, in_danger
                if ok:
                    self._jpeg = buf.tobytes()
                    self.last_frame = now
                self.fps = 0.8 * self.fps + 0.2 / max(now - t_last, 1e-3)
            t_last = now
            if is_file:
                time.sleep(0.05)
        cap.release()
        with self.lock:
            self.enabled = False
