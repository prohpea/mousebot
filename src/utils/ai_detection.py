"""
Modular AI Detection Pipeline (ONNX Runtime + DirectML / CPU)
Optimized for high-FPS inference on Windows using DirectML (NVIDIA / AMD / Intel).
"""
import ast
import json
import os
import threading
import time

import cv2
import numpy as np

try:
    import onnxruntime as ort
except ImportError:
    ort = None

from src.utils.debug_logger import log_print
from src.utils.config import config


_AI_DETECTOR_INSTANCE = None
_AI_DETECTOR_SIGNATURE = None
# ``get_ai_detector`` is called from the tracking thread on every frame and from
# the UI thread (model/device combo, "Reload model"). Without a lock, a UI
# reload could build a second 36 MB session while the track thread is mid-call,
# doubling peak memory on a 3 GB GPU and rebuilding twice.
_AI_DETECTOR_LOCK = threading.Lock()
_AI_OUTLINE_SKIP_LOG_INTERVAL = 2.0
_last_ai_outline_skip_log_time = None

# Class names that are valid aim targets. This is an allow-list: everything
# else exported by a model (teammate, breakable, dodge, item, flash, ...) must
# never become a target, so a new export cannot leak a false target by name.
TARGET_CLASS_NAMES = frozenset({"body", "head", "enemy", "player"})
DEFAULT_CLASS_NAMES = ("enemy", "head")
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def resolve_model_path(model_path):
    """Resolve a model path against CWD first, then the repository root."""
    text = str(model_path or "").strip()
    if not text or os.path.isabs(text) or os.path.isfile(text):
        return text
    candidate = os.path.join(_PROJECT_ROOT, text)
    return candidate if os.path.isfile(candidate) else text


def _parse_names_metadata(raw):
    """Parse the ``names`` entry of ONNX ``custom_metadata_map``.

    Ultralytics exports ``{0: 'body', 1: 'head', ...}``; depending on the
    exporter it is a Python-dict string or a JSON string, so both parsers are
    tried. Returns a dense ``list[str]`` indexed by class id, or ``None`` when
    the value is unusable (the caller then keeps the default names).
    """
    if raw is None:
        return None

    data = raw
    if not isinstance(data, dict):
        text = str(raw).strip()
        if not text:
            return None
        for parser in (ast.literal_eval, json.loads):
            try:
                data = parser(text)
                break
            except Exception:
                continue
        else:
            return None

    if isinstance(data, (list, tuple)):
        names = [str(name) for name in data]
        return names or None
    if not isinstance(data, dict) or not data:
        return None

    try:
        indexed = {int(key): str(value) for key, value in data.items()}
    except Exception:
        return None

    size = max(indexed) + 1
    if size <= 0 or size > 4096:
        return None
    return [indexed.get(idx, f"class_{idx}") for idx in range(size)]


def letterbox(img, new_shape=(640, 640), color=(114, 114, 114)):
    """Resize and pad image while meeting stride-multiple constraints."""
    shape = img.shape[:2]  # current shape [height, width]
    if isinstance(new_shape, int):
        new_shape = (new_shape, new_shape)

    # Scale ratio (new / old)
    r = min(new_shape[0] / shape[0], new_shape[1] / shape[1])

    # Compute padding
    new_unpad = int(round(shape[1] * r)), int(round(shape[0] * r))
    dw, dh = new_shape[1] - new_unpad[0], new_shape[0] - new_unpad[1]  # wh padding
    dw /= 2  # divide padding into 2 sides
    dh /= 2

    if shape[::-1] != new_unpad:  # resize
        img = cv2.resize(img, new_unpad, interpolation=cv2.INTER_LINEAR)
    top, bottom = int(round(dh - 0.1)), int(round(dh + 0.1))
    left, right = int(round(dw - 0.1)), int(round(dw + 0.1))
    img = cv2.copyMakeBorder(img, top, bottom, left, right, cv2.BORDER_CONSTANT, value=color)
    return img, r, (dw, dh)


def _nms_per_class(boxes, confidences, class_ids, iou_threshold):
    """Non-maximum suppression computed per class id.

    ``cv2.dnn.NMSBoxes`` is class-agnostic, and a ``head`` box sits inside its
    ``body`` box by construction: as soon as their IoU passes the threshold the
    higher-scoring body box suppresses the head box, and the pipeline silently
    falls back to the 22 % head estimate -- the very feature the dedicated head
    class exists for. Suppressing only within one class keeps both boxes the
    model predicted. Confidence filtering already happened in the caller, so
    the score threshold here is 0.

    Returns indices into ``boxes``, highest confidence first.
    """
    if not boxes:
        return []

    groups = {}
    for idx, cid in enumerate(class_ids):
        groups.setdefault(cid, []).append(idx)

    kept = []
    for indices in groups.values():
        group_boxes = [boxes[i] for i in indices]
        group_scores = [confidences[i] for i in indices]
        result = cv2.dnn.NMSBoxes(group_boxes, group_scores, 0.0, iou_threshold)
        if len(result) > 0:
            for position in np.array(result).flatten():
                kept.append(indices[int(position)])

    kept.sort(key=lambda i: confidences[i], reverse=True)
    return kept


class AIDetector:
    def __init__(self, model_path=None, device="dml", conf_threshold=None, iou_threshold=None):
        self.model_path = model_path or getattr(config, "ai_model_path", "models/valorant_detector.onnx")
        self.device = (device or getattr(config, "ai_device", "dml")).strip().lower()
        # ``or`` would treat a deliberate 0.0 threshold as "unset" and silently
        # restore the config default, so only None means "fall back".
        if conf_threshold is None:
            conf_threshold = getattr(config, "ai_confidence_threshold", 0.45)
        if iou_threshold is None:
            iou_threshold = getattr(config, "ai_iou_threshold", 0.45)
        self.conf_threshold = _as_float(conf_threshold, 0.45)
        self.iou_threshold = _as_float(iou_threshold, 0.45)
        self.session = None
        self.input_name = None
        self.input_shape = (1, 3, 640, 640)
        self.input_size = (640, 640)  # (w, h)
        self.input_dtype = np.float32
        self.class_names = list(DEFAULT_CLASS_NAMES)
        self.metadata_names = None
        self.active_provider = None
        self.last_error = None
        self._dml_fallback_done = False
        self.is_loaded = False
        self._load_model()

    def _load_model(self):
        if ort is None:
            self.last_error = "onnxruntime is not installed"
            log_print(
                "[AI] onnxruntime is not installed (pip install onnxruntime-directml). "
                "AI detection unavailable."
            )
            return

        resolved_path = resolve_model_path(self.model_path)
        if not resolved_path or not os.path.isfile(resolved_path):
            self.last_error = f"Model file '{self.model_path}' not found"
            log_print(f"[AI] Model file '{self.model_path}' not found. AI detection idle.")
            return
        self.model_path = resolved_path

        try:
            available_providers = ort.get_available_providers()
            if self.device == "dml" and "DmlExecutionProvider" in available_providers:
                providers = ["DmlExecutionProvider", "CPUExecutionProvider"]
                provider_desc = "DirectML (GPU)"
            else:
                providers = ["CPUExecutionProvider"]
                provider_desc = "CPU"
                if self.device == "dml":
                    # ai_device=dml with no DirectML build is a silent 10x
                    # slowdown, and the UI still says "GPU Active": say it out
                    # loud instead of letting the user wonder why it is slow.
                    log_print(
                        "[AI] ai_device is 'dml' but DmlExecutionProvider is "
                        "unavailable; falling back to CPU."
                    )

            opts = ort.SessionOptions()
            opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            opts.intra_op_num_threads = 4
            opts.log_severity_level = 3  # Errors only

            self.session = ort.InferenceSession(self.model_path, sess_options=opts, providers=providers)
            active_provider = self.session.get_providers()[0]
            self.active_provider = active_provider
            self.last_error = None
            log_print(f"[AI] Model loaded successfully: {self.model_path} [{provider_desc} -> {active_provider}]")

            # Inspect input
            inputs = self.session.get_inputs()
            if inputs:
                self.input_name = inputs[0].name
                shape = inputs[0].shape
                h = shape[2] if len(shape) > 2 and isinstance(shape[2], int) and shape[2] > 0 else 640
                w = shape[3] if len(shape) > 3 and isinstance(shape[3], int) and shape[3] > 0 else 640
                self.input_size = (w, h)
                self.input_shape = (1, 3, h, w)
                self.input_dtype = np.float16 if "float16" in str(getattr(inputs[0], "type", "")).lower() else np.float32

            # Class names come from the model itself: the Ultralytics export
            # stores them under custom_metadata_map["names"], which is the only
            # authoritative source (hand-copied README tables drift).
            self._load_class_names()

            self.is_loaded = True
        except Exception as e:
            self.last_error = str(e)
            self.active_provider = None
            log_print(f"[AI] Failed to load ONNX model: {e}")
            self.session = None
            self.is_loaded = False

    def _fallback_to_cpu(self, reason):
        """Rebuild the ORT session on CPU if DirectML fails at inference time."""
        self._dml_fallback_done = True
        if ort is None or not self.model_path or not os.path.isfile(self.model_path):
            return False
        log_print(f"[AI] DirectML inference failed ({reason}); falling back to CPUExecutionProvider.")
        try:
            opts = ort.SessionOptions()
            opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            opts.intra_op_num_threads = 4
            opts.log_severity_level = 3
            self.session = ort.InferenceSession(
                self.model_path, sess_options=opts, providers=["CPUExecutionProvider"]
            )
            self.active_provider = self.session.get_providers()[0]
            self.last_error = None
            return True
        except Exception as exc:
            self.last_error = str(exc)
            log_print(f"[AI] CPU fallback failed: {exc}")
            return False

    def _load_class_names(self):
        names = None
        if self.session is not None:
            try:
                meta = self.session.get_modelmeta()
                custom = getattr(meta, "custom_metadata_map", None) or {}
                names = _parse_names_metadata(custom.get("names"))
            except Exception as exc:
                log_print(f"[AI] Could not read model metadata class names: {exc}")
                names = None
        self.metadata_names = list(names) if names else None
        if names:
            self.class_names = list(names)
            log_print(f"[AI] Model classes: {self.class_names}")
        else:
            self.class_names = list(DEFAULT_CLASS_NAMES)

    def is_target_class(self, name):
        """True when ``name`` is a class the aim pipeline may target."""
        if name is None:
            return False
        return str(name).strip().lower() in TARGET_CLASS_NAMES

    def _target_class_mask(self, classes):
        """Boolean mask selecting anchors whose class may be targeted.

        One Python lookup per class *id* rather than per anchor; callers pass
        the already confidence-filtered ids so the ``np.unique`` work is paid
        on the survivors only.
        """
        classes = np.asarray(classes)
        if classes.size == 0:
            return np.zeros(classes.shape, dtype=bool)
        unique_ids, inverse = np.unique(classes, return_inverse=True)
        keep = np.array(
            [self.is_target_class(self._class_name_for_id(int(cid))) for cid in unique_ids],
            dtype=bool,
        )
        return keep[inverse]

    def supports_teammate_class(self):
        """True when the loaded model declares a ``teammate`` class.

        This is a question about the *model*, not about the aim allow-list: a
        model that exports ``teammate`` can label a team-mate as such and the
        detector already drops that box in ``_postprocess``. A player-only
        export (``head``/``body`` only) has no way to say "team-mate", so every
        player -- friend or foe -- comes back as ``body``/``head`` and needs the
        colour-outline guard instead.

        Tolerates ``class_names`` being missing or non-iterable (a bare mock in
        tests, an unloaded detector): the answer is then "no", never an
        exception on the tracking thread.
        """
        try:
            names = self.class_names
            if names is None:
                return False
            for name in names:
                if str(name).strip().lower() == "teammate":
                    return True
        except Exception:
            return False
        return False

    def teammate_capability_summary(self):
        """One-line, config-independent description of the model's classes.

        Used verbatim by the Vision UI so the user can see whether the selected
        model can tell a team-mate apart, or whether the enemy-outline guard is
        the only thing standing between them and a friendly-fire aim.
        """
        raw_names = []
        try:
            # ``class_names`` always holds a value (``DEFAULT_CLASS_NAMES`` when
            # metadata could not be read), so neither an unloaded model nor a
            # loaded model without readable metadata may be described as
            # "player-only" from fallback names. Only ``metadata_names`` is
            # authoritative.
            names = getattr(self, "metadata_names", None)
            if names is not None:
                raw_names = [str(name).strip() for name in names if str(name).strip()]
        except Exception:
            raw_names = []
        if not raw_names:
            if self.is_ready():
                return "Class list unavailable (no model metadata)"
            return "Class list unavailable (model not loaded)"
        listing = ", ".join(_dedupe_class_names(raw_names))
        total = len(raw_names)
        if any(name.lower() == "teammate" for name in raw_names):
            return f"Native 'teammate' class: {total} classes ({listing})"
        return (
            f"Player-only (no 'teammate' class): {total} classes ({listing}); "
            "Enemy Outline Guard required"
        )

    def is_ready(self):
        return self.is_loaded and self.session is not None

    def detect(self, image, roi=None):
        """Perform object detection on image / ROI.

        Returns list of dicts:
        [{"class": "body", "bbox": (x, y, w, h), "confidence": float(score)}, ...]
        Only classes whose name is an aim target are ever returned.
        """
        if not self.is_ready() or image is None or image.size == 0:
            return []

        frame_h, frame_w = image.shape[:2]
        offset_x, offset_y = 0, 0
        if roi is not None:
            try:
                rx0, ry0, rx1, ry1 = [int(v) for v in roi[:4]]
                rx0 = max(0, min(rx0, frame_w - 1))
                ry0 = max(0, min(ry0, frame_h - 1))
                rx1 = max(rx0 + 1, min(rx1, frame_w))
                ry1 = max(ry0 + 1, min(ry1, frame_h))
                sub_img = image[ry0:ry1, rx0:rx1]
                offset_x, offset_y = rx0, ry0
            except Exception:
                sub_img = image
        else:
            sub_img = image

        if sub_img.size == 0:
            return []

        target_w, target_h = self.input_size
        img_padded, r, (dw, dh) = letterbox(sub_img, new_shape=(target_h, target_w))

        # BGR -> RGB -> Transpose (H, W, C) to (C, H, W) -> Normalize
        rgb = cv2.cvtColor(img_padded, cv2.COLOR_BGR2RGB)
        dtype = getattr(self, "input_dtype", np.float32)
        tensor = rgb.transpose((2, 0, 1)).astype(dtype) / 255.0
        blob = np.ascontiguousarray(np.expand_dims(tensor, axis=0))

        try:
            preds = self.session.run(None, {self.input_name: blob})
        except Exception as e:
            if (
                not getattr(self, "_dml_fallback_done", False)
                and getattr(self, "active_provider", None) == "DmlExecutionProvider"
                and self._fallback_to_cpu(e)
            ):
                try:
                    preds = self.session.run(None, {self.input_name: blob})
                except Exception as retry_err:
                    self.last_error = str(retry_err)
                    log_print(f"[AI] Inference error after CPU fallback: {retry_err}")
                    return []
            else:
                self.last_error = str(e)
                log_print(f"[AI] Inference error: {e}")
                return []

        if not preds or preds[0] is None:
            return []

        output = preds[0]  # Shape: (1, 5+, N) or (1, N, 5+) or (N, 6)
        return self._postprocess(output, r, dw, dh, offset_x, offset_y, frame_w, frame_h)

    def _postprocess(self, output, r, dw, dh, offset_x, offset_y, frame_w, frame_h):
        # Remove batch dim
        if output.ndim == 3:
            out = output[0]
            # YOLOv8 format: (features, anchors) e.g. (5, 8400) -> transpose to (8400, 5)
            if out.shape[0] < out.shape[1] and out.shape[0] <= 32:
                out = out.transpose((1, 0))
        elif output.ndim == 2:
            out = output
        else:
            return []

        num_cols = out.shape[1]
        boxes = []
        confidences = []
        class_ids = []

        if num_cols >= 5:
            # Check if format has separate objectness (YOLOv5: cx, cy, w, h, obj_conf, cls1, ...)
            # or YOLOv8: cx, cy, w, h, cls1, cls2, ...
            cx = out[:, 0]
            cy = out[:, 1]
            w = out[:, 2]
            h = out[:, 3]

            if num_cols == 5:
                # 1 class: class score is col 4
                scores = out[:, 4]
                classes = np.zeros(len(scores), dtype=int)
            else:
                # Multi-class
                class_scores = out[:, 4:]
                classes = np.argmax(class_scores, axis=1)
                scores = np.max(class_scores, axis=1)

            # Filter by confidence threshold first: the class lookup then runs
            # on the survivors instead of every anchor.
            mask = scores >= self.conf_threshold
            if not np.any(mask):
                return []

            # Drop non-target classes (teammate/breakable/dodge/item/flash)
            # before NMS: a filtered box must not suppress a real target.
            keep = self._target_class_mask(classes[mask])
            if not np.any(keep):
                return []
            indices = np.where(mask)[0][keep]

            cx, cy, w, h = cx[indices], cy[indices], w[indices], h[indices]
            scores = scores[indices]
            classes = classes[indices]

            # Convert letterbox coordinates back to sub_image then full frame coordinates
            x1 = (cx - w / 2.0 - dw) / r + offset_x
            y1 = (cy - h / 2.0 - dh) / r + offset_y
            bw = w / r
            bh = h / r

            for i in range(len(scores)):
                bx = int(round(x1[i]))
                by = int(round(y1[i]))
                box_w = int(round(bw[i]))
                box_h = int(round(bh[i]))

                # Clamp to frame boundary
                bx = max(0, min(bx, frame_w - 1))
                by = max(0, min(by, frame_h - 1))
                box_w = max(1, min(box_w, frame_w - bx))
                box_h = max(1, min(box_h, frame_h - by))

                boxes.append([bx, by, box_w, box_h])
                confidences.append(float(scores[i]))
                class_ids.append(int(classes[i]))

        if not boxes:
            return []

        # Group NMS by resolved class name so multi-ID exports mapped to the
        # same role (e.g. merged dataset body classes) suppress duplicates
        # while distinct roles ('head' vs 'body') remain independent.
        nms_groups = [
            (self._class_name_for_id(cid) or cid) for cid in class_ids
        ]
        detections = []
        for idx in _nms_per_class(boxes, confidences, nms_groups, self.iou_threshold):
            cname = self._class_name_for_id(class_ids[idx])
            if cname is None:
                # No authoritative name for this id: never guess a target name.
                continue
            detections.append({
                "class": cname,
                "bbox": tuple(boxes[idx]),
                "confidence": float(confidences[idx]),
            })

        return detections

    def _class_name_for_id(self, class_id):
        """Map a raw model class id to its name.

        Returns ``None`` when the id has no authoritative name. Mapping an
        unknown id to a target-looking name (``"player"``) would let any class
        the metadata does not describe -- teammate, breakable, dodge, or a
        class a future export adds -- become an aim target as soon as metadata
        is missing or unparsable. Dropping the box is the safe failure: missing
        a target beats aiming at a teammate or a prop.
        """
        try:
            cid = int(class_id)
        except Exception:
            return None
        names = self.class_names or []
        if 0 <= cid < len(names):
            return str(names[cid])
        return None


_BODY_CLASS_NAMES = frozenset({"body", "player", "enemy"})
_HEAD_CLASS_NAME = "head"


def _dedupe_class_names(names):
    """Class names in first-seen order, de-duplicated case-insensitively.

    ``my_yolo_model.onnx`` maps three class ids to ``body``; listing "body"
    three times would read like three different roles.
    """
    seen = set()
    unique = []
    for name in names or []:
        text = str(name).strip()
        key = text.lower()
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(text)
    return unique


def _head_belongs_to_body(body_box, head_box, pad_ratio=0.15):
    """True when ``head_box`` is the head of the player in ``body_box``.

    Mirrors ``main._head_matches_body`` (which cannot be imported here without
    dragging the whole app into the detector module): a head may sit inside the
    body box, or directly on top of a torso-only body box. Horizontal padding
    keeps a slightly off-centre head attached; the vertical slacks scale with
    the body height so the rule works at any distance.
    """
    bx, by, bw, bh = body_box
    hx, hy, hw, hh = head_box
    if bw <= 0 or bh <= 0 or hw <= 0 or hh <= 0:
        return False

    head_cx = hx + hw / 2.0
    head_top = float(hy)
    head_bottom = float(hy + hh)
    pad_x = max(2.0, bw * pad_ratio)
    if not (bx - pad_x <= head_cx <= bx + bw + pad_x):
        return False
    if head_bottom < by - max(4.0, bh * 0.35):
        return False
    if head_top > by + bh * 0.5:
        return False
    return True


def _outline_pixel_count(image, bbox, hsv_min, hsv_max, pad_px=4, inner_px=2):
    """Count enemy-highlight pixels in the *band* around ``bbox``.

    The band is the bbox expanded by ``pad_px`` minus the bbox shrunk by
    ``inner_px``: an enemy highlight is drawn on the silhouette edge, so it
    lands just outside a tight model box or just inside a loose one. Counting
    the whole box would let purple armour or skin certify a team-mate, and
    counting only outside would miss tight boxes.

    Only a small crop is converted, never the full 1080p frame.
    """
    try:
        bx, by, bw, bh = [int(round(float(v))) for v in tuple(bbox)[:4]]
    except Exception:
        return 0
    if bw <= 0 or bh <= 0:
        return 0

    frame_h, frame_w = image.shape[:2]
    x0 = max(0, bx - int(pad_px))
    y0 = max(0, by - int(pad_px))
    x1 = min(frame_w, bx + bw + int(pad_px))
    y1 = min(frame_h, by + bh + int(pad_px))
    if x1 <= x0 or y1 <= y0:
        return 0

    crop = image[y0:y1, x0:x1]
    if crop.ndim == 3 and crop.shape[2] == 4:
        crop = cv2.cvtColor(crop, cv2.COLOR_BGRA2BGR)
    mask = cv2.inRange(cv2.cvtColor(crop, cv2.COLOR_BGR2HSV), hsv_min, hsv_max)

    # Blank the inner rectangle: only the ring may certify the box.
    ix0 = max(0, (bx + int(inner_px)) - x0)
    iy0 = max(0, (by + int(inner_px)) - y0)
    ix1 = min(mask.shape[1], (bx + bw - int(inner_px)) - x0)
    iy1 = min(mask.shape[0], (by + bh - int(inner_px)) - y0)
    if ix1 > ix0 and iy1 > iy0:
        mask[iy0:iy1, ix0:ix1] = 0
    return int(cv2.countNonZero(mask))


def _coerce_min_pixels(value):
    """Clamp ``ai_enemy_outline_min_pixels`` to 1..50 at every use site."""
    try:
        number = int(value)
    except Exception:
        return 4
    return max(1, min(50, number))


def _detector_class_hint(detector):
    """Diagnostic tag for the guard log: can this model name a team-mate?

    ``filter_enemy_detections`` is called from the tracking thread with the
    detector that produced the boxes, and when the guard has to fail open the
    operator needs to know *which* model the guard gave up on: a player-only
    export failing open is a real risk (team-mates become targets), while a
    model with a native ``teammate`` class failing open is harmless because the
    detector already dropped that box. The tag is log-only; it must never
    change a keep/drop decision, otherwise the caller could no longer predict
    what the function does from ``mode`` alone.
    """
    if detector is None:
        return "detector=unknown"
    try:
        names = getattr(detector, "class_names", None)
        supports = getattr(detector, "supports_teammate_class", None)
        if isinstance(names, (list, tuple)) and callable(supports):
            return "detector=native-teammate" if supports() else "detector=player-only"
    except Exception:
        pass
    return "detector=unknown"


def _log_enemy_outline_skip(reason, detector):
    """Throttle fail-open warnings so broken colour config cannot spam every frame."""
    global _last_ai_outline_skip_log_time
    now = time.monotonic()
    if (
        _last_ai_outline_skip_log_time is not None
        and (now - _last_ai_outline_skip_log_time) < _AI_OUTLINE_SKIP_LOG_INTERVAL
    ):
        return
    _last_ai_outline_skip_log_time = now
    log_print(
        f"[AI] Enemy outline guard skipped ({reason}); "
        f"boxes kept unverified ({_detector_class_hint(detector)})"
    )


def filter_enemy_detections(
    detections,
    image,
    detector=None,
    min_pixels=None,
    hsv_min=None,
    hsv_max=None,
    pad_px=4,
    inner_px=2,
    config_module=None,
):
    """Drop boxes that do not carry the enemy highlight around them.

    Player-only models (``head``/``body`` with no ``teammate`` class) label
    team-mates and enemies identically, so every team-mate became an aim
    target. The game draws a coloured outline only around enemies, so the
    detections are verified against that colour: a body/player/enemy box is
    kept only when its outline band holds at least ``min_pixels`` matching
    pixels; a ``head`` box is kept when it belongs to a kept body or, standing
    alone, when its own band passes the same test.

    Deliberately fail-open: with an unusable image or an unresolvable colour band
    the boxes are returned **unverified** and one line is logged. This guard is
    an extra verification step; turning a broken config into "the bot detects
    nothing" would be the worse failure. Fail-open never widens the allow-list,
    though: classes that are not aim targets (``teammate``, ``breakable``,
    ``dodge``, a renamed export) and boxes whose ``bbox`` cannot be parsed are
    dropped on every path, because keeping them would only guarantee a later
    drop in ``main.build_aim_targets`` while making this function's contract
    ("the returned boxes are aim candidates") untrue.

    ``detector`` does not change any keep/drop decision -- ``mode`` alone decides
    whether this function runs, as the plan requires -- but it labels the
    fail-open log with the model's teammate capability, which is the one thing
    that tells an operator whether a fail-open frame is dangerous.

    Returns shallow copies in the original order, with the original ``class``/
    ``bbox``/``confidence`` keys and any extra keys untouched.
    """
    items = list(detections or [])
    if not items:
        return []

    def _copies(source):
        return [dict(det) if isinstance(det, dict) else det for det in source]

    def _aim_candidates(source):
        """Allow-list filtered copies: the fail-open answer, still aim-safe."""
        candidates = []
        for det in source:
            if not isinstance(det, dict):
                continue
            name = str(det.get("class", "")).strip().lower()
            if name not in _BODY_CLASS_NAMES and name != _HEAD_CLASS_NAME:
                continue
            try:
                bx, by, bw, bh = [int(round(float(v))) for v in tuple(det["bbox"])[:4]]
            except Exception:
                continue
            if bw <= 0 or bh <= 0:
                continue
            candidates.append(det)
        return _copies(candidates)

    def _skip(reason):
        _log_enemy_outline_skip(reason, detector)
        return _aim_candidates(items)

    if image is None or not hasattr(image, "shape") or image.size == 0:
        return _skip("no usable image")
    if image.ndim != 3 or int(image.shape[2]) < 3:
        return _skip("image is not 3-channel BGR")
    if image.dtype != np.uint8:
        try:
            image = image.astype(np.uint8)
        except Exception:
            return _skip("image dtype is not uint8")

    if hsv_min is None or hsv_max is None:
        try:
            from src.utils.detection import enemy_outline_hsv_range

            hsv_min, hsv_max = enemy_outline_hsv_range(config_module=config_module)
        except Exception as exc:
            return _skip(f"no HSV band: {exc}")
    try:
        hsv_min = np.asarray(hsv_min, dtype=np.uint8).reshape(3)
        hsv_max = np.asarray(hsv_max, dtype=np.uint8).reshape(3)
    except Exception as exc:
        return _skip(f"bad HSV band: {exc}")
    # An explicit band can bypass ``enemy_outline_hsv_range()``'s validation, and
    # ``cv2.inRange`` with MIN > MAX matches nothing: every box would be dropped
    # as if no enemy had an outline. Treat it as unresolvable and fail open.
    if any(int(lo) > int(hi) for lo, hi in zip(hsv_min, hsv_max)):
        return _skip(f"reversed HSV band: MIN={hsv_min.tolist()} MAX={hsv_max.tolist()}")

    if min_pixels is None:
        module = config_module if config_module is not None else config
        min_pixels = getattr(module, "ai_enemy_outline_min_pixels", 4)
    min_pixels = _coerce_min_pixels(min_pixels)

    parsed = []
    for index, det in enumerate(items):
        if not isinstance(det, dict):
            continue
        try:
            bx, by, bw, bh = [int(round(float(v))) for v in tuple(det["bbox"])[:4]]
        except Exception:
            continue
        if bw <= 0 or bh <= 0:
            continue
        name = str(det.get("class", "")).strip().lower()
        parsed.append((index, name, (bx, by, bw, bh)))

    kept_indexes = set()
    kept_bodies = []
    head_entries = []
    for index, name, box in parsed:
        if name in _BODY_CLASS_NAMES:
            count = _outline_pixel_count(image, box, hsv_min, hsv_max, pad_px, inner_px)
            if count >= min_pixels:
                kept_indexes.add(index)
                kept_bodies.append(box)
        elif name == _HEAD_CLASS_NAME:
            head_entries.append((index, box))
        # Any other class (teammate, breakable, dodge, a renamed export) is not
        # an aim target in the first place: drop it.

    for index, box in head_entries:
        if any(_head_belongs_to_body(body, box) for body in kept_bodies):
            # The head of a verified enemy: the outline wraps the silhouette, so
            # the head box itself may hold little or none of it.
            kept_indexes.add(index)
            continue
        count = _outline_pixel_count(image, box, hsv_min, hsv_max, pad_px, inner_px)
        if count >= min_pixels:
            kept_indexes.add(index)

    return [dict(items[i]) for i in range(len(items)) if i in kept_indexes]


def _as_float(value, fallback):
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _session_signature():
    """Config values that require a new or reconfigured detector."""
    return (
        str(getattr(config, "ai_model_path", "models/valorant_detector.onnx")),
        str(getattr(config, "ai_device", "dml")).strip().lower(),
    )


def _thresholds_from_config():
    return (
        _as_float(getattr(config, "ai_confidence_threshold", 0.45), 0.45),
        _as_float(getattr(config, "ai_iou_threshold", 0.45), 0.45),
    )


def get_ai_detector(force_reload=False):
    """Return the shared detector, following the live config.

    ``ai_model_path`` and ``ai_device`` decide which session exists, so they
    rebuild it. ``ai_confidence_threshold``/``ai_iou_threshold`` are slider
    values consumed in ``_postprocess``: they are pushed onto the existing
    instance instead, so moving a slider never reloads the 36 MB model on the
    tracking thread.

    ``force_reload`` is the UI's explicit "Reload model" button: it rebuilds the
    session even when the config did not change, which is the only way to pick
    up a model file replaced on disk under the same path.

    The rebuild is serialised: the tracking thread calls this every frame while
    the UI thread calls it on a model/device change or "Reload model", and two
    concurrent builds would hold two 36 MB sessions at once. The tracking path
    never *waits* for a rebuild in flight -- it keeps the current instance,
    which is still valid, instead of stalling the frame loop for the ~1.7 s a
    session load takes. The explicit "Reload model" call does wait, because the
    caller asked for the new session and nothing else may start first.
    """
    global _AI_DETECTOR_INSTANCE, _AI_DETECTOR_SIGNATURE
    signature = _session_signature()
    conf_threshold, iou_threshold = _thresholds_from_config()

    if not _AI_DETECTOR_LOCK.acquire(blocking=bool(force_reload)):
        # Another thread is rebuilding (UI model switch or "Reload model").
        # The existing detector is still valid; rebuilding here would allocate a
        # second session and block the tracking thread for the whole load.
        current = _AI_DETECTOR_INSTANCE
        if current is not None:
            return current
        # Nothing to fall back on (first ever build): wait for it.
        _AI_DETECTOR_LOCK.acquire()
    try:
        if (
            _AI_DETECTOR_INSTANCE is None
            or force_reload
            or signature != _AI_DETECTOR_SIGNATURE
        ):
            _AI_DETECTOR_INSTANCE = AIDetector(
                model_path=signature[0],
                device=signature[1],
                conf_threshold=conf_threshold,
                iou_threshold=iou_threshold,
            )
            _AI_DETECTOR_SIGNATURE = signature
        else:
            _AI_DETECTOR_INSTANCE.conf_threshold = conf_threshold
            _AI_DETECTOR_INSTANCE.iou_threshold = iou_threshold
        return _AI_DETECTOR_INSTANCE
    finally:
        _AI_DETECTOR_LOCK.release()
