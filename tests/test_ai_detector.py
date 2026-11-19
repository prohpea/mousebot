"""
Unit tests for AIDetector, letterboxing, NMS, and detection pipeline integration.

Covers the Valorant YOLO11s export used by the bot: class names come from the
ONNX ``custom_metadata_map['names']`` (body/head/teammate/breakable/dodge), not
from a hardcoded list, and only real targets survive ``_postprocess``.
"""
import os
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

from src.utils.config import config
from src.utils.ai_detection import (
    AIDetector,
    TARGET_CLASS_NAMES,
    _parse_names_metadata,
    letterbox,
    get_ai_detector,
)
from src.utils import detection


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_PATH = os.path.join(REPO_ROOT, "models", "valorant_detector.onnx")
REFERENCE_IMAGE = os.path.join(
    r"C:\Users\TeamOS\Downloads\valorant-ai-aim-main",
    "valorant-ai-aim-main",
    "test.png",
)
METADATA_NAMES = ["body", "head", "teammate", "breakable", "dodge"]


def _bare_detector(class_names):
    """An AIDetector with no session, enough to exercise pure post-processing."""
    det = AIDetector.__new__(AIDetector)
    det.conf_threshold = 0.30
    det.iou_threshold = 0.50
    det.class_names = list(class_names)
    det.metadata_names = list(class_names)
    det.session = None
    det.input_name = None
    det.input_size = (640, 640)
    det.input_shape = (1, 3, 640, 640)
    det.is_loaded = False
    return det


def _yolo_output(rows):
    """Build a ``(1, 4 + num_classes, anchors)`` YOLO11-style output.

    ``rows`` items are ``(cx, cy, w, h, [class scores])``. The anchor count is
    padded above the feature count so the ``(features, anchors)`` layout is
    unambiguous (as in a real export, where anchors >> 4 + classes).
    """
    num_classes = max(len(row[4]) for row in rows)
    num_anchors = max(len(rows), 4 + num_classes + 8)
    out = np.zeros((1, 4 + num_classes, num_anchors), dtype=np.float32)
    for anchor, (cx, cy, w, h, scores) in enumerate(rows):
        out[0, 0, anchor] = cx
        out[0, 1, anchor] = cy
        out[0, 2, anchor] = w
        out[0, 3, anchor] = h
        for cls_idx, score in enumerate(scores):
            out[0, 4 + cls_idx, anchor] = score
    return out


class _ConfigSandbox:
    """Pin config values for one test and always restore them."""

    def __init__(self, **values):
        self.values = values
        self.previous = {}

    def __enter__(self):
        for key, value in self.values.items():
            self.previous[key] = getattr(config, key, "__missing__")
            setattr(config, key, value)
        return self

    def __exit__(self, *exc_info):
        for key, value in self.previous.items():
            if value == "__missing__":
                try:
                    delattr(config, key)
                except AttributeError:
                    pass
            else:
                setattr(config, key, value)
        return False


class TestAIDetection(unittest.TestCase):
    def test_zero_confidence_threshold_is_not_silently_replaced(self):
        """``0.0`` is a legitimate "keep everything" setting, not "unset"."""
        det = AIDetector(model_path="non_existent_model.onnx", conf_threshold=0.0)
        self.assertEqual(det.conf_threshold, 0.0)
        det2 = AIDetector(model_path="non_existent_model.onnx")
        self.assertAlmostEqual(det2.conf_threshold, float(config.ai_confidence_threshold))

    def test_zero_iou_threshold_is_not_silently_replaced(self):
        det = AIDetector(model_path="non_existent_model.onnx", iou_threshold=0.0)
        self.assertEqual(det.iou_threshold, 0.0)

    def test_letterbox_shapes_and_ratios(self):
        img = np.zeros((720, 1280, 3), np.uint8)
        boxed, r, (dw, dh) = letterbox(img, new_shape=(640, 640))
        self.assertEqual(boxed.shape, (640, 640, 3))
        expected_r = 640.0 / 1280.0
        self.assertAlmostEqual(r, expected_r)
        self.assertAlmostEqual(dw, 0.0)
        self.assertAlmostEqual(dh, (640.0 - 720.0 * expected_r) / 2.0)

    def test_detector_missing_model_graceful(self):
        det = AIDetector(model_path="non_existent_model.onnx")
        self.assertFalse(det.is_ready())
        res = det.detect(np.zeros((480, 640, 3), np.uint8))
        self.assertEqual(res, [])

    def test_postprocess_yolov8_format(self):
        det = AIDetector(model_path="non_existent_model.onnx")
        det.conf_threshold = 0.40
        det.iou_threshold = 0.50

        # Create synthetic YOLOv8 output: shape (1, 5, 8400)
        # 5 features: [cx, cy, w, h, class0_score]
        out = np.zeros((1, 5, 8400), dtype=np.float32)

        # Place box 1 at anchor 10
        out[0, 0, 10] = 320.0  # cx
        out[0, 1, 10] = 320.0  # cy
        out[0, 2, 10] = 50.0   # w
        out[0, 3, 10] = 100.0  # h
        out[0, 4, 10] = 0.90   # conf

        # Place box 2 at anchor 20
        out[0, 0, 20] = 100.0
        out[0, 1, 20] = 100.0
        out[0, 2, 20] = 30.0
        out[0, 3, 20] = 60.0
        out[0, 4, 20] = 0.85

        r = 1.0
        dw, dh = 0.0, 0.0
        offset_x, offset_y = 0, 0
        frame_w, frame_h = 640, 640

        detections = det._postprocess(out, r, dw, dh, offset_x, offset_y, frame_w, frame_h)
        self.assertEqual(len(detections), 2)
        classes = [d["class"] for d in detections]
        self.assertIn("enemy", classes)
        for d in detections:
            self.assertIn("bbox", d)
            self.assertEqual(len(d["bbox"]), 4)
            self.assertGreaterEqual(d["confidence"], 0.80)

    def test_detection_analyze_fallback_to_hsv_when_ai_disabled(self):
        with _ConfigSandbox(ai_detection_enabled=False):
            detection.load_model()
            img = np.zeros((200, 200, 3), np.uint8)
            frame = detection.analyze(detection._model, img)
        self.assertIsNotNone(frame)
        self.assertEqual(len(frame.detections), 0)

    def test_detection_analyze_with_ai_enabled_mock(self):
        mock_detector = MagicMock()
        mock_detector.is_ready.return_value = True
        mock_detector.detect.return_value = [
            {"class": "player", "bbox": (50, 60, 40, 80), "confidence": 0.95}
        ]
        with _ConfigSandbox(ai_detection_enabled=True):
            with patch("src.utils.ai_detection.get_ai_detector", return_value=mock_detector):
                img = np.zeros((200, 200, 3), np.uint8)
                frame = detection.analyze(None, img)
        self.assertEqual(len(frame.detections), 1)
        self.assertEqual(frame.detections[0]["confidence"], 0.95)
        self.assertEqual(frame.detections[0]["bbox"], (50, 60, 40, 80))

    def test_colour_model_still_runs_the_colour_pass_when_ai_is_enabled(self):
        """Supplying an HSV model must mean "colour pass", not "whatever the flag says".

        With the shipped ``config.json`` (``ai_detection_enabled: true``) the AI
        branch used to hijack every caller that had explicitly handed in an HSV
        model, so the colour pass became unreachable and every HSV suite
        measured ONNX detections instead.
        """
        mock_detector = MagicMock()
        mock_detector.is_ready.return_value = True
        mock_detector.detect.return_value = [
            {"class": "body", "bbox": (20, 30, 40, 90), "confidence": 0.91}
        ]
        with _ConfigSandbox(ai_detection_enabled=True):
            with patch("src.utils.ai_detection.get_ai_detector", return_value=mock_detector):
                detection.load_model()
                img = np.zeros((240, 320, 3), np.uint8)
                frame = detection.analyze(detection._model, img)

        mock_detector.detect.assert_not_called()
        self.assertEqual(frame.source, "hsv")
        self.assertIsNotNone(frame.mask)
        self.assertEqual(frame.mask.shape, (240, 320))

    def test_detection_ai_path_runs_without_hsv_model(self):
        """AI detection must not depend on HSV params being loaded."""
        mock_detector = MagicMock()
        mock_detector.is_ready.return_value = True
        mock_detector.detect.return_value = [
            {"class": "body", "bbox": (20, 30, 40, 90), "confidence": 0.91}
        ]
        with _ConfigSandbox(ai_detection_enabled=True):
            with patch("src.utils.ai_detection.get_ai_detector", return_value=mock_detector):
                img = np.zeros((240, 320, 3), np.uint8)
                frame = detection.analyze(None, img)
        self.assertEqual(len(frame.detections), 1)
        self.assertEqual(frame.detections[0]["class"], "body")
        mock_detector.detect.assert_called_once()

    def test_ai_only_frame_still_carries_a_usable_mask(self):
        """An AI-only frame must hand Triggerbot a mask instead of ``None``.

        ``Triggerbot`` falls back to ``cv2.inRange(hsv, model[0], model[1])``
        when ``raw_mask`` is None, so a ``None`` mask plus a ``None`` HSV model
        raised a ``TypeError`` every frame -- swallowed by ``normal.py``, which
        left the triggerbot silently dead exactly in AI-only mode.
        """
        mock_detector = MagicMock()
        mock_detector.is_ready.return_value = True
        mock_detector.detect.return_value = [
            {"class": "body", "bbox": (20, 30, 40, 90), "confidence": 0.91}
        ]
        with _ConfigSandbox(ai_detection_enabled=True, detection_return_raw_mask=True):
            with patch("src.utils.ai_detection.get_ai_detector", return_value=mock_detector):
                img = np.zeros((240, 320, 3), np.uint8)
                frame = detection.analyze(None, img)

        self.assertIsNotNone(frame.raw_mask, "AI-only frames must provide a mask")
        self.assertEqual(frame.raw_mask.shape, (240, 320))
        self.assertEqual(frame.mask_nonzero, 40 * 90)
        self.assertEqual(int(frame.raw_mask[30:120, 20:60].min()), 255)
        self.assertEqual(int(frame.raw_mask[0, 0]), 0)

    def test_ai_mask_is_built_lazily_and_only_once(self):
        """No consumer, no full-frame allocation and no full-frame pixel count.

        The mask is nothing but the boxes rasterised onto a frame-sized array.
        Building it eagerly cost a 2 MP allocation plus a 2 MP ``countNonZero``
        on every AI frame -- including the shipped config where the triggerbot
        that reads it is disabled. Reading it must still produce the same mask,
        and a second read must not rebuild it.
        """
        mock_detector = MagicMock()
        mock_detector.is_ready.return_value = True
        mock_detector.detect.return_value = [
            {"class": "body", "bbox": (20, 30, 40, 90), "confidence": 0.91}
        ]
        with _ConfigSandbox(ai_detection_enabled=True):
            with patch("src.utils.ai_detection.get_ai_detector", return_value=mock_detector):
                with patch.object(
                    detection, "_ai_detection_mask", wraps=detection._ai_detection_mask
                ) as builder:
                    frame = detection.analyze(None, np.zeros((240, 320, 3), np.uint8))
                    self.assertEqual(builder.call_count, 0, "the mask was rasterised eagerly")
                    self.assertTrue(frame.has_mask, "an AI frame must advertise its mask")

                    mask = frame.raw_mask
                    self.assertEqual(builder.call_count, 1)
                    self.assertEqual(mask.shape, (240, 320))
                    self.assertEqual(frame.mask_nonzero, 40 * 90)

                    # Cached: a second consumer must not pay for it again.
                    self.assertIs(frame.mask, mask)
                    self.assertIs(frame.raw_mask, mask)
                    self.assertEqual(builder.call_count, 1)

    def test_ai_mask_is_not_built_when_nothing_consumes_it(self):
        """Checking ``has_mask`` must not materialise the mask."""
        frame = detection.DetectionFrame(
            [{"class": "body", "bbox": (0, 0, 10, 10), "confidence": 0.9}],
            None,
            None,
            (0, 0, 640, 480),
            False,
            None,
            (480, 640),
            source="ai",
            mask_factory=MagicMock(side_effect=AssertionError("built without a consumer")),
        )
        self.assertTrue(frame.has_mask)
        self.assertEqual(frame._mask, None)

    def test_empty_ai_result_stays_empty_and_does_not_fall_back(self):
        """An empty AI answer is an answer, not a failure.

        Falling through to the colour pass whenever the AI model finds nothing
        would make the engine swap silently ineffective: in AI mode a frame with
        no enemy would be re-detected as a colour blob and aimed at. The colour
        fallback is reserved for a detector that cannot run at all.
        """
        mock_detector = MagicMock()
        mock_detector.is_ready.return_value = True
        mock_detector.detect.return_value = []
        with _ConfigSandbox(ai_detection_enabled=True):
            with patch("src.utils.ai_detection.get_ai_detector", return_value=mock_detector):
                frame = detection.analyze(
                    detection._model, np.zeros((240, 320, 3), np.uint8), engine="ai"
                )

        self.assertEqual(frame.detections, [])
        self.assertEqual(frame.source, "ai")
        self.assertFalse(frame.has_mask)
        self.assertIsNone(frame.raw_mask, "an empty AI frame must not build a mask")

    def test_unusable_ai_detector_falls_back_to_the_colour_model(self):
        """No onnxruntime / missing file must still leave the bot able to see."""
        broken = MagicMock()
        broken.is_ready.return_value = False
        with _ConfigSandbox(ai_detection_enabled=True):
            detection.load_model()
            self.assertIsNotNone(detection._model, "the HSV model failed to load")
            with patch("src.utils.ai_detection.get_ai_detector", return_value=broken):
                frame = detection.analyze(
                    detection._model, np.zeros((240, 320, 3), np.uint8), engine="ai"
                )

        self.assertEqual(frame.source, "hsv", "an unusable AI detector must not blind the bot")
        self.assertIsNotNone(frame.mask)

    def test_track_frame_asks_for_the_selected_engine_explicitly(self):
        """The tracker must name the engine instead of letting config decide.

        ``analyze`` used to consult ``ai_detection_enabled`` on its own, so a
        caller that handed over an HSV model was silently rerouted to ONNX. The
        tracker owns the choice now, and still passes the colour model through so
        the AI branch can fall back to it when the detector cannot load.
        """
        import main as main_module

        tracker = main_module.AimTracker.__new__(main_module.AimTracker)
        tracker.app = MagicMock()
        tracker.app.capture.get_frame_meta.return_value = {}
        tracker.app.capture.apply_mode_fov.side_effect = lambda frame: frame
        tracker._last_frame_seq = 1
        tracker._last_engine_toggle_key_state = False
        tracker.model = np.array([[0, 0, 0], [255, 255, 255]], dtype=np.uint8)
        tracker.perf = {}
        tracker._frame_count = 0
        tracker._last_frame_log_time = 0.0
        tracker._target_smoother = MagicMock()
        tracker._draw_enhanced_detection = MagicMock(side_effect=lambda img, *a: img)
        tracker._draw_fovs = MagicMock()
        tracker._draw_body = MagicMock()
        tracker._draw_head_bbox = MagicMock()
        tracker._update_raw_stream_windows = MagicMock()
        tracker._aim_and_move = MagicMock()
        tracker._compute_detection_roi = MagicMock(return_value=None)

        selected = []

        def fake_analyze(model, image, roi=None, engine=None):
            selected.append((model, engine))
            return detection.DetectionFrame([], None, None, None, False, 0, None)

        img = np.zeros((120, 160, 3), np.uint8)
        with patch.object(main_module, "analyze", side_effect=fake_analyze):
            for enabled, expected in ((True, "ai"), (False, "hsv")):
                selected.clear()
                with _ConfigSandbox(
                    ai_detection_enabled=enabled,
                    detection_engine="ai_detection" if enabled else "colorbot",
                    ai_toggle_key="",
                    show_opencv_windows=False,
                    enable_target_temporal_smoothing=False,
                    detection_roi_enabled=False,
                ):
                    tracker._track_frame(img)

                self.assertEqual(len(selected), 1)
                model, engine = selected[0]
                self.assertEqual(engine, expected, "the tracker did not name the engine")
                self.assertIs(
                    model, tracker.model,
                    "the colour model must stay available for the AI fallback",
                )

    def test_ai_mask_is_full_frame_so_a_trigger_roi_can_always_be_sliced(self):
        """The AI mask must cover the frame, whatever ROI detection used.

        Triggerbot picks its own centre ROI, independently of the detection
        ROI. A mask that only covers the detection crop cannot be sliced for a
        trigger ROI outside it: ``slice_mask_for_roi`` then returns ``None`` and
        Triggerbot falls back to HSV parameters -- which do not exist in
        AI-only mode.
        """
        from src.aim_system.Triggerbot import slice_mask_for_roi

        mock_detector = MagicMock()
        mock_detector.is_ready.return_value = True
        mock_detector.detect.return_value = [
            {"class": "head", "bbox": (120, 110, 20, 20), "confidence": 0.87}
        ]
        with _ConfigSandbox(ai_detection_enabled=True, detection_roi_max_fraction=0.70):
            with patch("src.utils.ai_detection.get_ai_detector", return_value=mock_detector):
                img = np.zeros((240, 320, 3), np.uint8)
                frame = detection.analyze(None, img, roi=(100, 100, 220, 220))

        self.assertEqual(frame.raw_mask.shape, (240, 320))
        self.assertEqual(int(frame.raw_mask[110:130, 120:140].min()), 255)
        self.assertEqual(int(frame.raw_mask[0, 0]), 0)
        self.assertEqual(frame.mask_nonzero, 20 * 20)

        # A trigger ROI far outside the detection ROI still slices cleanly.
        sliced = slice_mask_for_roi(frame.raw_mask, None, 160, 160, 176, 176)
        self.assertIsNotNone(sliced, "the AI mask could not be sliced for the trigger ROI")
        self.assertEqual(sliced.shape, (16, 16))
        # And the detection itself is inside it.
        sliced_head = slice_mask_for_roi(frame.raw_mask, None, 118, 108, 142, 132)
        self.assertIsNotNone(sliced_head)
        self.assertGreater(int(sliced_head.max()), 0)


    def test_ai_frames_are_not_run_through_the_colour_anti_smoke_filter(self):
        """Anti-smoke judges colour statistics; an AI mask is the bbox itself.

        The mask rasterised from detections is perfectly filled, so the
        fill-ratio/density rules would classify a real detection as smoke and
        drop every AI target. ``main`` must skip that filter for AI frames.
        """
        import main as main_module

        tracker = main_module.AimTracker.__new__(main_module.AimTracker)
        tracker.app = MagicMock()
        tracker.app.capture.get_frame_meta.return_value = {}
        tracker.app.capture.apply_mode_fov.side_effect = lambda frame: frame
        tracker._last_frame_seq = 1
        tracker._last_engine_toggle_key_state = False
        tracker.model = None  # no HSV model: this is the AI-only path
        tracker.perf = {}
        tracker._frame_count = 0
        tracker._last_frame_log_time = 0.0
        tracker._target_smoother = MagicMock()
        tracker._draw_enhanced_detection = MagicMock(side_effect=lambda img, *a: img)
        tracker._draw_fovs = MagicMock()
        tracker._draw_body = MagicMock()
        tracker._draw_head_bbox = MagicMock()
        tracker._update_raw_stream_windows = MagicMock()
        tracker._build_target_features = MagicMock(return_value={})
        tracker._filter_targets_with_anti_smoke = MagicMock(side_effect=lambda targets, *a, **k: targets)
        tracker._aim_and_move = MagicMock()

        detector = MagicMock()
        detector.is_ready.return_value = True
        detector.detect.return_value = [
            {"class": "body", "bbox": (140, 80, 40, 90), "confidence": 0.93},
            {"class": "head", "bbox": (148, 80, 22, 22), "confidence": 0.87},
        ]

        with _ConfigSandbox(
            ai_detection_enabled=True,
            show_opencv_windows=False,
            show_opencv_mask=False,
            show_opencv_detection=False,
            detection_roi_enabled=False,
            enable_target_temporal_smoothing=False,
            aim_type="head",
            anti_smoke_enabled=True,
            anti_smoke_enabled_sec=True,
        ):
            with patch("src.utils.ai_detection.get_ai_detector", return_value=detector):
                tracker._track_frame(np.zeros((240, 320, 3), np.uint8))

        tracker._filter_targets_with_anti_smoke.assert_not_called()
        tracker._build_target_features.assert_not_called()
        tracker._aim_and_move.assert_called_once()
        targets = tracker._aim_and_move.call_args[0][0]
        self.assertEqual(len(targets), 1, "the AI detection was dropped before aiming")
        self.assertAlmostEqual(targets[0][0], 159.0)
        self.assertAlmostEqual(targets[0][1], 91.0)

    def test_head_estimation_ignores_the_rasterised_ai_mask(self):
        """A body-only AI detection must estimate from geometry, not the mask.

        The AI mask is the body box filled in, so head refinement would find
        "head pixels" across the whole box and aim at its vertical centre
        instead of the configured head ratio.
        """
        import main as main_module

        tracker = main_module.AimTracker.__new__(main_module.AimTracker)
        tracker.app = MagicMock()
        tracker.app.capture.get_frame_meta.return_value = {}
        tracker.app.capture.apply_mode_fov.side_effect = lambda frame: frame
        tracker._last_frame_seq = 1
        tracker._last_engine_toggle_key_state = False
        tracker.model = None
        tracker.perf = {}
        tracker._frame_count = 0
        tracker._last_frame_log_time = 0.0
        tracker._target_smoother = MagicMock()
        tracker._draw_enhanced_detection = MagicMock(side_effect=lambda img, *a: img)
        tracker._draw_fovs = MagicMock()
        tracker._draw_body = MagicMock()
        tracker._draw_head_bbox = MagicMock()
        tracker._update_raw_stream_windows = MagicMock()
        tracker._aim_and_move = MagicMock()
        tracker._estimate_head_positions = MagicMock(
            return_value=[(150, 120, (130, 110, 170, 130))]
        )

        detector = MagicMock()
        detector.is_ready.return_value = True
        detector.detect.return_value = [
            {"class": "body", "bbox": (120, 100, 60, 120), "confidence": 0.93},
        ]

        with _ConfigSandbox(
            ai_detection_enabled=True,
            show_opencv_windows=False,
            show_opencv_mask=False,
            show_opencv_detection=False,
            detection_roi_enabled=False,
            enable_target_temporal_smoothing=False,
            aim_type="head",
            anti_smoke_enabled=False,
            anti_smoke_enabled_sec=False,
        ):
            with patch("src.utils.ai_detection.get_ai_detector", return_value=detector):
                tracker._track_frame(np.zeros((240, 320, 3), np.uint8))

        tracker._estimate_head_positions.assert_called_once()
        args = tracker._estimate_head_positions.call_args[0]
        self.assertEqual(args[:4], (120, 100, 180, 220))
        self.assertIsNone(
            args[5], "the rasterised AI mask was fed into head refinement"
        )


class TestMetadataClassNames(unittest.TestCase):
    def test_parse_names_metadata_accepts_python_dict_string(self):
        parsed = _parse_names_metadata(
            "{0: 'body', 1: 'head', 2: 'teammate', 3: 'breakable', 4: 'dodge'}"
        )
        self.assertEqual(parsed, METADATA_NAMES)

    def test_parse_names_metadata_accepts_json_and_dict(self):
        self.assertEqual(_parse_names_metadata('{"0": "body", "1": "head"}'), ["body", "head"])
        self.assertEqual(_parse_names_metadata({0: "body", 1: "head"}), ["body", "head"])

    def test_parse_names_metadata_rejects_garbage(self):
        self.assertIsNone(_parse_names_metadata(None))
        self.assertIsNone(_parse_names_metadata(""))
        self.assertIsNone(_parse_names_metadata("not a mapping"))

    def test_class_names_are_read_from_model_metadata(self):
        det = _bare_detector(["enemy", "head"])
        det.metadata_names = None
        det.session = MagicMock()
        det.session.get_modelmeta.return_value.custom_metadata_map = {
            "names": "{0: 'body', 1: 'head', 2: 'teammate', 3: 'breakable', 4: 'dodge'}"
        }

        det._load_class_names()

        self.assertEqual(det.class_names, METADATA_NAMES)
        self.assertEqual(det.metadata_names, METADATA_NAMES)

    def test_missing_metadata_keeps_default_names(self):
        det = _bare_detector(["enemy", "head"])
        det.metadata_names = None
        det.session = MagicMock()
        det.session.get_modelmeta.return_value.custom_metadata_map = {}

        det._load_class_names()

        self.assertEqual(det.class_names, ["enemy", "head"])

    def test_is_target_class_filters_metadata_classes(self):
        det = _bare_detector(METADATA_NAMES)
        for name in ("body", "head", "enemy", "player"):
            self.assertIn(name, TARGET_CLASS_NAMES)
            self.assertTrue(det.is_target_class(name))
        for name in ("teammate", "breakable", "dodge", "item", "flash"):
            self.assertFalse(det.is_target_class(name))

    def test_unnamed_class_ids_never_become_targets(self):
        """A 5-class model whose metadata is missing must not aim at ids 2-4.

        Falling back to defaults keeps two names, so ids 2/3/4 have no name.
        Mapping them to ``"player"`` (the old behaviour) put ``teammate``,
        ``breakable`` and ``dodge`` inside the allow-list -- the exact leak the
        allow-list exists to prevent.
        """
        det = _bare_detector(["enemy", "head"])
        self.assertIsNone(det._class_name_for_id(2))
        self.assertIsNone(det._class_name_for_id(4))
        self.assertFalse(det.is_target_class(det._class_name_for_id(2)))

        out = _yolo_output([
            (200.0, 200.0, 40.0, 80.0, [0.90, 0.02, 0.01, 0.01, 0.01]),  # enemy
            (200.0, 200.0, 40.0, 80.0, [0.01, 0.02, 0.95, 0.01, 0.01]),  # teammate
            (400.0, 200.0, 40.0, 40.0, [0.01, 0.01, 0.01, 0.93, 0.01]),  # breakable
            (500.0, 200.0, 40.0, 40.0, [0.01, 0.01, 0.01, 0.01, 0.94]),  # dodge
        ])
        classes = [d["class"] for d in det._postprocess(out, 1.0, 0.0, 0.0, 0, 0, 640, 640)]
        self.assertEqual(classes, ["enemy"])


class TestPostprocessClassFiltering(unittest.TestCase):
    def test_postprocess_drops_teammate_breakable_and_dodge(self):
        det = _bare_detector(METADATA_NAMES)
        # 5 classes: body, head, teammate, breakable, dodge
        out = _yolo_output([
            (100.0, 100.0, 40.0, 80.0, [0.90, 0.02, 0.01, 0.01, 0.01]),  # body
            (300.0, 120.0, 20.0, 20.0, [0.01, 0.88, 0.02, 0.01, 0.01]),  # head
            (500.0, 300.0, 40.0, 80.0, [0.01, 0.01, 0.95, 0.01, 0.01]),  # teammate
            (120.0, 400.0, 30.0, 30.0, [0.01, 0.01, 0.02, 0.93, 0.01]),  # breakable
            (560.0, 60.0, 24.0, 24.0, [0.01, 0.01, 0.01, 0.02, 0.94]),   # dodge
        ])

        detections = det._postprocess(out, 1.0, 0.0, 0.0, 0, 0, 640, 640)

        classes = sorted(d["class"] for d in detections)
        self.assertEqual(classes, ["body", "head"])

    def test_filtered_class_does_not_suppress_a_real_target(self):
        """NMS runs after filtering, so a teammate box cannot eat the body box."""
        det = _bare_detector(METADATA_NAMES)
        # Identical boxes: teammate (higher score) overlaps a body target.
        out = _yolo_output([
            (200.0, 200.0, 60.0, 120.0, [0.01, 0.01, 0.99, 0.01, 0.01]),  # teammate
            (200.0, 200.0, 60.0, 120.0, [0.85, 0.01, 0.01, 0.01, 0.01]),  # body
        ])

        detections = det._postprocess(out, 1.0, 0.0, 0.0, 0, 0, 640, 640)

        self.assertEqual([d["class"] for d in detections], ["body"])

    def test_head_box_inside_its_body_box_survives_nms(self):
        """NMS must not let the body box swallow the dedicated head box.

        A head box sits inside its body box, so class-agnostic NMS drops it as
        soon as IoU >= ``ai_iou_threshold``. The pipeline then silently falls
        back to the 22 % estimate, i.e. the head class is never used.
        """
        det = _bare_detector(METADATA_NAMES)
        det.iou_threshold = 0.30
        # Head (60x70) fully inside body (80x160): IoU = 4200/12800 = 0.33,
        # above the threshold, so a class-agnostic NMS keeps only the body.
        # The second body dups the first (IoU 1.0) to prove intra-class NMS
        # still runs.
        out = _yolo_output([
            (200.0, 200.0, 80.0, 160.0, [0.92, 0.01, 0.01, 0.01, 0.01]),  # body
            (200.0, 160.0, 60.0, 70.0, [0.01, 0.87, 0.01, 0.01, 0.01]),   # head
            (200.0, 200.0, 80.0, 160.0, [0.80, 0.01, 0.01, 0.01, 0.01]),  # body dup
        ])

        detections = det._postprocess(out, 1.0, 0.0, 0.0, 0, 0, 640, 640)

        classes = sorted(d["class"] for d in detections)
        self.assertEqual(classes, ["body", "head"], "per-class NMS kept one body and the head")
        body = [d for d in detections if d["class"] == "body"]
        self.assertEqual(len(body), 1, "duplicate body boxes survived intra-class NMS")
        self.assertGreaterEqual(body[0]["confidence"], 0.90, "the weaker duplicate won")

    def test_unknown_classes_are_never_targets(self):
        det = _bare_detector(METADATA_NAMES)
        self.assertFalse(det.is_target_class("some_other_label"))
        # Allow-list: a renamed export drops unknown labels rather than
        # inventing targets out of them.
        foreign = _bare_detector(["ct", "torso"])
        foreign.metadata_names = ["ct", "torso"]
        self.assertFalse(foreign.is_target_class("ct"))


class TestSingletonReload(unittest.TestCase):
    def setUp(self):
        import src.utils.ai_detection as ai

        self.ai = ai
        self.keys = ("ai_model_path", "ai_device", "ai_confidence_threshold", "ai_iou_threshold")
        self.previous = {key: getattr(config, key, "__missing__") for key in self.keys}
        self.old_instance = ai._AI_DETECTOR_INSTANCE
        self.old_signature = ai._AI_DETECTOR_SIGNATURE

    def tearDown(self):
        ai = self.ai
        ai._AI_DETECTOR_INSTANCE = self.old_instance
        ai._AI_DETECTOR_SIGNATURE = self.old_signature
        for key, value in self.previous.items():
            if value == "__missing__":
                try:
                    delattr(config, key)
                except AttributeError:
                    pass
            else:
                setattr(config, key, value)

    def test_detector_is_reused_while_the_session_config_is_unchanged(self):
        ai = self.ai
        with patch.object(ai, "AIDetector", side_effect=lambda **kw: MagicMock()) as ctor:
            ai._AI_DETECTOR_INSTANCE = None
            ai._AI_DETECTOR_SIGNATURE = None

            first = get_ai_detector()
            same = get_ai_detector()
            self.assertIs(first, same, "unchanged config rebuilt the detector")
            self.assertEqual(ctor.call_count, 1)

    def test_model_path_or_device_change_rebuilds_the_session(self):
        ai = self.ai
        with patch.object(ai, "AIDetector", side_effect=lambda **kw: MagicMock()) as ctor:
            ai._AI_DETECTOR_INSTANCE = None
            ai._AI_DETECTOR_SIGNATURE = None

            first = get_ai_detector()
            config.ai_device = "cpu" if str(config.ai_device).lower() != "cpu" else "dml"
            reloaded = get_ai_detector()
            self.assertIsNot(reloaded, first)
            self.assertEqual(ctor.call_count, 2)

            config.ai_model_path = "models/another.onnx"
            get_ai_detector()
            self.assertEqual(ctor.call_count, 3)

    def test_threshold_change_reuses_the_session(self):
        """Conf/iou are post-processing values: they must not reload 36 MB."""
        ai = self.ai
        with patch.object(ai, "AIDetector", side_effect=lambda **kw: MagicMock()) as ctor:
            ai._AI_DETECTOR_INSTANCE = None
            ai._AI_DETECTOR_SIGNATURE = None

            first = get_ai_detector()
            config.ai_confidence_threshold = float(config.ai_confidence_threshold) + 0.10
            config.ai_iou_threshold = float(config.ai_iou_threshold) - 0.10
            same = get_ai_detector()

            self.assertIs(same, first, "a threshold change rebuilt the InferenceSession")
            self.assertEqual(ctor.call_count, 1)
            self.assertAlmostEqual(same.conf_threshold, float(config.ai_confidence_threshold))
            self.assertAlmostEqual(same.iou_threshold, float(config.ai_iou_threshold))

    def test_concurrent_rebuilds_never_create_two_sessions(self):
        """The UI reload and the track thread must not both build 36 MB sessions.

        ``get_ai_detector`` is called on every tracked frame and from the UI
        (model/device change, "Reload model"). Unsynchronised, two threads could
        each construct an ``InferenceSession`` during the ~1.7 s load, doubling
        peak memory on a 3 GB GPU.
        """
        ai = self.ai
        build_started = threading.Event()
        release_build = threading.Event()
        builds = []

        def slow_ctor(**kwargs):
            builds.append(kwargs)
            build_started.set()
            release_build.wait(2.0)
            return MagicMock()

        with patch.object(ai, "AIDetector", side_effect=slow_ctor):
            ai._AI_DETECTOR_INSTANCE = None
            ai._AI_DETECTOR_SIGNATURE = None

            results = {}

            def call(name):
                results[name] = get_ai_detector()

            first = threading.Thread(target=call, args=("first",), daemon=True)
            first.start()
            self.assertTrue(build_started.wait(2.0), "the first build never started")

            second = threading.Thread(target=call, args=("second",), daemon=True)
            second.start()
            # The second caller must not start a build of its own either way.
            second.join(timeout=0.20)

            release_build.set()
            first.join(timeout=2.0)
            second.join(timeout=2.0)

        self.assertEqual(len(builds), 1, f"built {len(builds)} sessions for one config")
        self.assertIs(results["first"], results["second"])

    def test_tracking_thread_does_not_stall_behind_a_reload(self):
        """A frame must never wait ~1.7 s for the UI's model reload.

        While the UI rebuilds, the previous detector is still valid; the track
        path returns it immediately instead of blocking the frame loop.
        """
        ai = self.ai
        build_started = threading.Event()
        release_build = threading.Event()
        stale = MagicMock()

        def slow_ctor(**kwargs):
            build_started.set()
            release_build.wait(2.0)
            return MagicMock()

        ai._AI_DETECTOR_INSTANCE = stale
        ai._AI_DETECTOR_SIGNATURE = ai._session_signature()

        with patch.object(ai, "AIDetector", side_effect=slow_ctor):
            reload_thread = threading.Thread(
                target=lambda: get_ai_detector(force_reload=True), daemon=True
            )
            reload_thread.start()
            self.assertTrue(build_started.wait(2.0), "the reload never started")

            # The track path returns at once with the still-valid instance.
            self.assertIs(get_ai_detector(), stale)

            release_build.set()
            reload_thread.join(timeout=2.0)


class TestHeadAndBodyTargetSelection(unittest.TestCase):
    """``head`` boxes must be used as-is, never re-estimated from the body."""

    def setUp(self):
        from main import build_aim_targets

        self.build = build_aim_targets
        self.estimate = MagicMock(return_value=[(999, 999, (0, 0, 1, 1))])

    def _detections(self):
        return [
            {"class": "body", "bbox": (100, 100, 40, 100), "confidence": 0.93},
            {"class": "head", "bbox": (105, 100, 20, 20), "confidence": 0.87},
        ]

    def test_head_mode_aims_at_the_head_bbox_centre_only(self):
        targets, bboxes, _bodies, heads, rects = self.build(
            self._detections(), "head", 640, 480, 100,
            estimate_head_positions=self.estimate,
        )

        self.estimate.assert_not_called()
        self.assertEqual(len(targets), 1, "a body target duplicated the head target")
        cx, cy = targets[0][0], targets[0][1]
        self.assertAlmostEqual(cx, 115.0)
        self.assertAlmostEqual(cy, 110.0)
        self.assertEqual(heads, [(115, 110)])
        self.assertEqual(rects, [(105, 100, 125, 120)])
        self.assertEqual(len(bboxes), 1)

    def test_body_mode_prefers_the_body_bbox(self):
        targets, _bboxes, bodies, heads, _rects = self.build(
            self._detections(), "body", 640, 480, 100,
            estimate_head_positions=self.estimate,
        )

        self.estimate.assert_not_called()
        self.assertEqual(len(targets), 1)
        self.assertAlmostEqual(targets[0][0], 120.0)
        self.assertAlmostEqual(targets[0][1], 150.0)
        self.assertEqual(heads, [])
        self.assertEqual(len(bodies), 1)

    def test_head_box_stacked_on_top_of_the_body_is_paired_not_duplicated(self):
        """A torso-only ``body`` export puts the head box *above* the body box.

        ``_head_centre_inside`` (the previous pairing rule) only accepted a head
        whose centre fell inside the body, or 15 % around it. When ``body`` means
        the torso, the head sits on top: the centre is outside, so the head
        became a standalone target *and* the body fell through to the 22 %
        estimate -- two targets for one player, the wrong one sometimes nearer
        the crosshair.
        """
        detections = [
            # Torso only: the head is drawn above it, not inside it.
            {"class": "body", "bbox": (100, 120, 40, 100), "confidence": 0.93},
            {"class": "head", "bbox": (108, 96, 24, 24), "confidence": 0.87},
        ]

        for aim_type in ("head", "nearest"):
            self.estimate.reset_mock()
            targets, _bboxes, _bodies, heads, _rects = self.build(
                detections, aim_type, 640, 480, 100,
                estimate_head_positions=self.estimate,
            )

            self.estimate.assert_not_called()
            self.assertEqual(len(targets), 1, f"{aim_type}: one player got two targets")
            self.assertAlmostEqual(targets[0][0], 120.0)
            self.assertAlmostEqual(targets[0][1], 108.0)
            self.assertEqual(heads, [(120, 108)])

    def test_head_from_a_different_player_is_still_standalone(self):
        """Pairing must stay spatial: a far-away head does not belong to a body."""
        detections = [
            {"class": "body", "bbox": (100, 120, 40, 100), "confidence": 0.93},
            {"class": "head", "bbox": (420, 100, 24, 24), "confidence": 0.87},
        ]

        targets, _bboxes, _bodies, heads, _rects = self.build(
            detections, "head", 640, 480, 100,
            estimate_head_positions=self.estimate,
        )

        # The body has no head of its own -> estimated; the far head stands alone.
        self.estimate.assert_called_once_with(100, 120, 140, 220)
        self.assertEqual(len(targets), 2)
        self.assertIn((432, 112), heads, "the unrelated head was attached to the body")

    def test_two_players_each_keep_their_own_stacked_head(self):
        detections = [
            {"class": "body", "bbox": (100, 120, 40, 100), "confidence": 0.93},
            {"class": "head", "bbox": (108, 96, 24, 24), "confidence": 0.87},
            {"class": "body", "bbox": (400, 120, 40, 100), "confidence": 0.91},
            {"class": "head", "bbox": (410, 98, 22, 22), "confidence": 0.85},
        ]

        targets, _bboxes, _bodies, heads, _rects = self.build(
            detections, "head", 640, 480, 100,
            estimate_head_positions=self.estimate,
        )

        self.estimate.assert_not_called()
        self.assertEqual(len(targets), 2, "a player was counted twice or dropped")
        self.assertIn((120, 108), heads)
        self.assertIn((421, 109), heads)

    def test_body_only_detections_fall_back_to_head_estimation(self):
        detections = [{"class": "body", "bbox": (100, 100, 40, 100), "confidence": 0.93}]

        targets, _bboxes, _bodies, _heads, _rects = self.build(
            detections, "head", 640, 480, 100,
            estimate_head_positions=self.estimate,
        )

        self.estimate.assert_called_once_with(100, 100, 140, 200)
        self.assertEqual(len(targets), 1)
        self.assertAlmostEqual(targets[0][0], 999)
        self.assertAlmostEqual(targets[0][1], 999)

    def test_mixed_players_estimate_only_the_body_without_a_head_box(self):
        detections = [
            {"class": "body", "bbox": (100, 100, 40, 100), "confidence": 0.93},
            {"class": "head", "bbox": (105, 100, 20, 20), "confidence": 0.87},
            {"class": "body", "bbox": (400, 100, 40, 100), "confidence": 0.90},
        ]

        targets, bboxes, _bodies, heads, _rects = self.build(
            detections, "head", 640, 480, 100,
            estimate_head_positions=self.estimate,
        )

        # The estimator ran for the headless body only, never for the paired one.
        self.estimate.assert_called_once_with(400, 100, 440, 200)
        self.assertEqual(len(targets), 2)
        self.assertIn((115, 110), heads)
        self.assertEqual(len(bboxes), 2)

    def test_nearest_mode_keeps_head_and_body_y_bounds(self):
        targets, _bboxes, _bodies, _heads, _rects = self.build(
            self._detections(), "nearest", 640, 480, 100,
            estimate_head_positions=self.estimate,
        )

        self.assertEqual(len(targets), 1)
        _cx, _cy, _d, head_y_min, body_y_max = targets[0]
        self.assertEqual(head_y_min, 100)   # the head box's own top edge
        self.assertEqual(body_y_max, 200)   # the body box's bottom edge

    def test_overlapping_body_box_does_not_duplicate_a_paired_head(self):
        detections = [
            {"class": "body", "bbox": (100, 100, 40, 100), "confidence": 0.93},
            {"class": "body", "bbox": (98, 98, 46, 106), "confidence": 0.71},
            {"class": "head", "bbox": (105, 100, 20, 20), "confidence": 0.87},
        ]

        targets, _bboxes, _bodies, _heads, _rects = self.build(
            detections, "head", 640, 480, 100,
            estimate_head_positions=self.estimate,
        )

        self.estimate.assert_not_called()
        self.assertEqual(len(targets), 1, "the second body box produced a duplicate target")

    def test_small_far_head_survives_the_body_area_floor(self):
        """A 5x5 head (25 px²) is a real target; a 5x5 body is noise.

        ``min_bbox_area`` is tuned to reject body-sized blobs. Applying it to
        ``head`` before reading the class deleted every distant head, so the
        head class now has its own, much lower floor.
        """
        detections = [
            {"class": "head", "bbox": (100, 100, 5, 5), "confidence": 0.55},
            {"class": "body", "bbox": (10, 10, 5, 5), "confidence": 0.41},
        ]

        targets, bboxes, bodies, heads, rects = self.build(
            detections, "head", 640, 480, 100,
            estimate_head_positions=self.estimate,
        )

        self.estimate.assert_not_called()
        self.assertEqual(bodies, [], "a 5x5 body noise box survived the body floor")
        self.assertEqual(len(targets), 1, "the small far head was dropped")
        self.assertAlmostEqual(targets[0][0], 102.5)
        self.assertAlmostEqual(targets[0][1], 102.5)
        self.assertEqual(heads, [(102, 102)])
        self.assertEqual(rects, [(100, 100, 105, 105)])
        self.assertEqual(len(bboxes), 1)

    def test_head_floor_never_exceeds_the_caller_floor(self):
        """With ``min_bbox_area=1`` (real-model path) behaviour is unchanged."""
        detections = [{"class": "head", "bbox": (100, 100, 1, 1), "confidence": 0.5}]

        targets, _bboxes, _bodies, heads, _rects = self.build(
            detections, "head", 640, 480, 1,
            estimate_head_positions=self.estimate,
        )

        self.assertEqual(len(targets), 1)
        self.assertEqual(len(heads), 1)

    def test_non_target_classes_never_become_targets(self):
        detections = [
            {"class": "teammate", "bbox": (10, 10, 40, 100), "confidence": 0.99},
            {"class": "breakable", "bbox": (200, 10, 40, 40), "confidence": 0.99},
            {"class": "dodge", "bbox": (300, 10, 40, 40), "confidence": 0.99},
        ]

        for aim_type in ("head", "body", "nearest"):
            targets, _bboxes, _bodies, _heads, _rects = self.build(
                detections, aim_type, 640, 480, 100,
                estimate_head_positions=self.estimate,
            )
            self.assertEqual(targets, [], f"{aim_type} mode targeted a non-enemy")


class TestRealModelInference(unittest.TestCase):
    """Load the shipped model and run one real inference pass.

    The model is a per-machine artifact (``models/*.onnx`` is git-ignored), but
    it is part of this task's deliverable, so its absence is a failure -- not a
    skip. Only the external reference screenshot is optional.

    ``CVM_SKIP_MODEL_TEST=1`` is the documented opt-out for a clean clone that
    has no model yet: it skips *both* real-model tests and says so, because a
    skip is not evidence of anything (the Tester log will show ``skipped``).
    """

    SKIP_MODEL = os.environ.get("CVM_SKIP_MODEL_TEST", "") == "1"
    SKIP_REASON = (
        "CVM_SKIP_MODEL_TEST=1: models/*.onnx is git-ignored, so this is a skip, not a pass"
    )

    @unittest.skipIf(SKIP_MODEL, SKIP_REASON)
    def test_valorant_model_declares_teammate_class(self):
        """The 5-class Valo export can name a team-mate natively."""
        self.assertTrue(os.path.isfile(MODEL_PATH), f"packaged model missing: {MODEL_PATH}")
        det = AIDetector(model_path=MODEL_PATH, device="cpu")
        self.assertTrue(det.is_ready(), "valorant_detector.onnx failed to load")
        self.assertTrue(det.supports_teammate_class(), det.class_names)
        self.assertIn("teammate", [str(n).lower() for n in det.class_names])
        self.assertIn("Native 'teammate' class", det.teammate_capability_summary())

    @unittest.skipIf(SKIP_MODEL, SKIP_REASON)
    def test_my_yolo_model_lacks_teammate_class(self):
        """The converted 4-class model is player-only: the outline guard is required."""
        my_model = os.path.join(os.path.dirname(MODEL_PATH), "my_yolo_model.onnx")
        self.assertTrue(os.path.isfile(my_model), f"converted model missing: {my_model}")
        det = AIDetector(model_path=my_model, device="cpu")
        self.assertTrue(det.is_ready(), "my_yolo_model.onnx failed to load")
        self.assertEqual([n.lower() for n in det.class_names], ["head", "body", "body", "body"])
        self.assertFalse(det.supports_teammate_class())
        summary = det.teammate_capability_summary()
        self.assertIn("Player-only", summary)
        self.assertIn("Enemy Outline Guard required", summary)

    @unittest.skipIf(SKIP_MODEL, SKIP_REASON)
    def test_packaged_model_loads_and_runs(self):
        self.assertTrue(
            os.path.isfile(MODEL_PATH),
            f"models/valorant_detector.onnx is a required deliverable: {MODEL_PATH}",
        )

        det = AIDetector(model_path=MODEL_PATH, device="cpu")
        self.assertTrue(det.is_ready(), "the packaged ONNX model failed to load")
        self.assertEqual(det.input_size, (320, 320), "expected the 320px YOLO11s export")
        self.assertIsNotNone(det.metadata_names, "class names were not read from metadata")
        self.assertEqual([n.lower() for n in det.class_names], METADATA_NAMES)

        img = np.zeros((480, 640, 3), np.uint8)
        detections = det.detect(img)

        self.assertIsInstance(detections, list)
        for item in detections:
            self.assertIn(item["class"], TARGET_CLASS_NAMES)

    @unittest.skipIf(SKIP_MODEL, SKIP_REASON)
    def test_inference_on_reference_screenshot(self):
        if not os.path.isfile(REFERENCE_IMAGE):
            self.skipTest(f"reference screenshot missing: {REFERENCE_IMAGE}")
        self.assertTrue(os.path.isfile(MODEL_PATH), f"packaged model missing: {MODEL_PATH}")

        img = cv2.imread(REFERENCE_IMAGE)
        self.assertIsNotNone(img, "reference screenshot could not be decoded")

        det = AIDetector(model_path=MODEL_PATH, device="cpu", conf_threshold=0.25)
        detections = det.detect(img)

        self.assertTrue(detections, "no detection on the reference screenshot")
        for item in detections:
            self.assertIn(item["class"], TARGET_CLASS_NAMES)
            x, y, w, h = item["bbox"]
            self.assertGreater(w, 0)
            self.assertGreater(h, 0)
            self.assertGreaterEqual(x, 0)
            self.assertGreaterEqual(y, 0)
            self.assertLessEqual(x + w, img.shape[1])
            self.assertLessEqual(y + h, img.shape[0])

        classes = {item["class"] for item in detections}
        self.assertIn("body", classes, f"the player body was not detected: {classes}")
        self.assertIn("head", classes, f"the head box was lost: {classes}")

        # The real detections must survive the whole target-selection path: each
        # head box is aimed at as-is, at its own centre, instead of falling back
        # to the 22 % estimate inside the body.
        import main as main_module

        targets, _bboxes, _bodies, heads, _rects = main_module.build_aim_targets(
            detections, "head", img.shape[1], img.shape[0], 1,
        )
        self.assertTrue(targets, "the real detections produced no aim target")
        self.assertTrue(heads, "the head detections produced no head overlay")
        head_centres = {
            (int(round(x + w / 2.0)), int(round(y + h / 2.0)))
            for x, y, w, h in (
                d["bbox"] for d in detections if d["class"] == "head"
            )
        }
        self.assertTrue(
            head_centres.issubset(set(heads)),
            f"head targets not placed at their box centres: {head_centres - set(heads)}",
        )

    @unittest.skipIf(SKIP_MODEL, SKIP_REASON)
    def test_my_yolo_model_loads_and_detects(self):
        my_model = os.path.join(os.path.dirname(MODEL_PATH), "my_yolo_model.onnx")
        self.assertTrue(os.path.isfile(my_model), f"converted model missing: {my_model}")
        det = AIDetector(model_path=my_model, device="cpu", conf_threshold=0.25)
        self.assertTrue(det.is_ready(), "my_yolo_model.onnx failed to load")
        self.assertEqual(det.input_size, (320, 320))
        self.assertEqual([n.lower() for n in det.class_names], ["head", "body", "body", "body"])
        if os.path.isfile(REFERENCE_IMAGE):
            img = cv2.imread(REFERENCE_IMAGE)
            self.assertIsNotNone(img)
            detections = det.detect(img)
            classes = {d["class"] for d in detections}
            self.assertIn("body", classes)
            self.assertIn("head", classes)


class TestAIDetectorResilience(unittest.TestCase):
    def test_resolve_model_path_falls_back_to_repo_root(self):
        from src.utils.ai_detection import resolve_model_path

        orig_cwd = os.getcwd()
        parent = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        try:
            os.chdir(parent)
            resolved = resolve_model_path("models/valorant_detector.onnx")
            self.assertTrue(os.path.isabs(resolved))
            self.assertTrue(os.path.isfile(resolved))
        finally:
            os.chdir(orig_cwd)

    def test_name_grouped_nms_deduplicates_merged_body_classes(self):
        det = _bare_detector(["head", "body", "body", "body"])
        out = _yolo_output([
            (200.0, 200.0, 60.0, 120.0, [0.01, 0.90, 0.01, 0.01]),  # body (id 1)
            (200.0, 200.0, 60.0, 120.0, [0.01, 0.01, 0.01, 0.75]),  # body (id 3)
            (200.0, 155.0, 20.0, 20.0, [0.85, 0.01, 0.01, 0.01]),   # head (id 0)
        ])
        detections = det._postprocess(out, 1.0, 0.0, 0.0, 0, 0, 640, 640)
        self.assertEqual(len([d for d in detections if d["class"] == "body"]), 1)
        self.assertEqual(len([d for d in detections if d["class"] == "head"]), 1)

    def test_dml_runtime_error_falls_back_to_cpu_session(self):
        det = _bare_detector(["body", "head"])
        det.model_path = MODEL_PATH
        det.device = "dml"
        det.active_provider = "DmlExecutionProvider"
        det._dml_fallback_done = False
        det.input_size = (320, 320)
        det.input_dtype = np.float32
        det.input_name = "images"
        det.is_loaded = True
        det.session = MagicMock()
        det.session.run.side_effect = RuntimeError("DirectML execution failed")

        fallback_session = MagicMock()
        fallback_session.get_providers.return_value = ["CPUExecutionProvider"]
        fallback_session.run.return_value = [_yolo_output([(160.0, 160.0, 40.0, 80.0, [0.91, 0.01])])]

        import src.utils.ai_detection as ai_mod
        with patch.object(ai_mod.ort, "InferenceSession", return_value=fallback_session):
            detections = det.detect(np.zeros((320, 320, 3), np.uint8))

        self.assertEqual(det.active_provider, "CPUExecutionProvider")
        self.assertEqual(len(detections), 1)
        self.assertEqual(detections[0]["class"], "body")

    def test_track_frame_skips_roi_crop_in_ai_mode(self):
        import main as main_module
        from src.utils.detection import DetectionFrame

        tracker = main_module.AimTracker.__new__(main_module.AimTracker)
        tracker.app = MagicMock()
        tracker.app.capture.apply_mode_fov.side_effect = lambda img: img
        tracker.app.capture.get_frame_meta.return_value = {}
        tracker._frame_count = 0
        tracker._last_frame_log_time = 0.0
        tracker._last_frame_seq = 1
        tracker._last_engine_toggle_key_state = False
        tracker.model = None
        tracker._compute_detection_roi = MagicMock(return_value=(100, 100, 200, 200))
        tracker._aim_and_move = MagicMock()
        tracker.perf = {}

        with _ConfigSandbox(ai_detection_enabled=True, detection_roi_enabled=True, show_opencv_windows=False):
            with patch.object(main_module, "analyze", return_value=DetectionFrame([], None, None, None, False, 0, (320, 320, 3))) as mock_an:
                tracker._track_frame(np.zeros((320, 320, 3), np.uint8))

        tracker._compute_detection_roi.assert_not_called()
        self.assertIsNone(mock_an.call_args.kwargs["roi"])
        self.assertEqual(mock_an.call_args.kwargs["engine"], "ai")


class TestObsUdpPluginHelper(unittest.TestCase):
    """OBS xUDP plugin bridge: install state, AI filter preset, crop guard."""

    def _bundle(self, tmpdir, with_installer=True, with_dll=True):
        """Build a fake bundle so the assertions never depend on this machine."""
        obs_dir = os.path.join(tmpdir, "obs-plugins", "64bit")
        bin_dir = os.path.join(tmpdir, "bin", "64bit")
        os.makedirs(obs_dir, exist_ok=True)
        os.makedirs(bin_dir, exist_ok=True)
        if with_dll:
            for path in (
                os.path.join(obs_dir, "obs-color-correction.dll"),
                os.path.join(bin_dir, "turbojpeg.dll"),
            ):
                with open(path, "wb") as handle:
                    handle.write(b"stub")
        if with_installer:
            for name in ("install.ps1", "install.bat"):
                with open(os.path.join(tmpdir, name), "w", encoding="utf-8") as handle:
                    handle.write("exit 0")
        return tmpdir

    def test_plugin_status_reports_installed_and_missing(self):
        from src.utils.obs_udp_plugin import check_plugin_status

        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_root = self._bundle(os.path.join(tmpdir, "bundle"))
            installed_obs = os.path.join(tmpdir, "obs-installed")
            installed_turbo = os.path.join(tmpdir, "turbo-installed")
            os.makedirs(os.path.join(installed_obs, "obs-plugins", "64bit"))
            os.makedirs(os.path.join(installed_obs, "bin", "64bit"))
            os.makedirs(installed_turbo)
            for path in (
                os.path.join(installed_obs, "obs-plugins", "64bit", "obs-color-correction.dll"),
                os.path.join(installed_obs, "bin", "64bit", "turbojpeg.dll"),
                os.path.join(installed_turbo, "turbojpeg.dll"),
            ):
                open(path, "wb").close()

            status = check_plugin_status(plugin_root, installed_obs, installed_turbo)
            self.assertTrue(status["installed"])
            self.assertTrue(status["bundle_available"])
            self.assertEqual(status["installer"], "install.ps1")
            self.assertEqual(status["missing"], [])

            empty_obs = os.path.join(tmpdir, "obs-empty")
            empty_turbo = os.path.join(tmpdir, "turbo-empty")
            os.makedirs(empty_obs)
            os.makedirs(empty_turbo)
            broken = check_plugin_status(plugin_root, empty_obs, empty_turbo)
            self.assertFalse(broken["installed"])
            self.assertFalse(broken["obs_dll"])
            self.assertFalse(broken["obs_turbojpeg"])
            self.assertFalse(broken["turbo_lib_dll"])
            self.assertGreaterEqual(len(broken["missing"]), 3)
            self.assertTrue(broken["bundle_available"], "bundle files must still be usable")

    def test_plugin_bundle_paths_match_shipped_layout(self):
        from src.utils.obs_udp_plugin import (
            PLUGIN_BUNDLE_DIRNAME,
            build_install_command,
            resolve_plugin_root,
        )

        root = resolve_plugin_root()
        self.assertTrue(root.endswith(PLUGIN_BUNDLE_DIRNAME))
        self.assertTrue(os.path.isdir(root), f"shipped bundle missing: {root}")
        command = build_install_command(root)
        self.assertIsNotNone(command)
        self.assertIn("install.ps1", " ".join(command))
        elevated = build_install_command(root, elevated=True)
        self.assertIn("RunAs", " ".join(elevated))

    def test_installer_dry_run_never_executes(self):
        from src.utils.obs_udp_plugin import run_plugin_installer

        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_root = self._bundle(tmpdir)
            ok, text = run_plugin_installer(plugin_root, dry_run=True)
            self.assertTrue(ok)
            self.assertIn("install.ps1", text)

    def test_preset_320_for_valorant_and_my_yolo(self):
        from src.utils.obs_udp_plugin import build_ai_obs_filter_preset

        for model in ("models/valorant_detector.onnx", "models/my_yolo_model.onnx",
                      r"models\my_yolo_model.onnx"):
            preset = build_ai_obs_filter_preset(model)
            self.assertEqual((preset["width"], preset["height"]), (320, 320), model)
            self.assertEqual(preset["fps"], 144)
            self.assertTrue(80 <= preset["jpeg_quality"] <= 85)

    def test_preset_640_for_my_yolo_640(self):
        from src.utils.obs_udp_plugin import build_ai_obs_filter_preset

        preset = build_ai_obs_filter_preset("models/my_yolo_model_640.onnx")
        self.assertEqual((preset["width"], preset["height"]), (640, 640))

    def test_preset_disables_colorbot_colour_chain(self):
        """The HSV chain (purple boost / contrast crush) must be inverted for AI."""
        from src.utils.obs_udp_plugin import build_ai_obs_filter_preset

        preset = build_ai_obs_filter_preset("models/my_yolo_model.onnx")
        self.assertFalse(preset["color_enhancement"])
        self.assertFalse(preset["adaptive_enhancement"])
        self.assertFalse(preset["reduce_background_colors"])
        self.assertFalse(preset["shadow_rejection"])
        self.assertEqual(preset["contrast_crush"], 0.0)
        self.assertFalse(preset["enhance_purple_tones"])
        self.assertFalse(preset["outline_thickening"])
        self.assertEqual(preset["fps"], 144)
        self.assertTrue(80 <= preset["jpeg_quality"] <= 85)

    def test_preset_text_states_the_three_must_be_off(self):
        from src.utils.obs_udp_plugin import (
            build_ai_obs_filter_preset,
            format_ai_obs_filter_preset,
        )

        text = format_ai_obs_filter_preset(build_ai_obs_filter_preset("models/my_yolo_model.onnx"))
        for needle in (
            "Color Enhancement: OFF",
            "Adaptive Enhancement: OFF",
            "Reduce Background Colors: OFF",
            "Shadow Rejection: OFF",
            "Contrast Crush: 0.00",
        ):
            self.assertIn(needle, text)
        self.assertIn("320x320", text)
        self.assertIn("144", text)

    def test_preset_text_requires_crop_pad_before_color_correction(self):
        """PC1 must Crop/Pad 1:1 *before* Colour Correction, not shrink the canvas.

        ``obs-color-correction.dll`` is prebuilt and only changes colours. The
        scene is 1920x1080, so dropping OBS output to 320x320 would resample the
        whole picture and blur a distant head into nothing; the fix is a 1:1
        crop around the crosshair, applied above the colour filter.
        """
        from src.utils.obs_udp_plugin import (
            build_ai_obs_filter_preset,
            format_ai_obs_filter_preset,
        )

        preset = build_ai_obs_filter_preset(
            "models/valorant_detector.onnx", target_ip="192.168.1.50",
        )
        self.assertEqual((preset["width"], preset["height"]), (320, 320))

        text = format_ai_obs_filter_preset(preset)

        for needle in ("PC1", "Crop/Pad", "1:1", "320x320", "800", "380"):
            self.assertIn(needle, text)
        self.assertIn("1920x1080", text)
        self.assertLess(
            text.index("Crop/Pad"), text.index("Color Correction"),
            "Crop/Pad must be listed above Color Correction",
        )
        # The warning against shrinking the whole scene must be explicit.
        self.assertIn("Do NOT set the OBS canvas/output", text)

    def test_preset_text_uses_the_640_crop_offsets_for_a_640_model(self):
        from src.utils.obs_udp_plugin import (
            build_ai_obs_filter_preset,
            format_ai_obs_filter_preset,
        )

        preset = build_ai_obs_filter_preset(
            "models/my_yolo_model_640.onnx", target_ip="192.168.1.50",
        )
        text = format_ai_obs_filter_preset(preset)

        self.assertIn("640x640", text)
        self.assertIn("Left 640, Right 640, Top 220, Bottom 220", text)
        self.assertLess(text.index("Crop/Pad"), text.index("Color Correction"))

    def test_colorbot_preset_is_320_at_200_fps_with_purple_chain(self):
        """The shipped default is HSV Colorbot: 320x320 @ 200 FPS, purple chain ON."""
        from src.utils.obs_udp_plugin import build_colorbot_obs_filter_preset

        preset = build_colorbot_obs_filter_preset(target_ip="192.168.1.50")

        self.assertEqual((preset["width"], preset["height"]), (320, 320))
        self.assertEqual(preset["fps"], 200)
        self.assertEqual(preset["jpeg_quality"], 80)
        self.assertTrue(preset["color_enhancement"])
        self.assertFalse(preset["adaptive_enhancement"])
        self.assertTrue(preset["enhance_purple_tones"])
        self.assertTrue(preset["reduce_background_colors"])
        self.assertFalse(preset["shadow_rejection"])
        self.assertTrue(preset["outline_thickening"])
        self.assertAlmostEqual(preset["contrast_crush"], 0.85)
        # A peer IP means no "bind address" warning, unlike the default.
        self.assertFalse(any("bind address" in w for w in preset["warnings"]))

    def test_colorbot_preset_text_puts_crop_pad_before_color_correction(self):
        """PC1 must Crop/Pad 1:1 *above* Color Correction, exactly like the AI preset."""
        from src.utils.obs_udp_plugin import (
            build_colorbot_obs_filter_preset,
            format_colorbot_obs_filter_preset,
        )

        preset = build_colorbot_obs_filter_preset(
            target_ip="192.168.1.50", target_port="5000",
        )
        text = format_colorbot_obs_filter_preset(preset)

        for needle in (
            "COLORBOT",
            "320x320",
            "800",
            "380",
            "Relative = ON",
            "FOV (Crop Size) = 320",
            "Max Network FPS: 200",
            "JPEG Quality: 80",
            "Color Enhancement: ON",
            "Adaptive Enhancement: OFF",
            "Enhance Purple Tones: ON",
            "Reduce Background Colors: ON",
            "Shadow Rejection: OFF",
            "Outline Thickening: ON",
        ):
            self.assertIn(needle, text)
        self.assertIn("144", text, "the 144 FPS fallback note must be spelled out")
        self.assertLess(
            text.index("Crop/Pad"), text.index("Color Correction"),
            "Crop/Pad must be listed above Color Correction",
        )

    def test_unknown_model_falls_back_to_640_with_warning(self):
        from src.utils.obs_udp_plugin import build_ai_obs_filter_preset

        preset = build_ai_obs_filter_preset("models/mystery.onnx")
        self.assertIn(preset["width"], (320, 640))
        self.assertTrue(preset["warnings"])

    def test_preset_input_size_prefers_table_then_detector(self):
        from src.utils.obs_udp_plugin import preset_input_size

        self.assertEqual(preset_input_size("models/valorant_detector.onnx"), (320, "model_table"))
        self.assertEqual(preset_input_size("models/my_yolo_model_640.onnx"), (640, "model_table"))
        self.assertEqual(preset_input_size("models/custom_320.onnx", (416, 416)), (416, "detector_input_size"))

    def test_crop_bypass_when_ai_and_crop_below_model_input(self):
        from src.utils.obs_udp_plugin import should_bypass_udp_crop, udp_crop_decision

        with _ConfigSandbox(
            detection_engine="ai_detection",
            ai_model_path="models/my_yolo_model.onnx",
            udp_fov_enabled=True,
            udp_fov=108,
            ai_udp_bypass_tiny_crop=True,
            ai_udp_min_crop_px=0,
        ):
            state = udp_crop_decision(config)
            self.assertTrue(state["bypass"])
            self.assertEqual(state["reason"], "tiny_crop")
            self.assertEqual(state["total_px"], 216)
            self.assertEqual(state["min_px"], 320)
            # The thin wrapper must agree with the decision it wraps.
            self.assertTrue(should_bypass_udp_crop(config))

    def test_crop_not_bypassed_for_colorbot_engine(self):
        from src.utils.obs_udp_plugin import udp_crop_decision

        with _ConfigSandbox(
            detection_engine="colorbot",
            ai_detection_enabled=False,
            ai_model_path="models/my_yolo_model.onnx",
            udp_fov_enabled=True,
            udp_fov=108,
            ai_udp_bypass_tiny_crop=True,
        ):
            state = udp_crop_decision(config)
            self.assertFalse(state["bypass"])
            self.assertEqual(state["reason"], "engine_colorbot")

    def test_crop_not_bypassed_when_option_off(self):
        from src.utils.obs_udp_plugin import udp_crop_decision

        with _ConfigSandbox(
            detection_engine="ai_detection",
            ai_model_path="models/my_yolo_model.onnx",
            udp_fov_enabled=True,
            udp_fov=108,
            ai_udp_bypass_tiny_crop=False,
        ):
            state = udp_crop_decision(config)
            self.assertFalse(state["bypass"])
            self.assertEqual(state["reason"], "option_off")

    def test_crop_kept_when_large_enough(self):
        from src.utils.obs_udp_plugin import udp_crop_decision

        with _ConfigSandbox(
            detection_engine="ai_detection",
            ai_model_path="models/my_yolo_model.onnx",
            udp_fov_enabled=True,
            udp_fov=320,
            ai_udp_bypass_tiny_crop=True,
        ):
            state = udp_crop_decision(config)
            self.assertFalse(state["bypass"])
            self.assertEqual(state["reason"], "crop_ok")

    def test_capture_apply_mode_fov_bypasses_tiny_crop_for_ai(self):
        from src.capture.capture_service import CaptureService

        service = CaptureService()
        service.mode = "UDP"
        frame = np.zeros((1080, 1920, 3), np.uint8)
        with _ConfigSandbox(
            detection_engine="ai_detection",
            ai_model_path="models/my_yolo_model.onnx",
            udp_fov_enabled=True,
            udp_fov=108,
            ai_udp_bypass_tiny_crop=True,
        ):
            out = service.apply_mode_fov(frame)
            self.assertEqual(out.shape[:2], (1080, 1920), "AI mode lost the full frame")
            state = service.get_udp_crop_state()
            self.assertIsInstance(state, dict)
            self.assertEqual(state.get("reason"), "tiny_crop")

    def test_capture_apply_mode_fov_still_crops_for_colorbot(self):
        from src.capture.capture_service import CaptureService

        service = CaptureService()
        service.mode = "UDP"
        frame = np.zeros((1080, 1920, 3), np.uint8)
        with _ConfigSandbox(
            detection_engine="colorbot",
            ai_detection_enabled=False,
            ai_model_path="models/my_yolo_model.onnx",
            udp_fov_enabled=True,
            udp_fov=108,
            ai_udp_bypass_tiny_crop=True,
        ):
            out = service.apply_mode_fov(frame)
            self.assertEqual(out.shape[:2], (216, 216), "Colorbot crop behaviour changed")

    def test_capture_apply_mode_fov_honours_guard_off(self):
        from src.capture.capture_service import CaptureService

        service = CaptureService()
        service.mode = "UDP"
        frame = np.zeros((720, 1280, 3), np.uint8)
        with _ConfigSandbox(
            detection_engine="ai_detection",
            ai_model_path="models/my_yolo_model.onnx",
            udp_fov_enabled=True,
            udp_fov=108,
            ai_udp_bypass_tiny_crop=False,
        ):
            out = service.apply_mode_fov(frame)
            self.assertEqual(out.shape[:2], (216, 216))

    def test_telemetry_snapshot_fields_and_warnings(self):
        from src.utils.obs_udp_plugin import (
            build_udp_telemetry_snapshot,
            format_udp_telemetry_line,
        )

        receiver = MagicMock()
        receiver.is_receiving = True
        receiver.packet_count = 900
        receiver.fragment_drops = 3
        receiver.get_performance_stats.return_value = {
            "current_fps": 143.6,
            "decoding_fps": 142.1,
            "receive_delay_ms": 1.4,
            "decode_delay_ms": 0.6,
            "packet_count": 900,
            "last_packet_age_s": 0.004,
            "fragment_drops": 3,
            "is_receiving": True,
        }
        receiver.get_last_frame_meta.return_value = {"receive_ms": 1.7, "decode_ms": 0.5}
        receiver.get_current_frame.return_value = np.zeros((320, 320, 3), np.uint8)
        capture = MagicMock()
        capture.mode = "UDP"
        capture.is_connected.return_value = True
        capture.udp_manager.get_receiver.return_value = receiver
        capture._ip = "0.0.0.0"
        capture._port = 5000

        with _ConfigSandbox(
            detection_engine="ai_detection",
            ai_model_path="models/my_yolo_model.onnx",
            udp_fov_enabled=True,
            udp_fov=108,
            ai_udp_bypass_tiny_crop=True,
        ):
            snapshot = build_udp_telemetry_snapshot(
                capture, plugin_status={"installed": True, "missing": []}
            )

        self.assertTrue(snapshot["available"])
        self.assertTrue(snapshot["connected"])
        self.assertTrue(snapshot["receiving"])
        self.assertFalse(snapshot["starved"])
        self.assertAlmostEqual(snapshot["fps"], 143.6, places=1)
        self.assertAlmostEqual(snapshot["decode_fps"], 142.1, places=1)
        self.assertEqual(snapshot["resolution"], "320x320")
        self.assertAlmostEqual(snapshot["receive_ms"], 1.7, places=2)
        self.assertAlmostEqual(snapshot["decode_ms"], 0.5, places=2)
        self.assertEqual(snapshot["fragment_drops"], 3)
        self.assertEqual(snapshot["endpoint"], "0.0.0.0:5000")
        codes = {w["code"] for w in snapshot["warnings"]}
        self.assertIn("fragment_drops", codes)
        self.assertIn("tiny_crop_bypassed", codes)
        self.assertNotIn("plugin_missing", codes)
        line = format_udp_telemetry_line(snapshot)
        self.assertIn("320x320", line)
        self.assertIn("drops 3", line)

    def test_telemetry_flags_starved_and_missing_plugin(self):
        from src.utils.obs_udp_plugin import build_udp_telemetry_snapshot

        receiver = MagicMock()
        receiver.packet_count = 0
        receiver.fragment_drops = 0
        receiver.get_performance_stats.return_value = {
            "current_fps": 0.0,
            "packet_count": 0,
            "last_packet_age_s": None,
            "fragment_drops": 0,
        }
        receiver.get_last_frame_meta.return_value = {}
        receiver.get_current_frame.return_value = None
        capture = MagicMock()
        capture.mode = "UDP"
        capture.is_connected.return_value = True
        capture.udp_manager.get_receiver.return_value = receiver

        with _ConfigSandbox(detection_engine="ai_detection", udp_fov_enabled=False):
            snapshot = build_udp_telemetry_snapshot(
                capture,
                plugin_status={"installed": False, "missing": ["obs-color-correction.dll"]},
            )

        self.assertTrue(snapshot["starved"])
        codes = {w["code"] for w in snapshot["warnings"]}
        self.assertIn("starved", codes)
        self.assertIn("plugin_missing", codes)

    def test_telemetry_survives_a_mock_capture(self):
        from src.utils.obs_udp_plugin import build_udp_telemetry_snapshot

        snapshot = build_udp_telemetry_snapshot(MagicMock(), plugin_status={"installed": True})
        self.assertIn("available", snapshot)
        self.assertIsInstance(snapshot["warnings"], list)

    def test_config_round_trips_new_ai_udp_keys(self):
        from src.utils.config import Config

        probe = Config()
        probe.ai_udp_bypass_tiny_crop = False
        probe.ai_udp_min_crop_px = 512
        probe.ai_udp_stream_enabled = True
        data = probe.to_dict()
        for key in ("ai_udp_bypass_tiny_crop", "ai_udp_min_crop_px", "ai_udp_stream_enabled"):
            self.assertIn(key, data)
        clone = Config()
        clone.from_dict(data)
        self.assertFalse(clone.ai_udp_bypass_tiny_crop)
        self.assertEqual(clone.ai_udp_min_crop_px, 512)
        self.assertTrue(clone.ai_udp_stream_enabled)

    def test_track_frame_survives_mock_capture_crop_state(self):
        """main.py's guard must ignore a MagicMock ``get_udp_crop_state``."""
        import main as main_module

        tracker = main_module.AimTracker.__new__(main_module.AimTracker)
        tracker.app = MagicMock()
        tracker.app.capture.apply_mode_fov.side_effect = lambda img: img
        tracker.app.capture.get_frame_meta.return_value = {}
        tracker._frame_count = 0
        tracker._last_frame_log_time = 0.0
        tracker._last_frame_seq = 1
        tracker._last_engine_toggle_key_state = False
        tracker.model = None
        tracker.perf = {}
        tracker._compute_detection_roi = MagicMock(return_value=None)
        tracker._aim_and_move = MagicMock()
        tracker._update_raw_stream_windows = MagicMock()
        tracker._draw_enhanced_detection = MagicMock(side_effect=lambda img, *a: img)
        tracker._draw_fovs = MagicMock()
        tracker._draw_body = MagicMock()
        tracker._draw_head_bbox = MagicMock()

        with _ConfigSandbox(ai_detection_enabled=True, show_opencv_windows=False, detection_roi_enabled=False):
            with patch.object(
                main_module,
                "analyze",
                return_value=detection.DetectionFrame([], None, None, None, False, 0, (320, 320, 3)),
            ):
                tracker._track_frame(np.zeros((320, 320, 3), np.uint8))
        self.assertNotIn("ai_udp_crop_bypass", tracker.perf)

    def test_track_frame_reports_crop_guard_state_once(self):
        """A real dict from the capture service lands in perf and logs once."""
        import main as main_module

        tracker = main_module.AimTracker.__new__(main_module.AimTracker)
        tracker.app = MagicMock()
        tracker.app.capture.apply_mode_fov.side_effect = lambda img: img
        tracker.app.capture.get_frame_meta.return_value = {}
        tracker.app.capture.get_udp_crop_state.return_value = {
            "bypass": True, "reason": "tiny_crop", "total_px": 216, "min_px": 320,
        }
        tracker._frame_count = 0
        tracker._last_frame_log_time = 0.0
        tracker._last_frame_seq = 1
        tracker._last_engine_toggle_key_state = False
        tracker.model = None
        tracker.perf = {}
        tracker._compute_detection_roi = MagicMock(return_value=None)
        tracker._aim_and_move = MagicMock()
        tracker._update_raw_stream_windows = MagicMock()
        tracker._draw_enhanced_detection = MagicMock(side_effect=lambda img, *a: img)
        tracker._draw_fovs = MagicMock()
        tracker._draw_body = MagicMock()
        tracker._draw_head_bbox = MagicMock()

        with _ConfigSandbox(ai_detection_enabled=True, show_opencv_windows=False, detection_roi_enabled=False):
            with patch.object(
                main_module,
                "analyze",
                return_value=detection.DetectionFrame([], None, None, None, False, 0, (320, 320, 3)),
            ):
                tracker._track_frame(np.zeros((320, 320, 3), np.uint8))
        self.assertTrue(tracker.perf.get("ai_udp_crop_bypass"))
        self.assertEqual(tracker.perf.get("ai_udp_crop_reason"), "tiny_crop")
        self.assertTrue(tracker._ai_udp_bypass_active)


class TestObsUdpPluginFixes(unittest.TestCase):
    """Regressions for the reviewer's FIX round on the OBS UDP integration."""

    def test_connect_udp_failure_restores_the_previous_capture_mode(self):
        """A failed bind must not leave the service claiming ``mode == "UDP"``.

        ``connect_udp`` used to assign mode/_ip/_port before binding, so a port
        already held by another instance left the crop guard, telemetry, footer
        and read_frame talking about a UDP stream that was never connected.
        """
        from src.capture import capture_service as capture_module

        if not capture_module.HAS_UDP:
            self.skipTest("OBS_UDP receiver module is unavailable in this environment")
        service = capture_module.CaptureService()
        service.mode = "NDI"
        service._ip = "127.0.0.1"
        service._port = 1234
        service._udp_crop_cache = ("stale", {"bypass": True, "reason": "tiny_crop"})
        service.udp_manager = MagicMock()
        service.udp_manager.connect.return_value = False

        ok, error = service.connect_udp("0.0.0.0", 5000)

        self.assertFalse(ok)
        self.assertTrue(error)
        self.assertEqual(service.mode, "NDI")
        self.assertEqual(service._ip, "127.0.0.1")
        self.assertEqual(service._port, 1234)
        state = service.get_udp_crop_state()
        self.assertEqual(state.get("mode"), "NDI")
        self.assertFalse(state.get("bypass"))

    def test_connect_udp_success_switches_mode_and_endpoint(self):
        from src.capture import capture_service as capture_module

        if not capture_module.HAS_UDP:
            self.skipTest("OBS_UDP receiver module is unavailable in this environment")
        service = capture_module.CaptureService()
        service.mode = "NDI"
        service.udp_manager = MagicMock()
        service.udp_manager.connect.return_value = True

        ok, error = service.connect_udp("0.0.0.0", "5000")

        self.assertTrue(ok)
        self.assertIsNone(error)
        self.assertEqual(service.mode, "UDP")
        self.assertEqual(service._ip, "0.0.0.0")
        self.assertEqual(service._port, 5000)
        service.udp_manager.connect.assert_called_with("0.0.0.0", 5000, target_fps=0)

    def test_crop_decision_is_computed_once_per_config_signature(self):
        """The hot path must not rebuild the policy dict every frame twice."""
        from src.capture import capture_service as capture_module
        from src.capture.capture_service import CaptureService
        from src.utils.obs_udp_plugin import udp_crop_decision as real_policy

        service = CaptureService()
        service.mode = "UDP"
        frame = np.zeros((1080, 1920, 3), np.uint8)
        with _ConfigSandbox(
            detection_engine="ai_detection",
            ai_model_path="models/my_yolo_model.onnx",
            udp_fov_enabled=True,
            udp_fov=108,
            ai_udp_bypass_tiny_crop=True,
        ):
            with patch.object(capture_module, "_udp_crop_decision_policy", wraps=real_policy) as policy:
                for _ in range(5):
                    service.apply_mode_fov(frame)
                    state = service.get_udp_crop_state()
                self.assertEqual(state.get("reason"), "tiny_crop")
                self.assertEqual(policy.call_count, 1, "policy rebuilt per frame")

                # A config change must invalidate the memo (no stale bypass).
                config.udp_fov = 400
                state = service.get_udp_crop_state()
                self.assertEqual(state.get("reason"), "crop_ok")
                self.assertEqual(policy.call_count, 2)

    def test_wait_for_install_reports_the_real_state_not_the_launcher(self):
        """Completion is decided by the DLLs on disk, never by an exit code."""
        from src.utils import obs_udp_plugin

        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_root = os.path.join(tmpdir, "bundle")
            os.makedirs(os.path.join(plugin_root, "obs-plugins", "64bit"))
            os.makedirs(os.path.join(plugin_root, "bin", "64bit"))
            for name in ("install.ps1", "install.bat"):
                with open(os.path.join(plugin_root, name), "w", encoding="utf-8") as handle:
                    handle.write("exit 0")
            obs_dir = os.path.join(tmpdir, "obs")
            turbo_dir = os.path.join(tmpdir, "turbo")
            os.makedirs(turbo_dir)

            status = obs_udp_plugin.wait_for_install(
                plugin_root, obs_dir, turbo_dir, timeout=0.2, interval=0.05
            )
            self.assertFalse(status["installed"])
            self.assertIn("obs-color-correction.dll", " ".join(status["missing"]))

            os.makedirs(os.path.join(obs_dir, "obs-plugins", "64bit"))
            os.makedirs(os.path.join(obs_dir, "bin", "64bit"))
            for path in (
                os.path.join(obs_dir, "obs-plugins", "64bit", "obs-color-correction.dll"),
                os.path.join(obs_dir, "bin", "64bit", "turbojpeg.dll"),
                os.path.join(turbo_dir, "turbojpeg.dll"),
            ):
                open(path, "wb").close()

            status = obs_udp_plugin.wait_for_install(
                plugin_root, obs_dir, turbo_dir, timeout=0.2, interval=0.05
            )
            self.assertTrue(status["installed"])

    def test_elevated_install_command_waits_for_the_elevated_process(self):
        """``Start-Process`` needs ``-Wait``; without it a UAC prompt returns 0."""
        from src.utils.obs_udp_plugin import build_install_command

        root = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "..",
            "OBS-xUDP-Plugin",
        )
        root = os.path.abspath(root)
        if not os.path.isdir(root):
            self.skipTest("shipped OBS bundle not present in this checkout")
        command = build_install_command(root, elevated=True)
        self.assertIsNotNone(command)
        text = " ".join(command)
        self.assertIn("RunAs", text)
        self.assertIn("-Wait", text)

    def test_jpeg_quality_constant_is_the_single_source_of_truth(self):
        """The preset, its text form and the tests must agree; no phantom range."""
        from src.utils import obs_udp_plugin

        self.assertFalse(hasattr(obs_udp_plugin, "AI_OBS_JPEG_QUALITY_RANGE"))
        preset = obs_udp_plugin.build_ai_obs_filter_preset("models/my_yolo_model.onnx")
        self.assertEqual(preset["jpeg_quality"], obs_udp_plugin.AI_OBS_JPEG_QUALITY)
        self.assertTrue(80 <= preset["jpeg_quality"] <= 85)
        text = obs_udp_plugin.format_ai_obs_filter_preset(preset)
        self.assertIn("JPEG Quality: %d" % obs_udp_plugin.AI_OBS_JPEG_QUALITY, text)

    def test_resolve_plugin_root_has_no_unreachable_override(self):
        """No ``obs_udp_plugin_root`` config key exists, so no override parameter."""
        import inspect

        from src.utils.obs_udp_plugin import resolve_plugin_root

        self.assertEqual(list(inspect.signature(resolve_plugin_root).parameters), [])
        self.assertFalse(hasattr(config, "obs_udp_plugin_root"))


class TestTeammateCapability(unittest.TestCase):
    """The detector must describe whether the model can name a team-mate."""

    def test_supports_teammate_class_true_for_metadata_names(self):
        det = _bare_detector(METADATA_NAMES)
        self.assertTrue(det.supports_teammate_class())

    def test_supports_teammate_class_false_for_player_only_names(self):
        det = _bare_detector(["head", "body", "body", "body"])
        self.assertFalse(det.supports_teammate_class())

    def test_supports_teammate_class_tolerates_non_iterable_class_names(self):
        det = _bare_detector(["body", "head"])
        det.class_names = None
        self.assertFalse(det.supports_teammate_class())
        det.class_names = 42
        self.assertFalse(det.supports_teammate_class())
        det.class_names = MagicMock()
        self.assertFalse(det.supports_teammate_class())

    def test_teammate_capability_summary_reports_native_class(self):
        det = _bare_detector(METADATA_NAMES)
        summary = det.teammate_capability_summary()
        self.assertIn("Native 'teammate' class", summary)
        self.assertIn("5 classes", summary)
        self.assertIn("body", summary)

    def test_teammate_capability_summary_requests_the_guard_for_player_only(self):
        det = _bare_detector(["head", "body", "body", "body"])
        summary = det.teammate_capability_summary()
        self.assertIn("Player-only", summary)
        self.assertIn("Enemy Outline Guard required", summary)
        # Deduplicated listing, but the real class count is still reported.
        self.assertIn("4 classes", summary)
        self.assertEqual(summary.count("body"), 1)
        self.assertNotIn("Native 'teammate'", summary)

    def test_teammate_capability_summary_without_a_model(self):
        det = _bare_detector([])
        det.class_names = []
        self.assertEqual(
            det.teammate_capability_summary(), "Class list unavailable (model not loaded)"
        )

    def test_teammate_capability_summary_loaded_without_metadata_never_prints_defaults(self):
        """A loaded model whose metadata was unreadable must not display DEFAULT_CLASS_NAMES."""
        det = _bare_detector(["enemy", "head"])
        det.metadata_names = None
        det.session = MagicMock()
        det.is_loaded = True
        self.assertTrue(det.is_ready())
        summary = det.teammate_capability_summary()
        self.assertEqual(summary, "Class list unavailable (no model metadata)")
        self.assertNotIn("Player-only", summary)


PURPLE_BAND = ((125, 60, 80), (170, 255, 255))
DARK_GREY_BGR = (40, 40, 40)


def _frame_with_outlines(size=(240, 320), bodies=(), heads=()):
    """Build a BGR frame with dark boxes and optional purple outline bands.

    ``bodies``/``heads`` items are ``(bbox, outline)``. An outline is drawn as a
    4px purple border sitting 2px outside the box, i.e. exactly in the band the
    filter inspects, and the box interior is then repainted dark so the colour
    can only ever be found on the ring.
    """
    height, width = size
    hsv = np.zeros((height, width, 3), np.uint8)
    for bbox, outline in list(bodies) + list(heads):
        x, y, w, h = bbox
        hsv[y:y + h, x:x + w] = DARK_GREY_BGR
        if outline:
            cv2.rectangle(hsv, (x - 2, y - 2), (x + w + 2, y + h + 2), (150, 220, 220), 4)
    painted = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
    # Restore the plain box interiors so only the ring carries the colour.
    for bbox, _outline in list(bodies) + list(heads):
        x, y, w, h = bbox
        painted[y:y + h, x:x + w] = DARK_GREY_BGR
    return painted


# The head sits well inside its body, away from the body's outline ring: only
# the pairing rule can certify it, which is exactly what must be proven.
ENEMY_BODY = (40, 60, 40, 80)
ENEMY_HEAD = (50, 80, 20, 20)
TEAMMATE_BODY = (200, 60, 40, 80)
TEAMMATE_HEAD = (210, 80, 20, 20)


def _enemy_and_teammate_detections():
    """An outlined enemy (body + head) and an unoutlined team-mate (same)."""
    return [
        {"class": "body", "bbox": ENEMY_BODY, "confidence": 0.94},
        {"class": "head", "bbox": ENEMY_HEAD, "confidence": 0.90},
        {"class": "body", "bbox": TEAMMATE_BODY, "confidence": 0.88},
        {"class": "head", "bbox": TEAMMATE_HEAD, "confidence": 0.85},
    ]


def _enemy_and_teammate_frame():
    return _frame_with_outlines(
        bodies=[
            (ENEMY_BODY, True),      # enemy body, outlined
            (TEAMMATE_BODY, False),  # team-mate body, no outline
        ],
        heads=[
            (ENEMY_HEAD, False),      # enemy head: certified by its body only
            (TEAMMATE_HEAD, False),   # team-mate head: no outline anywhere
        ],
    )


class TestEnemyOutlineFilter(unittest.TestCase):
    """``filter_enemy_detections`` keeps enemies and drops unoutlined boxes."""

    def test_filter_keeps_enemy_body_with_outline_and_its_head(self):
        from src.utils.ai_detection import filter_enemy_detections

        detections = _enemy_and_teammate_detections()
        kept = filter_enemy_detections(
            detections,
            _enemy_and_teammate_frame(),
            hsv_min=np.array(PURPLE_BAND[0], np.uint8),
            hsv_max=np.array(PURPLE_BAND[1], np.uint8),
            min_pixels=4,
        )

        classes = [(d["class"], d["bbox"]) for d in kept]
        self.assertEqual(
            classes,
            [("body", ENEMY_BODY), ("head", ENEMY_HEAD)],
            "the outlined enemy body and its own head must survive",
        )
        # Shallow copies: the caller's raw list is untouched.
        self.assertEqual(len(detections), 4)
        self.assertIsNot(kept[0], detections[0])

    def test_filter_drops_teammate_body_and_its_head_without_outline(self):
        from src.utils.ai_detection import filter_enemy_detections

        frame = _enemy_and_teammate_frame()
        kept = filter_enemy_detections(
            _enemy_and_teammate_detections(),
            frame,
            hsv_min=np.array(PURPLE_BAND[0], np.uint8),
            hsv_max=np.array(PURPLE_BAND[1], np.uint8),
            min_pixels=4,
        )
        bboxes = {d["bbox"] for d in kept}
        self.assertNotIn(TEAMMATE_BODY, bboxes)
        self.assertNotIn(TEAMMATE_HEAD, bboxes)
        self.assertEqual(len(kept), 2)

    def test_filter_checks_a_standalone_head_directly(self):
        from src.utils.ai_detection import filter_enemy_detections

        outlined = (50, 80, 20, 20)
        bare = (210, 80, 20, 20)
        frame = _frame_with_outlines(heads=[(outlined, True), (bare, False)])
        detections = [
            {"class": "head", "bbox": outlined, "confidence": 0.9},
            {"class": "head", "bbox": bare, "confidence": 0.8},
        ]
        kept = filter_enemy_detections(
            detections,
            frame,
            hsv_min=np.array(PURPLE_BAND[0], np.uint8),
            hsv_max=np.array(PURPLE_BAND[1], np.uint8),
            min_pixels=4,
        )
        self.assertEqual([d["bbox"] for d in kept], [outlined])

    def test_filter_drops_unknown_classes_and_unparsable_boxes(self):
        from src.utils.ai_detection import filter_enemy_detections

        frame = _frame_with_outlines(bodies=[(ENEMY_BODY, True)])
        detections = [
            {"class": "teammate", "bbox": ENEMY_BODY, "confidence": 0.99},
            {"class": "breakable", "bbox": ENEMY_BODY, "confidence": 0.99},
            {"class": "body", "bbox": "not a box", "confidence": 0.99},
            {"class": "body", "confidence": 0.99},
            {"class": "body", "bbox": ENEMY_BODY, "confidence": 0.5},
        ]
        kept = filter_enemy_detections(
            detections,
            frame,
            hsv_min=np.array(PURPLE_BAND[0], np.uint8),
            hsv_max=np.array(PURPLE_BAND[1], np.uint8),
            min_pixels=4,
        )
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["confidence"], 0.5)
        self.assertEqual(kept[0]["class"], "body")

    def test_filter_respects_min_pixels_and_custom_hsv(self):
        from src.utils.ai_detection import filter_enemy_detections

        # A single purple speck in the band: enough for min_pixels=1, not for 4.
        specks = np.zeros((240, 320, 3), np.uint8)
        specks[59, 39] = cv2.cvtColor(
            np.array([[[150, 220, 220]]], np.uint8), cv2.COLOR_HSV2BGR
        )[0, 0]
        detections = [{"class": "body", "bbox": ENEMY_BODY, "confidence": 0.9}]
        purple = (np.array(PURPLE_BAND[0], np.uint8), np.array(PURPLE_BAND[1], np.uint8))

        self.assertEqual(
            len(filter_enemy_detections(
                detections, specks, hsv_min=purple[0], hsv_max=purple[1], min_pixels=1
            )),
            1,
            "a single outline pixel must satisfy min_pixels=1",
        )
        self.assertEqual(
            filter_enemy_detections(
                detections, specks, hsv_min=purple[0], hsv_max=purple[1], min_pixels=4
            ),
            [],
            "one stray pixel must not certify a body at min_pixels=4",
        )
        # The rule is "outline colour only": a yellow band rejects purple.
        self.assertEqual(
            filter_enemy_detections(
                detections, specks,
                hsv_min=np.array([18, 80, 80], np.uint8),
                hsv_max=np.array([40, 255, 255], np.uint8),
                min_pixels=1,
            ),
            [],
        )

    def test_filter_uses_custom_hsv_when_asked(self):
        from src.utils.ai_detection import filter_enemy_detections

        frame = _frame_with_outlines(bodies=[(ENEMY_BODY, True)])
        detections = [{"class": "body", "bbox": ENEMY_BODY, "confidence": 0.9}]
        # The purple band from the frame, expressed as a custom (pinned) range,
        # keeps the body; a narrower custom range rejects it.
        self.assertEqual(
            len(filter_enemy_detections(
                detections, frame,
                hsv_min=np.array(PURPLE_BAND[0], np.uint8),
                hsv_max=np.array(PURPLE_BAND[1], np.uint8),
                min_pixels=4,
            )),
            1,
        )
        with _ConfigSandbox(
            color="custom",
            custom_hsv_min_h=100, custom_hsv_min_s=0, custom_hsv_min_v=0,
            custom_hsv_max_h=101, custom_hsv_max_s=255, custom_hsv_max_v=255,
        ):
            self.assertEqual(
                filter_enemy_detections(detections, frame),
                [],
                "the guard must honour the custom HSV band, not a preset",
            )

    def test_filter_is_fail_open_on_unusable_image_or_colour(self):
        from src.utils.ai_detection import filter_enemy_detections

        detections = [{"class": "body", "bbox": (10, 10, 20, 20), "confidence": 0.9}]
        for image in (None, np.zeros((0, 0, 3), np.uint8), np.zeros((20, 20), np.uint8)):
            kept = filter_enemy_detections(
                detections, image,
                hsv_min=np.array(PURPLE_BAND[0], np.uint8),
                hsv_max=np.array(PURPLE_BAND[1], np.uint8),
            )
            self.assertEqual(len(kept), 1, f"fail-open broke for image={type(image)}")

        with _ConfigSandbox(color="not-a-colour"):
            kept = filter_enemy_detections(
                detections, np.zeros((40, 40, 3), np.uint8)
            )
        self.assertEqual(len(kept), 1, "an unresolvable colour must not blind the guard")

    def test_filter_is_fail_open_on_a_reversed_custom_band(self):
        """``MIN > MAX`` yields an all-zero mask, so it must be refused, not used.

        ``cv2.inRange`` with an inverted band matches nothing: without an
        explicit check the guard would drop *every* box while reporting a normal
        run, i.e. a hand-edited ``config.json`` (or an imported profile) could
        silently blind the AI engine. The band is unresolvable, so the guard
        fails open exactly like an unknown colour.
        """
        from src.utils.ai_detection import filter_enemy_detections

        frame = _enemy_and_teammate_frame()
        detections = [{"class": "body", "bbox": ENEMY_BODY, "confidence": 0.9}]
        with _ConfigSandbox(
            color="custom",
            custom_hsv_min_h=170, custom_hsv_min_s=255, custom_hsv_min_v=255,
            custom_hsv_max_h=10, custom_hsv_max_s=10, custom_hsv_max_v=10,
        ):
            kept = filter_enemy_detections(detections, frame)
        self.assertEqual(
            [d["bbox"] for d in kept],
            [ENEMY_BODY],
            "a reversed custom band silently dropped the enemy instead of failing open",
        )

        # An explicit band skips the config lookup, so the filter has to refuse
        # it on its own instead of handing it to cv2.inRange.
        kept = filter_enemy_detections(
            detections,
            frame,
            hsv_min=np.array([170, 255, 255], np.uint8),
            hsv_max=np.array([10, 10, 10], np.uint8),
        )
        self.assertEqual([d["bbox"] for d in kept], [ENEMY_BODY])

    def test_enemy_outline_hsv_range_rejects_a_reversed_custom_band(self):
        from src.utils.detection import enemy_outline_hsv_range

        with _ConfigSandbox(
            color="custom",
            custom_hsv_min_h=170, custom_hsv_min_s=255, custom_hsv_min_v=255,
            custom_hsv_max_h=10, custom_hsv_max_s=10, custom_hsv_max_v=10,
        ):
            with self.assertRaises(ValueError):
                enemy_outline_hsv_range()

        # One reversed channel is enough; a valid band must still pass through.
        with _ConfigSandbox(
            color="custom",
            custom_hsv_min_h=132, custom_hsv_min_s=155, custom_hsv_min_v=140,
            custom_hsv_max_h=156, custom_hsv_max_s=100, custom_hsv_max_v=255,
        ):
            with self.assertRaises(ValueError):
                enemy_outline_hsv_range()

        with _ConfigSandbox(
            color="custom",
            custom_hsv_min_h=132, custom_hsv_min_s=155, custom_hsv_min_v=140,
            custom_hsv_max_h=156, custom_hsv_max_s=255, custom_hsv_max_v=255,
        ):
            low, high = enemy_outline_hsv_range()
        self.assertEqual([int(v) for v in low], [132, 155, 140])
        self.assertEqual([int(v) for v in high], [156, 255, 255])

    def test_filter_fail_open_still_drops_non_target_classes(self):
        """Fail-open must not resurrect a team-mate box the allow-list rejects.

        Fail-open means "cannot verify the outline", not "the allow-list is
        lifted": a ``teammate`` box kept here would only be dropped later by
        ``main.build_aim_targets``, while this function would have claimed it
        returned aim candidates.
        """
        from src.utils.ai_detection import filter_enemy_detections

        detections = [
            {"class": "teammate", "bbox": (10, 10, 20, 20), "confidence": 0.99},
            {"class": "breakable", "bbox": (10, 10, 20, 20), "confidence": 0.99},
            {"class": "body", "bbox": "not a box", "confidence": 0.98},
            {"class": "body", "bbox": (10, 10, 20, 20), "confidence": 0.90},
            {"class": "head", "bbox": (12, 12, 8, 8), "confidence": 0.80},
        ]
        kept = filter_enemy_detections(
            detections,
            None,
            hsv_min=np.array(PURPLE_BAND[0], np.uint8),
            hsv_max=np.array(PURPLE_BAND[1], np.uint8),
        )
        self.assertEqual(
            [(d["class"], d["bbox"]) for d in kept],
            [("body", (10, 10, 20, 20)), ("head", (12, 12, 8, 8))],
            "fail-open kept a non-target class or an unparsable box",
        )

    def test_filter_detector_argument_never_changes_keep_drop_decisions(self):
        """``detector`` is diagnostic only: ``mode`` alone decides.

        A caller passing a teammate-capable detector must get exactly the same
        boxes as one passing none, otherwise "Always On" would silently trust
        the model it was chosen to override.
        """
        from src.utils.ai_detection import filter_enemy_detections

        frame = _enemy_and_teammate_frame()
        detections = _enemy_and_teammate_detections()
        native = _bare_detector(METADATA_NAMES)
        player_only = _bare_detector(["head", "body"])

        baseline = filter_enemy_detections(
            detections,
            frame,
            hsv_min=np.array(PURPLE_BAND[0], np.uint8),
            hsv_max=np.array(PURPLE_BAND[1], np.uint8),
            min_pixels=4,
        )
        for detector in (native, player_only):
            self.assertEqual(
                filter_enemy_detections(
                    detections,
                    frame,
                    detector=detector,
                    hsv_min=np.array(PURPLE_BAND[0], np.uint8),
                    hsv_max=np.array(PURPLE_BAND[1], np.uint8),
                    min_pixels=4,
                ),
                baseline,
            )
        self.assertEqual([d["bbox"] for d in baseline], [ENEMY_BODY, ENEMY_HEAD])

    def test_filter_fail_open_logs_are_throttled(self):
        """Repeated fail-open frames must not spam tracking-thread logs at ~144 Hz."""
        import src.utils.ai_detection as ai_mod
        from src.utils.ai_detection import filter_enemy_detections

        detections = [{"class": "body", "bbox": ENEMY_BODY, "confidence": 0.9}]
        times = iter([10.0, 10.1, 10.5, 11.9, 12.1])
        old_last = ai_mod._last_ai_outline_skip_log_time
        try:
            ai_mod._last_ai_outline_skip_log_time = None
            with patch.object(ai_mod, "log_print") as log_mock, patch.object(
                ai_mod.time, "monotonic", side_effect=lambda: next(times)
            ):
                for _ in range(5):
                    kept = filter_enemy_detections(detections, None)
                    self.assertEqual(len(kept), 1)
            self.assertEqual(log_mock.call_count, 2)
        finally:
            ai_mod._last_ai_outline_skip_log_time = old_last


class _OutlineSandbox:
    """Pin the AI outline keys plus the colour for one analyze() test."""

    def __init__(self, mode="auto", color="purple", min_pixels=4, **extra):
        self.values = {
            "ai_enemy_outline_filter": mode,
            "ai_enemy_outline_min_pixels": min_pixels,
            "color": color,
            "ai_detection_enabled": True,
            **extra,
        }
        self.sandbox = _ConfigSandbox(**self.values)

    def __enter__(self):
        return self.sandbox.__enter__()

    def __exit__(self, *exc_info):
        return self.sandbox.__exit__(*exc_info)


def _analyze_detector(class_names, detections, supports=None):
    """A detector mock that survives every guard in ``analyze``.

    ``class_names`` is a *real* list on purpose: the auto mode only trusts a
    real list/tuple, and a plain MagicMock detector is covered separately.
    """
    detector = MagicMock()
    detector.is_ready.return_value = True
    detector.class_names = list(class_names)
    detector.detect.return_value = [dict(d) for d in detections]
    if supports is None:
        supports = any(str(n).lower() == "teammate" for n in class_names)
    detector.supports_teammate_class.return_value = bool(supports)
    return detector


class TestAnalyzeEnemyOutlineModes(unittest.TestCase):
    """``detection.analyze(engine='ai')`` under auto / on / off."""

    def _analyze(self, detector, mode="auto"):
        from unittest.mock import patch as _patch

        with _OutlineSandbox(mode=mode), _patch(
            "src.utils.ai_detection.get_ai_detector", return_value=detector
        ):
            return detection.analyze(
                None, _enemy_and_teammate_frame(), engine="ai"
            )

    def test_analyze_ai_auto_filters_player_only_model(self):
        detector = _analyze_detector(["head", "body"], _enemy_and_teammate_detections())
        frame = self._analyze(detector, mode="auto")

        self.assertEqual(frame.source, "ai")
        classes = [(d["class"], d["bbox"]) for d in frame.detections]
        self.assertEqual(classes, [("body", ENEMY_BODY), ("head", ENEMY_HEAD)])
        # The mask follows the filtered list, not the raw one. The head sits
        # inside its body box, so the rasterised area is the body box alone.
        self.assertEqual(frame.mask_nonzero, 40 * 80)
        mask = frame.raw_mask
        self.assertEqual(int(mask[60, 40]), 255)
        self.assertEqual(int(mask[60, 200]), 0, "the team-mate box is still in the mask")

    def test_analyze_ai_auto_skips_teammate_capable_model(self):
        detector = _analyze_detector(METADATA_NAMES, _enemy_and_teammate_detections())
        frame = self._analyze(detector, mode="auto")

        self.assertEqual(len(frame.detections), 4, "auto must trust a teammate-capable model")
        detector.supports_teammate_class.assert_called()

    def test_analyze_ai_on_filters_even_with_teammate_class(self):
        detector = _analyze_detector(METADATA_NAMES, _enemy_and_teammate_detections())
        frame = self._analyze(detector, mode="on")

        self.assertEqual(
            [d["bbox"] for d in frame.detections],
            [ENEMY_BODY, ENEMY_HEAD],
            "Always On must not trust the model's teammate class",
        )

    def test_analyze_ai_off_keeps_every_box(self):
        detector = _analyze_detector(["head", "body"], _enemy_and_teammate_detections())
        frame = self._analyze(detector, mode="off")

        self.assertEqual(len(frame.detections), 4)
        # Both heads sit inside their body boxes, so the two body boxes are the
        # whole rasterised area.
        self.assertEqual(frame.mask_nonzero, 2 * (40 * 80))

    def test_analyze_ai_on_with_roi_keeps_full_frame_coordinates(self):
        """The guard must verify the full frame while boxes stay full-frame.

        ``detect`` already added the ROI offset to every bbox, so the filter has
        to be handed the *full* image, not the crop. Handing it the crop would
        shift every box by the ROI origin and reject a real enemy whose outline
        was drawn in frame coordinates.
        """
        from unittest.mock import patch as _patch
        import src.utils.ai_detection as ai_mod

        frame_image = _enemy_and_teammate_frame()
        roi = (20, 40, 260, 160)  # around the enemy, 240x120 < 70% of 240x320
        detector = _analyze_detector(["head", "body"], _enemy_and_teammate_detections())
        seen = {}
        real_filter = ai_mod.filter_enemy_detections

        def _spy(detections, image, **kwargs):
            seen["shape"] = None if image is None else tuple(image.shape)
            seen["boxes"] = [d["bbox"] for d in detections]
            return real_filter(detections, image, **kwargs)

        with _OutlineSandbox(mode="on", detection_roi_max_fraction=0.70), _patch(
            "src.utils.ai_detection.get_ai_detector", return_value=detector
        ), _patch.object(ai_mod, "filter_enemy_detections", side_effect=_spy):
            frame = detection.analyze(None, frame_image, roi=roi, engine="ai")

        self.assertEqual(
            detector.detect.call_args.kwargs.get("roi"), roi,
            "the test did not exercise the ROI path",
        )
        self.assertEqual(
            seen["shape"], frame_image.shape,
            "the guard was handed the ROI crop instead of the full frame",
        )
        self.assertEqual(
            seen["boxes"], [ENEMY_BODY, ENEMY_HEAD, TEAMMATE_BODY, TEAMMATE_HEAD],
            "the guard did not receive the raw full-frame boxes",
        )
        self.assertEqual(
            [(d["class"], d["bbox"]) for d in frame.detections],
            [("body", ENEMY_BODY), ("head", ENEMY_HEAD)],
            "the outlined enemy was lost or shifted once a ROI was in play",
        )
        mask = frame.raw_mask
        self.assertEqual(int(mask[60, 40]), 255, "the enemy body left the AI mask")
        self.assertEqual(int(mask[60, 200]), 0, "the team-mate box is still in the mask")

    def test_analyze_ai_auto_skips_magicmock_detector(self):
        """The pre-existing tests drive analyze with a bare MagicMock: keep them."""
        from unittest.mock import patch as _patch

        detector = MagicMock()
        detector.is_ready.return_value = True
        detector.detect.return_value = [
            {"class": "player", "bbox": (50, 60, 40, 80), "confidence": 0.95}
        ]
        with _OutlineSandbox(mode="auto"), _patch(
            "src.utils.ai_detection.get_ai_detector", return_value=detector
        ):
            frame = detection.analyze(None, np.zeros((200, 200, 3), np.uint8), engine="ai")

        self.assertEqual(len(frame.detections), 1)
        self.assertEqual(frame.detections[0]["bbox"], (50, 60, 40, 80))

    def test_analyze_ai_empty_filtered_result_stays_ai(self):
        """A guard that drops everything must not fall back to the colour pass."""
        detector = _analyze_detector(
            ["head", "body"],
            [{"class": "body", "bbox": TEAMMATE_BODY, "confidence": 0.9}],
        )
        from unittest.mock import patch as _patch

        with _OutlineSandbox(mode="on"), _patch(
            "src.utils.ai_detection.get_ai_detector", return_value=detector
        ):
            # No HSV model at all: a fallback would have nothing to fall back to.
            frame = detection.analyze(None, _enemy_and_teammate_frame(), engine="ai")

        self.assertEqual(frame.detections, [])
        self.assertEqual(frame.source, "ai")
        self.assertFalse(frame.has_mask)


class TestEnemyOutlineConfig(unittest.TestCase):
    """The two guard keys survive a save/load round-trip and are clamped."""

    def test_config_round_trips_enemy_outline_keys(self):
        from src.utils.config import Config

        probe = Config()
        probe.ai_enemy_outline_filter = "on"
        probe.ai_enemy_outline_min_pixels = 7
        data = probe.to_dict()
        for key in ("ai_enemy_outline_filter", "ai_enemy_outline_min_pixels"):
            self.assertIn(key, data)
        self.assertEqual(data["ai_enemy_outline_filter"], "on")
        self.assertEqual(data["ai_enemy_outline_min_pixels"], 7)

        clone = Config()
        clone.from_dict(data)
        self.assertEqual(clone.ai_enemy_outline_filter, "on")
        self.assertEqual(clone.ai_enemy_outline_min_pixels, 7)

    def test_enemy_outline_config_clamps_and_normalises(self):
        from src.utils.config import Config

        clone = Config()
        clone.from_dict({"ai_enemy_outline_filter": "bogus", "ai_enemy_outline_min_pixels": 0})
        self.assertEqual(clone.ai_enemy_outline_filter, "auto")
        self.assertEqual(clone.ai_enemy_outline_min_pixels, 1)

        clone.from_dict({"ai_enemy_outline_min_pixels": 999})
        self.assertEqual(clone.ai_enemy_outline_min_pixels, 50)

        clone.from_dict({"ai_enemy_outline_filter": "ON"})
        self.assertEqual(clone.ai_enemy_outline_filter, "on")

        clone.from_dict({"ai_enemy_outline_min_pixels": "not a number"})
        self.assertEqual(clone.ai_enemy_outline_min_pixels, 4)


if __name__ == "__main__":
    unittest.main()