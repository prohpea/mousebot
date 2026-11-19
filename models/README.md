# AI Detection Models for Valorant (ONNX Runtime + DirectML)

This folder hosts YOLO ONNX models accelerated via DirectML on your NVIDIA GeForce GTX 1060 3GB GPU.

### Quick Setup:
1. Place your trained `.onnx` model file in this directory:
   e.g. `models/valorant_detector.onnx` or `models/yolov8n_valorant.onnx`
2. Supported formats:
   - YOLOv8, YOLOv9, YOLOv10, YOLOv11 (Output shape: `[1, 5, 8400]` or `[1, num_anchors, 4+classes]`)
   - YOLOv5 (Output shape: `[1, num_anchors, 5+classes]`)
3. Enable in `config.json`:
   ```json
   "ai_detection_enabled": true,
   "ai_model_path": "models/valorant_detector.onnx",
   "ai_device": "dml",
   "ai_confidence_threshold": 0.45,
   "ai_iou_threshold": 0.45
   ```
4. If `ai_detection_enabled` is `false` or the model file is not present, the bot automatically runs the optimized HSV pipeline with zero overhead.
