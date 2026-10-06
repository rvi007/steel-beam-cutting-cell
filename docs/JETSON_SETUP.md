# Running it on the Jetson Orin Nano

Your board (see `JETSON_SPECS.md`): Orin Nano Super, **4 GB RAM**, JetPack 7.2.1, Ubuntu
24.04, Python 3.12, numpy 1.26.4, OpenCV 4.6.0. **Nothing needs installing** - the server
uses only Python's standard library, numpy and (for the camera) OpenCV, and the 3D library
(three.js) is inside the repo.

## Check the Orin first

```
python3 -m beamcell.doctor --save
git add docs/SYSTEM_CHECK.md && git commit -m "System check" && git push
```
It lists what's ready and what's missing (camera, YOLO model, GPIO, memory...) with a plan, and
the saved report lets a cloud session see your exact setup.

## Start it

```
cd ~/steel-beam-cutting-cell
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

## Person and object detection (YOLO) - on the GPU

Three detectors, best first - the app uses the best one it finds:

| | Detector | Speed on the Orin Nano (estimate) | Finds |
|---|---|---|---|
| 1 | **YOLO on the GPU** (TensorRT engine, `models/*.engine`) | about 30+ pictures/s, CPU left free | people **and objects** |
| 2 | YOLO on the CPU (`models/*.onnx`, OpenCV DNN) | a few pictures/s, busy CPU | people and objects - **needs OpenCV 4.7 or newer**: the Jetson's OpenCV 4.6 can't run YOLOv8 / YOLO11, so on this board it's the GPU or HOG |
| 3 | HOG (built into OpenCV, no download) | slow, misses people side-on | people only |

### Set up YOLO on the GPU (once, about 15 minutes)

**1. Check TensorRT for Python is there** (it comes with JetPack):
```
python3 -c "import tensorrt; print(tensorrt.__version__)"
```
If that fails: `sudo apt install python3-libnvinfer` (or `sudo apt install nvidia-jetpack`).

**2. Get the model as ONNX** - on any PC with Python, not the Jetson (it has no PyTorch, and
it saves memory and download):
```
pip install ultralytics
yolo export model=yolo11n.pt format=onnx imgsz=640 opset=17
```
Copy `yolo11n.onnx` (about 10 MB) to `~/steel-beam-cutting-cell/models/` on the Jetson.
(Checked: this file finds the people and the bus in Ultralytics' test photo with the app's own
post-processing, the same as Ultralytics' reference results.)

**3. Build the GPU engine on the Jetson** (close the browser first - it needs memory):
```
cd ~/steel-beam-cutting-cell
tools/make_trt_engine.sh
```
It makes `models/yolo11n.engine` (5-10 minutes; FP16). An engine only works on the GPU and
TensorRT version it was built on - build it again after a JetPack upgrade.

**4. Use it:** restart the app, **Camera** tab, *Detector* "YOLO on the GPU (TensorRT)", Start camera.
The status line says which detector runs and how many pictures per second.
`python3 -m beamcell.doctor` shows the line "YOLO on the GPU (TensorRT)".

If the engine can't be loaded, the app says why and falls back to the CPU with the `.onnx` (if this
OpenCV can run it - it tries the model once when the camera starts), then to HOG.

**Licence note:** Ultralytics YOLO models (YOLO11, YOLOv8) are AGPL-3.0. That's fine for this
prototype and for research; selling a product that contains them needs an Ultralytics licence -
or a model under a permissive licence. The model files aren't kept in git.

## Camera zones

Three boxes on the camera picture (set them with the sliders, defaults in `config/cell.toml`):
- **Warning** (amber): someone's feet inside - the machine slows to 25%.
- **Danger** (red): protective stop, latched until the zone is clear **and** Reset is pressed.
- **Bed** (pink): YOLO objects lying on the roller bed - a bag, bottle, phone, tool... - are
  listed on the Camera tab. With `camera_object_stop = true` (`[safety]` in `config/cell.toml`)
  they also stop the machine (an OBJECT stop: the hands hold where they are). Leave it `false`
  until you have watched it for a while - YOLO knows everyday objects (COCO), not every tool, and
  a shadow or the steel itself must never stop a job. A model trained on your own photos of
  tools on the bed would do better later.

Set `require_camera = true` to stop the machine if the camera fails.
This is an extra layer only - see `SAFETY.md`.

## Real E-stop and buttons

You can wire a real E-stop, gate switch, light-curtain relay and reset button to the 40-pin
header - wiring and settings in `SAFETY.md` section 6.

## AI advisor (optional)

See `ASSISTANT.md` - it runs in the cloud only when you ask a question, because the Orin's
4 GB can't hold a vision-language model next to the cell.
