"""
Hybrid HSV + AI (ONNX) Head Refiner & Model Inspector.

Architecture (Direction 2 - Zero-Blocking 144Hz Hybrid):
1. HSV color detection runs at full 144+ FPS (~0.4 ms) to locate enemy-colored silhouettes
   and guarantee team-color safety (never locks teammates).
2. A lightweight YOLO ONNX model (e.g. YOLO11n 192x192 or YOLOv8 128x128) runs on a 1:1
   pixel crop centered around the HSV candidate bbox in a single-slot (size=1) background
   worker thread (or synchronously for offline/test evaluation).
3. Detected true head coordinates update a short-lived relative bbox anchor
   (rel_dx = head_x - bbox_cx, rel_dy = head_y - bbox_y1) so intermediate 144Hz frames
   track strafing targets with zero main-loop blocking.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, replace
import math
import os
from pathlib import Path
import threading
import time
from typing import Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from src.utils.app_paths import get_app_dir
from src.utils.debug_logger import log_print


_ONNX_DTYPE_NAMES: Dict[int, str] = {
    1: "FP32",
    2: "UINT8",
    3: "INT8",
    6: "INT32",
    7: "INT64",
    10: "FP16",
    11: "FP64",
}

_HEAD_CLASS_KEYWORDS = ("head", "hs", "enemy_head", "headshot", "tete")


@dataclass(frozen=True)
class ModelInspectionReport:
    path: str
    exists: bool
    compatible: bool
    verdict: str
    reason: str
    size_mb: float
    producer: str
    opset: Tuple[int, ...]
    input_name: str
    input_dtype: str
    input_hw: Tuple[int, int]
    output_shapes: Tuple[Tuple[object, ...], ...]
    class_names: Dict[int, str]
    head_class_ids: Tuple[int, ...]
    single_class_mode: bool
    backend: str = "unloaded"
    latency_ms: float = 0.0


@dataclass(frozen=True)
class _RelativeHeadAnchor:
    bbox_cx: float
    bbox_y1: float
    bbox_w: float
    bbox_h: float
    rel_dx: float
    rel_dy: float
    confidence: float
    timestamp: float
    hits: int = 1


_RESOLVED_PATH_CACHE: Dict[str, str] = {}


def resolve_model_path(raw_path: str) -> str:
    txt = str(raw_path or "").strip()
    if not txt:
        return ""
    cached = _RESOLVED_PATH_CACHE.get(txt)
    if cached is not None:
        return cached
    p = Path(txt)
    if p.is_absolute() and p.exists():
        res = str(p)
    else:
        app_candidate = get_app_dir() / txt
        if app_candidate.exists():
            res = str(app_candidate)
        else:
            cwd_candidate = Path.cwd() / txt
            if cwd_candidate.exists():
                res = str(cwd_candidate)
            else:
                res = str(p if p.is_absolute() else app_candidate)
    if os.path.isfile(res):
        _RESOLVED_PATH_CACHE[txt] = res
    return res


# ---------------------------------------------------------------------------
# Pure-Python ONNX Protobuf Header & Graph IO Inspector (zero extra deps)
# ---------------------------------------------------------------------------

def _read_varint(buf: bytes, pos: int) -> Tuple[int, int]:
    result = 0
    shift = 0
    n = len(buf)
    while pos < n:
        b = buf[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            return result, pos
        shift += 7
    return result, pos


def _iter_proto_fields(buf: bytes, start: int = 0, end: Optional[int] = None):
     limit = len(buf) if end is None else end
     pos = start
     while pos < limit:
        tag, pos = _read_varint(buf, pos)
        if tag <= 0:
            break
        field_num = tag >> 3
        wire_type = tag & 0x7
        if wire_type == 0:
            val, pos = _read_varint(buf, pos)
            yield field_num, wire_type, val
        elif wire_type == 1:
            if pos + 8 > limit:
                break
            yield field_num, wire_type, (pos, pos + 8)
            pos += 8
        elif wire_type == 2:
            ln, pos = _read_varint(buf, pos)
            if ln < 0 or pos + ln > limit:
                break
            yield field_num, wire_type, (pos, pos + ln)
            pos += ln
        elif wire_type == 5:
            if pos + 4 > limit:
                break
            yield field_num, wire_type, (pos, pos + 4)
            pos += 4
        else:
            break


def _parse_tensor_shape(buf: bytes, start: int, end: int) -> List[object]:
    dims: List[object] = []
    for fnum, wt, val in _iter_proto_fields(buf, start, end):
        if fnum == 1 and wt == 2:
            ds, de = val
            dval: object = "?"
            for df, dwt, dv in _iter_proto_fields(buf, ds, de):
                if df == 1 and dwt == 0:
                    if dv >= (1 << 63):
                        dv -= (1 << 64)
                    dval = int(dv)
                elif df == 2 and dwt == 2:
                    dval = buf[dv[0]:dv[1]].decode("utf-8", "replace")
            dims.append(dval)
    return dims


def _parse_value_info(buf: bytes, start: int, end: int) -> Dict[str, object]:
    name = ""
    elem_type = 0
    shape: List[object] = []
    for fnum, wt, val in _iter_proto_fields(buf, start, end):
        if fnum == 1 and wt == 2:
            name = buf[val[0]:val[1]].decode("utf-8", "replace")
        elif fnum == 2 and wt == 2:
            for tf, twt, tv in _iter_proto_fields(buf, val[0], val[1]):
                if tf == 1 and twt == 2:
                    for ttf, ttwt, ttv in _iter_proto_fields(buf, tv[0], tv[1]):
                        if ttf == 1 and ttwt == 0:
                            elem_type = int(ttv)
                        elif ttf == 2 and ttwt == 2:
                            shape = _parse_tensor_shape(buf, ttv[0], ttv[1])
    return {
        "name": name,
        "dtype": _ONNX_DTYPE_NAMES.get(elem_type, str(elem_type)),
        "shape": shape,
    }


def _parse_class_names_metadata(raw_names: str) -> Dict[int, str]:
    txt = str(raw_names or "").strip()
    if not txt:
        return {}
    try:
        parsed = ast.literal_eval(txt)
        if isinstance(parsed, dict):
            return {int(k): str(v) for k, v in parsed.items()}
        if isinstance(parsed, (list, tuple)):
            return {idx: str(v) for idx, v in enumerate(parsed)}
    except Exception:
        pass
    return {}


def inspect_onnx_model(model_path: str, run_benchmark: bool = False) -> ModelInspectionReport:
    resolved = resolve_model_path(model_path)
    if not resolved or not os.path.isfile(resolved):
        return ModelInspectionReport(
            path=resolved or str(model_path),
            exists=False,
            compatible=False,
            verdict="INCOMPATIBLE",
            reason="Model file not found",
            size_mb=0.0,
            producer="",
            opset=(),
            input_name="",
            input_dtype="",
            input_hw=(0, 0),
            output_shapes=(),
            class_names={},
            head_class_ids=(),
            single_class_mode=False,
        )

    try:
        with open(resolved, "rb") as f:
            buf = f.read()
    except Exception as exc:
        return ModelInspectionReport(
            path=resolved,
            exists=True,
            compatible=False,
            verdict="INCOMPATIBLE",
            reason=f"Cannot read file: {exc}",
            size_mb=0.0,
            producer="",
            opset=(),
            input_name="",
            input_dtype="",
            input_hw=(0, 0),
            output_shapes=(),
            class_names={},
            head_class_ids=(),
            single_class_mode=False,
        )

    size_mb = round(len(buf) / (1024.0 * 1024.0), 2)
    producer = ""
    opsets: List[int] = []
    metadata: Dict[str, str] = {}
    init_names = set()
    raw_inputs: List[Dict[str, object]] = []
    outputs: List[Dict[str, object]] = []

    for fnum, wt, val in _iter_proto_fields(buf, 0, len(buf)):
        if fnum == 2 and wt == 2:
            producer = buf[val[0]:val[1]].decode("utf-8", "replace")
        elif fnum == 8 and wt == 2:
            for of, owt, ov in _iter_proto_fields(buf, val[0], val[1]):
                if of == 2 and owt == 0:
                    opsets.append(int(ov))
        elif fnum == 14 and wt == 2:
            mk, mv = "", ""
            for mf, mwt, mval in _iter_proto_fields(buf, val[0], val[1]):
                if mf == 1 and mwt == 2:
                    mk = buf[mval[0]:mval[1]].decode("utf-8", "replace")
                elif mf == 2 and mwt == 2:
                    mv = buf[mval[0]:mval[1]].decode("utf-8", "replace")
            if mk:
                metadata[mk] = mv
        elif fnum == 7 and wt == 2:
            for gf, gwt, gv in _iter_proto_fields(buf, val[0], val[1]):
                if gf == 5 and gwt == 2:
                    for tf, twt, tv in _iter_proto_fields(buf, gv[0], gv[1]):
                        if tf == 8 and twt == 2:
                            init_names.add(buf[tv[0]:tv[1]].decode("utf-8", "replace"))
                elif gf == 11 and gwt == 2:
                    raw_inputs.append(_parse_value_info(buf, gv[0], gv[1]))
                elif gf == 12 and gwt == 2:
                    outputs.append(_parse_value_info(buf, gv[0], gv[1]))

    inputs = [i for i in raw_inputs if i.get("name") not in init_names]
    if not inputs or not outputs:
        return ModelInspectionReport(
            path=resolved,
            exists=True,
            compatible=False,
            verdict="INCOMPATIBLE",
            reason="Invalid ONNX graph (missing inputs or outputs)",
            size_mb=size_mb,
            producer=producer,
            opset=tuple(opsets),
            input_name="",
            input_dtype="",
            input_hw=(0, 0),
            output_shapes=(),
            class_names={},
            head_class_ids=(),
            single_class_mode=False,
        )

    in0 = inputs[0]
    in_name = str(in0.get("name", "images"))
    in_dtype = str(in0.get("dtype", "FP32"))
    in_shape = list(in0.get("shape", []))
    if len(in_shape) != 4 or (isinstance(in_shape[1], int) and in_shape[1] != 3):
        return ModelInspectionReport(
            path=resolved,
            exists=True,
            compatible=False,
            verdict="INCOMPATIBLE",
            reason=f"Expected 4D BCHW image input [1,3,H,W], got {in_shape}",
            size_mb=size_mb,
            producer=producer,
            opset=tuple(opsets),
            input_name=in_name,
            input_dtype=in_dtype,
            input_hw=(0, 0),
            output_shapes=tuple(tuple(o.get("shape", ())) for o in outputs),
            class_names={},
            head_class_ids=(),
            single_class_mode=False,
        )

    ih = int(in_shape[2]) if isinstance(in_shape[2], int) and in_shape[2] > 0 else 192
    iw = int(in_shape[3]) if isinstance(in_shape[3], int) and in_shape[3] > 0 else 192
    out_shapes = tuple(tuple(o.get("shape", ())) for o in outputs)
    class_names = _parse_class_names_metadata(metadata.get("names", ""))

    # Infer class count from output tensor if metadata lacks names
    if not class_names and out_shapes:
        s0 = out_shapes[0]
        if len(s0) == 3 and isinstance(s0[1], int) and isinstance(s0[2], int):
            if s0[1] < s0[2] and 5 <= s0[1] <= 36:
                c_cnt = s0[1] - 4
                class_names = {i: f"class_{i}" for i in range(c_cnt)}
            elif s0[2] < s0[1] and 6 <= s0[2] <= 37:
                c_cnt = s0[2] - 5
                class_names = {i: f"class_{i}" for i in range(c_cnt)}

    head_ids = tuple(
        cid
        for cid, cname in sorted(class_names.items())
        if any(kw in cname.strip().lower() for kw in _HEAD_CLASS_KEYWORDS)
    )
    single_class = len(class_names) <= 1 and len(head_ids) == 0

    if not head_ids and not single_class:
        return ModelInspectionReport(
            path=resolved,
            exists=True,
            compatible=False,
            verdict="INCOMPATIBLE",
            reason=f"Multi-class model {class_names} has no 'head' class",
            size_mb=size_mb,
            producer=producer,
            opset=tuple(opsets),
            input_name=in_name,
            input_dtype=in_dtype,
            input_hw=(ih, iw),
            output_shapes=out_shapes,
            class_names=class_names,
            head_class_ids=head_ids,
            single_class_mode=False,
        )

    verdict = "OPTIMAL"
    reason = f"Ready ({iw}x{ih}, classes={class_names or {0: 'target'}})"
    if max(iw, ih) > 320 or size_mb > 30.0:
        verdict = "WARN_HEAVY"
        reason = f"Compatible ({iw}x{ih}, {size_mb:.1f}MB) — heavier model, async mode recommended"

    backend_name = "header_only"
    latency_ms = 0.0
    if run_benchmark:
        try:
            runner = _OnnxRunner(resolved, (ih, iw), in_name, in_dtype)
            backend_name = runner.backend_name
            dummy = np.zeros((ih, iw, 3), dtype=np.uint8)
            for _ in range(2):
                runner.infer(dummy)
            samples = []
            for _ in range(6):
                t0 = time.perf_counter()
                runner.infer(dummy)
                samples.append((time.perf_counter() - t0) * 1000.0)
            latency_ms = round(float(np.median(samples)), 2)
            if latency_ms > 25.0 and verdict == "OPTIMAL":
                verdict = "COMPATIBLE"
            reason = f"{verdict}: {iw}x{ih} on {backend_name} ({latency_ms:.1f}ms)"
        except Exception as exc:
            return ModelInspectionReport(
                path=resolved,
                exists=True,
                compatible=False,
                verdict="INCOMPATIBLE",
                reason=f"Runtime load failed: {exc}",
                size_mb=size_mb,
                producer=producer,
                opset=tuple(opsets),
                input_name=in_name,
                input_dtype=in_dtype,
                input_hw=(ih, iw),
                output_shapes=out_shapes,
                class_names=class_names,
                head_class_ids=head_ids,
                single_class_mode=single_class,
            )

    return ModelInspectionReport(
        path=resolved,
        exists=True,
        compatible=True,
        verdict=verdict,
        reason=reason,
        size_mb=size_mb,
        producer=producer,
        opset=tuple(opsets),
        input_name=in_name,
        input_dtype=in_dtype,
        input_hw=(ih, iw),
        output_shapes=out_shapes,
        class_names=class_names,
        head_class_ids=head_ids,
        single_class_mode=single_class,
        backend=backend_name,
        latency_ms=latency_ms,
    )


# ---------------------------------------------------------------------------
# YOLO Output Decoder & Runtime Execution Wrapper
# ---------------------------------------------------------------------------

def decode_yolo_detections(
    raw_output: np.ndarray,
    img_w: int,
    img_h: int,
    conf_threshold: float = 0.35,
    nms_iou: float = 0.45,
) -> List[Tuple[float, float, float, float, float, int]]:
    """
    Decode YOLOv5 / YOLOv8 / YOLOv10 / YOLOv11 ONNX output tensor into
    sorted list of (cx, cy, w, h, conf, class_id) in crop pixel coordinates.
    """
    if raw_output is None:
        return []
    arr = np.squeeze(np.asarray(raw_output))
    if arr.ndim == 1:
        arr = arr[None, :]
    if arr.ndim != 2 or arr.size == 0:
        return []

    # Case A: End-to-end NMS output [N, 6] -> (x1, y1, x2, y2, score, cls_id)
    if arr.shape[1] == 6 and arr.shape[0] <= 300:
        keep = arr[:, 4] >= conf_threshold
        dets = []
        for row in arr[keep]:
            x1, y1, x2, y2, sc, cid = row
            w = max(0.0, float(x2 - x1))
            h = max(0.0, float(y2 - y1))
            if w > 0.5 and h > 0.5:
                dets.append((float(x1 + x2) * 0.5, float(y1 + y2) * 0.5, w, h, float(sc), int(round(cid))))
        dets.sort(key=lambda d: d[4], reverse=True)
        return dets

    # Case B: YOLOv8 / YOLOv11 transposed [4 + C, anchors] -> [anchors, 4 + C]
    if arr.shape[0] < arr.shape[1] and arr.shape[0] <= 64:
        arr = arr.T

    cols = arr.shape[1]
    if cols < 5:
        return []

    expected_v8_anchors = int(
        (img_w // 8) * (img_h // 8)
        + (img_w // 16) * (img_h // 16)
        + (img_w // 32) * (img_h // 32)
    )
    is_anchor_free = (arr.shape[0] == expected_v8_anchors) or (cols == 5)

    boxes_xywh = arr[:, :4]
    if is_anchor_free:
        cls_scores = arr[:, 4:]
    else:
        cls_scores = arr[:, 4:5] * arr[:, 5:]

    if cls_scores.shape[1] == 1:
        confs = cls_scores[:, 0]
        cls_ids = np.zeros(len(arr), dtype=np.int32)
    else:
        cls_ids = np.argmax(cls_scores, axis=1)
        confs = cls_scores[np.arange(len(arr)), cls_ids]

    mask = confs >= conf_threshold
    if not np.any(mask):
        return []

    b = boxes_xywh[mask]
    c = confs[mask]
    cid = cls_ids[mask]

    # Normalized [0..1] coordinate guard
    if float(np.max(b[:, :2])) <= 1.5 and img_w > 16:
        b = b.copy()
        b[:, 0] *= float(img_w)
        b[:, 2] *= float(img_w)
        b[:, 1] *= float(img_h)
        b[:, 3] *= float(img_h)

    nms_boxes = [
        [float(x - w * 0.5), float(y - h * 0.5), float(w), float(h)]
        for x, y, w, h in b
    ]
    indices = cv2.dnn.NMSBoxes(nms_boxes, c.tolist(), float(conf_threshold), float(nms_iou))
    if len(indices) == 0:
        return []

    results: List[Tuple[float, float, float, float, float, int]] = []
    for idx in np.asarray(indices).flatten():
        x, y, w, h = b[idx]
        results.append((float(x), float(y), float(w), float(h), float(c[idx]), int(cid[idx])))
    results.sort(key=lambda item: item[4], reverse=True)
    return results


class _OnnxRunner:
    """Executes ONNX inference via onnxruntime (CUDA/DirectML/CPU) or cv2.dnn SIMD fallback."""

    def __init__(self, model_path: str, input_hw: Tuple[int, int], input_name: str, input_dtype: str):
        self.model_path = model_path
        self.ih, self.iw = int(input_hw[0]), int(input_hw[1])
        self.input_name = input_name or "images"
        self.is_fp16 = str(input_dtype).upper() == "FP16"
        self._ort_session = None
        self._cv_net = None
        self._cv_lock = threading.Lock()
        self.backend_name = "CPU"
        self._init_runtime()

    def _init_runtime(self) -> None:
        try:
            import onnxruntime as ort  # type: ignore

            avail = list(ort.get_available_providers())
            preferred = []
            for p in ("CUDAExecutionProvider", "DmlExecutionProvider", "CPUExecutionProvider"):
                if p in avail:
                    preferred.append(p)
            if not preferred:
                preferred = avail
            sess_opts = ort.SessionOptions()
            sess_opts.intra_op_num_threads = max(1, min(4, (os.cpu_count() or 4) // 2))
            sess_opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            self._ort_session = ort.InferenceSession(self.model_path, sess_options=sess_opts, providers=preferred)
            active_prov = self._ort_session.get_providers()[0] if self._ort_session.get_providers() else "ORT"
            self.input_name = self._ort_session.get_inputs()[0].name
            self.backend_name = f"ORT:{active_prov.replace('ExecutionProvider', '')}"
            return
        except Exception:
            self._ort_session = None

        # Zero-dependency fallback: OpenCV DNN CPU SIMD (cap thread pool so 4-core CPUs never starve 1kHz HID)
        try:
            max_cv_threads = max(1, min(2, (os.cpu_count() or 4) // 2))
            if cv2.getNumThreads() > max_cv_threads:
                cv2.setNumThreads(max_cv_threads)
        except Exception:
            pass
        net = cv2.dnn.readNetFromONNX(self.model_path)
        net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
        net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
        self._cv_net = net
        self.backend_name = "OpenCV-SIMD"

    _LUT_CACHE: Dict[int, np.ndarray] = {}

    @classmethod
    def _auto_lift_dark_crop(cls, bgr_crop: np.ndarray) -> np.ndarray:
        """
        Automatically lift exposure on Contrast-Crushed OBS-xUDP frames (where p95 V < 90)
        in ~0.03ms via cached LUT so YOLO ONNX models see normal Valorant head contrast without
        requiring the user to disable Contrast Crush on OBS.
        """
        sample = bgr_crop[::4, ::4]
        if sample.size == 0:
            return bgr_crop
        # Measure p95 of HSV Value (max across B,G,R) so dark walls/ceilings don't skew gain
        v_sample = np.max(sample, axis=2) if sample.ndim == 3 else sample
        p95 = int(np.percentile(v_sample, 95))
        if p95 >= 95 or p95 <= 3:
            return bgr_crop
        bucket = max(16, min(92, (p95 // 4) * 4))
        lut = cls._LUT_CACHE.get(bucket)
        if lut is None:
            gain = min(2.20, max(1.35, 72.0 / float(bucket)))
            xs = np.arange(256, dtype=np.float32) / 255.0
            lut = np.clip((xs ** 0.36) * 255.0 * gain, 0.0, 255.0).astype(np.uint8)
            cls._LUT_CACHE[bucket] = lut
        return cv2.LUT(bgr_crop, lut)

    def infer(self, bgr_crop: np.ndarray) -> np.ndarray:
        norm_crop = self._auto_lift_dark_crop(bgr_crop)
        blob = cv2.dnn.blobFromImage(
            norm_crop,
            1.0 / 255.0,
            (self.iw, self.ih),
            swapRB=True,
            crop=False,
        )
        if self.is_fp16:
            blob = blob.astype(np.float16)
        if self._ort_session is not None:
            outs = self._ort_session.run(None, {self.input_name: blob})
            return outs[0]
        with self._cv_lock:
            self._cv_net.setInput(blob)
            return self._cv_net.forward()


# ---------------------------------------------------------------------------
# Hybrid Head Refiner (Async 144Hz Worker + Sync Deterministic Mode)
# ---------------------------------------------------------------------------

class HybridHeadRefiner:
    """
    Refines HSV candidate target head coordinates using a local crop ONNX detector.
    """

    def __init__(self, start_worker: bool = True):
        self._lock = threading.Lock()
        self._slot_cond = threading.Condition()
        self._pending_job: Optional[Tuple[np.ndarray, Tuple[int, int, int, int], float, str]] = None
        self._stop_event = threading.Event()

        self._loaded_path: str = ""
        self._report: Optional[ModelInspectionReport] = None
        self._runner: Optional[_OnnxRunner] = None
        self._load_failed_path: str = ""
        self._last_submit_ts: float = 0.0
        self._last_submit_bbox: Optional[Tuple[int, int, int, int]] = None

        self._anchor: Optional[_RelativeHeadAnchor] = None
        self.last_infer_ms: float = 0.0
        self.last_confidence: float = 0.0
        self.anchor_ttl_sec: float = 0.18

        self._worker: Optional[threading.Thread] = None
        if start_worker:
            self._worker = threading.Thread(target=self._worker_loop, name="HybridHeadRefiner", daemon=True)
            self._worker.start()

    def stop(self) -> None:
        self._stop_event.set()
        with self._slot_cond:
            self._slot_cond.notify_all()
        if self._worker is not None:
            try:
                self._worker.join(timeout=0.5)
            except Exception:
                pass

    @property
    def report(self) -> Optional[ModelInspectionReport]:
        return self._report

    def get_status_summary(self) -> str:
        rep = self._report
        if rep is None:
            return "Idle (no model loaded)"
        if not rep.compatible:
            return f"Invalid: {rep.reason}"
        iw, ih = rep.input_hw[1], rep.input_hw[0]
        bname = self._runner.backend_name if self._runner is not None else rep.backend
        ms_txt = f" | {self.last_infer_ms:.1f}ms" if self.last_infer_ms > 0 else ""
        return f"Ready: {os.path.basename(rep.path)} ({iw}x{ih}, {bname}{ms_txt})"

    def ensure_model_loaded(self, model_path: str) -> bool:
        resolved = resolve_model_path(model_path)
        with self._lock:
            if resolved == self._loaded_path and self._runner is not None:
                return True
            if resolved == self._load_failed_path:
                return False

        rep = inspect_onnx_model(resolved, run_benchmark=False)
        if not rep.compatible:
            with self._lock:
                self._report = rep
                self._runner = None
                self._loaded_path = ""
                self._load_failed_path = resolved
                self._anchor = None
            log_print(f"[HybridAI] Model rejected ({resolved}): {rep.reason}")
            return False

        try:
            runner = _OnnxRunner(rep.path, rep.input_hw, rep.input_name, rep.input_dtype)
            with self._lock:
                self._report = rep
                self._runner = runner
                self._loaded_path = resolved
                self._load_failed_path = ""
                self._anchor = None
            log_print(
                f"[HybridAI] Loaded {os.path.basename(rep.path)} "
                f"({rep.input_hw[1]}x{rep.input_hw[0]}, {runner.backend_name}, classes={rep.class_names})"
            )
            return True
        except Exception as exc:
            failed_rep = replace(
                rep,
                compatible=False,
                verdict="INCOMPATIBLE",
                reason=f"Runtime load failed: {exc}",
            )
            with self._lock:
                self._report = failed_rep
                self._runner = None
                self._loaded_path = ""
                self._load_failed_path = resolved
                self._anchor = None
            log_print(f"[HybridAI] Failed to initialize ONNX runner: {exc}")
            return False

    @staticmethod
    def _extract_1to1_crop(
        img: np.ndarray,
        center_x: int,
        center_y: int,
        crop_w: int,
        crop_h: int,
    ) -> Tuple[np.ndarray, int, int]:
        """
        Extract a 1:1 pixel crop of exact shape (crop_h, crop_w, 3) centered at (center_x, center_y),
        letterbox-padding with 114 if the crop extends past image borders (zero resize distortion).
        Returns (crop_bgr, origin_x0, origin_y0) such that full_x = origin_x0 + local_x.
        """
        img_h, img_w = img.shape[:2]
        x0 = int(center_x - crop_w // 2)
        y0 = int(center_y - crop_h // 2)
        x1 = x0 + crop_w
        y1 = y0 + crop_h

        sx0 = max(0, x0)
        sy0 = max(0, y0)
        sx1 = min(img_w, x1)
        sy1 = min(img_h, y1)

        if sx0 == x0 and sy0 == y0 and sx1 == x1 and sy1 == y1:
            return img[sy0:sy1, sx0:sx1].copy(), x0, y0

        sub = img[sy0:sy1, sx0:sx1]
        pad_left = sx0 - x0
        pad_top = sy0 - y0
        pad_right = x1 - sx1
        pad_bottom = y1 - sy1
        if sub.size == 0:
            canvas = np.full((crop_h, crop_w, 3), 114, dtype=np.uint8)
            return canvas, x0, y0
        padded = cv2.copyMakeBorder(
            sub,
            pad_top,
            pad_bottom,
            pad_left,
            pad_right,
            cv2.BORDER_CONSTANT,
            value=(114, 114, 114),
        )
        return padded, x0, y0

    @staticmethod
    def _select_best_head_for_bbox(
        dets: Sequence[Tuple[float, float, float, float, float, int]],
        crop_x0: int,
        crop_y0: int,
        bbox: Tuple[int, int, int, int],
        report: ModelInspectionReport,
    ) -> Optional[Tuple[float, float, float]]:
        """
        Match AI detections to the HSV-verified enemy bbox (x1, y1, x2, y2).
        Returns (head_x, head_y, confidence) in full-image coordinates or None.
        """
        x1, y1, x2, y2 = bbox
        bw = max(1.0, float(x2 - x1))
        bh = max(1.0, float(y2 - y1))
        bbox_cx = 0.5 * float(x1 + x2)

        # Spatial association window anchored around upper HSV bbox + head region above shoulders
        min_fx = float(x1) - max(10.0, 0.40 * bw)
        max_fx = float(x2) + max(10.0, 0.40 * bw)
        min_fy = float(y1) - max(20.0, 0.90 * bw)
        max_fy = float(y1) + max(14.0, 0.60 * bh)

        best_candidate: Optional[Tuple[float, float, float, float]] = None  # (score, hx, hy, conf)

        for dcx, dcy, dw, dh, conf, cid in dets:
            if report.head_class_ids and cid not in report.head_class_ids:
                continue

            fx = float(crop_x0) + float(dcx)
            fy = float(crop_y0) + float(dcy)

            if not report.head_class_ids:
                # Single-class detector (e.g. YOLO11n {0: 'Enemy'} head-box or full-body model):
                # Strictly separate compact head boxes (~10x13) from full-body/crouched boxes (~22x42)
                # relative to HSV silhouette (bw, bh) so body boxes NEVER drag aim to stomach center!
                d_aspect = float(dw) / max(1.0, float(dh))
                is_head_only_silhouette = (bh <= 20.0 and bw <= 22.0 and (bw / max(1.0, bh)) >= 0.78)
                max_head_h = max(16.0, bh * 0.85) if is_head_only_silhouette else max(16.0, bh * 0.48)
                max_head_w = max(18.0, bw * 0.95) if is_head_only_silhouette else max(18.0, bw * 0.88)
                is_compact_head = (
                    dw <= max_head_w
                    and dh <= max_head_h
                    and 0.50 <= d_aspect <= 1.75
                )
                if not is_compact_head:
                    if dh >= 18.0 and d_aspect <= 0.95:
                        # Full-body / crouched silhouette box -> map strictly to anatomical head center (top 10%)
                        fy = (float(crop_y0) + float(dcy) - 0.5 * float(dh)) + 0.10 * float(dh)
                    else:
                        continue

            if not (min_fx <= fx <= max_fx and min_fy <= fy <= max_fy):
                continue

            horiz_dist = abs(fx - bbox_cx) / max(12.0, bw)
            rank_score = float(conf) - 0.15 * horiz_dist
            if best_candidate is None or rank_score > best_candidate[0]:
                best_candidate = (rank_score, fx, fy, float(conf))

        if best_candidate is None:
            return None
        return best_candidate[1], best_candidate[2], best_candidate[3]

    def _run_crop_inference(
        self,
        img: np.ndarray,
        bbox: Tuple[int, int, int, int],
        conf_threshold: float,
    ) -> Optional[Tuple[float, float, float]]:
        with self._lock:
            runner = self._runner
            report = self._report
        if runner is None or report is None or not report.compatible:
            return None

        x1, y1, x2, y2 = bbox
        bw = max(1, x2 - x1)
        bh = max(1, y2 - y1)
        # Center crop slightly below y1 so plenty of headroom above shoulders is captured
        crop_cx = int(round(0.5 * (x1 + x2)))
        crop_cy = int(round(y1 + min(18.0, 0.25 * bh)))
        ih, iw = report.input_hw

        crop, ox0, oy0 = self._extract_1to1_crop(img, crop_cx, crop_cy, iw, ih)
        t0 = time.perf_counter()
        raw_out = runner.infer(crop)
        infer_ms = (time.perf_counter() - t0) * 1000.0

        dets = decode_yolo_detections(raw_out, iw, ih, conf_threshold=conf_threshold)
        matched = self._select_best_head_for_bbox(dets, ox0, oy0, bbox, report)
        self.last_infer_ms = infer_ms
        if matched is None:
            return None

        hx, hy, conf = matched
        self.last_confidence = conf
        bbox_cx = 0.5 * float(x1 + x2)
        bbox_y1 = float(y1)
        new_rel_dx = hx - bbox_cx
        new_rel_dy = hy - bbox_y1
        now = time.perf_counter()

        with self._lock:
            prev = self._anchor
            if (
                prev is not None
                and (now - prev.timestamp) <= self.anchor_ttl_sec
                and math.hypot(bbox_cx - prev.bbox_cx, bbox_y1 - prev.bbox_y1) <= max(28.0, 0.85 * max(bw, bh))
            ):
                # Light EMA on relative offset eliminates 1px anchor shimmer while keeping 144Hz motion 1:1
                alpha = 0.65
                rel_dx = alpha * new_rel_dx + (1.0 - alpha) * prev.rel_dx
                rel_dy = alpha * new_rel_dy + (1.0 - alpha) * prev.rel_dy
                hits = min(10, int(prev.hits) + 1)
            else:
                rel_dx = new_rel_dx
                rel_dy = new_rel_dy
                hits = 1

            self._anchor = _RelativeHeadAnchor(
                bbox_cx=bbox_cx,
                bbox_y1=bbox_y1,
                bbox_w=float(bw),
                bbox_h=float(bh),
                rel_dx=rel_dx,
                rel_dy=rel_dy,
                confidence=conf,
                timestamp=now,
                hits=hits,
            )
        return bbox_cx + rel_dx, bbox_y1 + rel_dy, conf

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            with self._slot_cond:
                while self._pending_job is None and not self._stop_event.is_set():
                    self._slot_cond.wait(timeout=0.1)
                if self._stop_event.is_set():
                    return
                job = self._pending_job
                self._pending_job = None

            if job is not None:
                img, bbox, conf_thr, m_path = job
                try:
                    if self.ensure_model_loaded(m_path):
                        self._run_crop_inference(img, bbox, conf_thr)
                except Exception as exc:
                    log_print(f"[HybridAI] Worker inference error: {exc}")

    def refine_head(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        full_bgr_img: np.ndarray,
        fallback_hx: float,
        fallback_hy: float,
        model_path: str,
        conf_threshold: float = 0.35,
        sync: bool = False,
    ) -> Tuple[float, float, bool]:
        """
        Refine (head_x, head_y) for an HSV-detected enemy bbox.
        Returns (hx, hy, used_ai).
        """
        if full_bgr_img is None or full_bgr_img.size == 0:
            return fallback_hx, fallback_hy, False

        bbox = (int(x1), int(y1), int(x2), int(y2))
        if sync:
            if not self.ensure_model_loaded(model_path):
                return fallback_hx, fallback_hy, False
            res = self._run_crop_inference(full_bgr_img, bbox, conf_threshold)
            if res is not None:
                return res[0], res[1], True
            return fallback_hx, fallback_hy, False

        resolved = resolve_model_path(model_path)
        now = time.perf_counter()
        bbox_cx = 0.5 * float(x1 + x2)
        bbox_y1 = float(y1)
        bw = max(1.0, float(x2 - x1))
        bh = max(1.0, float(y2 - y1))

        with self._lock:
            failed = (not resolved) or (resolved == self._load_failed_path)
            anc = self._anchor
            bname = self._runner.backend_name if self._runner is not None else "CPU"
        if failed:
            return fallback_hx, fallback_hy, False

        # Throttle CPU-backed worker submissions (~22 Hz max steady-state) so 4-core CPUs never saturate,
        # while dispatching immediately on first target sighting or large bbox jump (>14px).
        is_gpu_ort = bname.startswith("ORT:CUDA") or bname.startswith("ORT:Dml")
        min_interval = 0.014 if is_gpu_ort else 0.045
        jumped = True
        if self._last_submit_bbox is not None:
            px1, py1, px2, py2 = self._last_submit_bbox
            jumped = math.hypot(bbox_cx - 0.5 * (px1 + px2), bbox_y1 - float(py1)) > 14.0
        if anc is None or jumped or (now - self._last_submit_ts) >= min_interval:
            self._last_submit_ts = now
            self._last_submit_bbox = bbox
            with self._slot_cond:
                self._pending_job = (full_bgr_img, bbox, float(conf_threshold), resolved)
                self._slot_cond.notify()

        if (
            anc is not None
            and (now - anc.timestamp) <= self.anchor_ttl_sec
            and math.hypot(bbox_cx - anc.bbox_cx, bbox_y1 - anc.bbox_y1) <= max(32.0, 0.90 * max(bw, bh))
        ):
            ai_hx = bbox_cx + anc.rel_dx
            ai_hy = bbox_y1 + anc.rel_dy
            # Smooth 3-hit ramp prevents sudden 6-8px step jump on first async ONNX arrival
            # from spiking ABCurves velocity_lead or triggering a turn queue flush.
            w_ai = min(1.0, 0.50 + 0.25 * float(max(0, int(anc.hits) - 1)))
            age = now - anc.timestamp
            if age > 0.12:
                w_ai *= max(0.0, 1.0 - (age - 0.12) / max(0.01, self.anchor_ttl_sec - 0.12))
            blended_x = fallback_hx + w_ai * (ai_hx - fallback_hx)
            blended_y = fallback_hy + w_ai * (ai_hy - fallback_hy)
            return blended_x, blended_y, True

        return fallback_hx, fallback_hy, False
