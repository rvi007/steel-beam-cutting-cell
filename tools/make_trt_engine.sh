#!/bin/sh
# Build a TensorRT engine (YOLO on the Jetson's GPU) from an ONNX model in models/.
# Run it ON THE JETSON - an engine only works on the GPU and TensorRT version it was built on.
#
#   tools/make_trt_engine.sh                    # every models/*.onnx that has no .engine yet
#   tools/make_trt_engine.sh models/yolo11n.onnx
#
# Takes 5-10 minutes per model on an Orin Nano (close the browser to give it memory). Then pick
# "YOLO on the GPU" on the Camera tab - or just restart: the engine is used before the .onnx.
cd "$(dirname "$0")/.." || exit 1
TRTEXEC=$(command -v trtexec || ls /usr/src/tensorrt/bin/trtexec 2>/dev/null)
if [ -z "$TRTEXEC" ]; then
  echo "trtexec not found - install TensorRT's tools: sudo apt install tensorrt  (or nvidia-jetpack)"
  exit 1
fi
if [ $# -gt 0 ]; then MODELS="$*"; else MODELS=$(ls models/*.onnx 2>/dev/null); fi
if [ -z "$MODELS" ]; then
  echo "no .onnx model in models/ - see docs/JETSON_SETUP.md (YOLO on the GPU) for how to get one"
  exit 1
fi
for onnx in $MODELS; do
  engine="${onnx%.onnx}.engine"
  if [ -f "$engine" ] && [ $# -eq 0 ]; then echo "$engine already built"; continue; fi
  echo "building $engine (FP16) - this takes a few minutes..."
  # FP16 = half precision: about twice as fast on the GPU, same detections for YOLO.
  # 1 GB workspace keeps it inside the Orin Nano's 4 GB.
  "$TRTEXEC" --onnx="$onnx" --saveEngine="$engine" --fp16 --memPoolSize=workspace:1024 > "${engine%.engine}.build.log" 2>&1 \
    && echo "done: $engine" || { echo "FAILED - see ${engine%.engine}.build.log"; exit 1; }
done
