# Running it on the Jetson Orin Nano

Your board (see `JETSON_SPECS.md`): Orin Nano Super, **4 GB RAM**, JetPack 7.2.1, Ubuntu
24.04, Python 3.12, numpy 1.26.4, OpenCV 4.6.0. **Nothing needs installing** - the server
uses only Python's standard library, numpy and (for the camera) OpenCV, and the 3D library
(three.js) is inside the repo.

## Start it

```
cd ~/robot_arm
git pull
./start.sh
```

Open **http://localhost:8080** in Chromium on the Jetson. The terminal also prints an address
like `http://172.20.10.5:8080` - open that on a laptop, tablet or phone on the same Wi-Fi
for a demo (it's often smoother there, and it saves the Jetson's memory).

Stop it with **Ctrl+C**.

## Start automatically at boot

```
sudo cp deploy/beamcell.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now beamcell
```

Check with `systemctl status beamcell`; read the log with `journalctl -u beamcell -f`.

## Full-screen demo (kiosk mode)

```
chromium-browser --kiosk --app=http://localhost:8080
```
(On some JetPack versions the command is `chromium`.) Press **Alt+F4** to leave.

## Memory: the Orin has only 4 GB

When you checked, only ~365 MB was free and swap was full. To keep it smooth:
- Close other programs (especially other browsers / old matplotlib windows).
- If the 3D view is slow: **Help → Use low graphics** (turns off shadows and smoothing).
- Or run the server on the Jetson and open the app on a laptop instead.
- The pill at the top right shows the Jetson's free memory, updated every 15 s.
- The camera only starts when you press *Start camera*; *Stop* frees its memory.

## Camera

| Camera | Choose |
|---|---|
| USB webcam | *USB camera 0* (or 1 if you have two) |
| Raspberry Pi / Arducam CSI camera on the Orin's ribbon connector | *Jetson CSI camera* (uses `nvarguscamerasrc`) |
| A recorded video, for a demo without a camera | *Video file...* and type its path |

Check a USB camera is seen with `ls /dev/video*`. A CSI camera can be tested with
`nvgstcapture-1.0`.

## Person detection (YOLO)

Two detectors:

1. **Built in, no download**: OpenCV's HOG people detector. Works straight away with your
   OpenCV 4.6. OK for a demo; it misses people who are far away or side-on.
2. **YOLO** (much better): put a YOLO model exported to **ONNX** in the `models/` folder. It
   runs through OpenCV's DNN module, so PyTorch isn't needed on the Jetson.

To get the ONNX file, on any PC with Python (not the Jetson - it saves memory and download):
```
pip install ultralytics
yolo export model=yolo11n.pt format=onnx imgsz=320 opset=12
```
Copy `yolo11n.onnx` to `~/robot_arm/models/` and rename it `yolo11n_320.onnx` (the `320` in
the name tells the app the picture size). It's about 10 MB. YOLOv8 (`yolov8n.pt`) and YOLOv5
ONNX files work too. Then pick it in the **Camera** tab's *Detector* list.

The YOLO path was tested here with synthetic model output, not with a real model on your
board - if OpenCV 4.6 refuses the file, export again with `opset=11`.

## Safety zone

The green box on the camera picture is the zone (set it with the sliders). When a person's
feet are inside it the box turns red, the machine **stops**, and it stays stopped until the
zone is clear **and** someone presses **Reset** - the same as a light curtain. Turn off
*Person in the zone stops the machine* to just watch.

This is a demo of the idea. A real machine needs certified safety hardware (light curtains,
interlocked gates, a safety PLC) - a camera and YOLO are not a safety device.
