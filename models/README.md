# YOLO models

Put `yolo11n.onnx` here, then build the GPU engine on the Jetson: `tools/make_trt_engine.sh`
(it makes `yolo11n.engine`). Pick "YOLO on the GPU" in the Camera tab.
See docs/JETSON_SETUP.md, "Person and object detection (YOLO) - on the GPU".
Model files aren't kept in git (size, and Ultralytics models are AGPL-3.0).
