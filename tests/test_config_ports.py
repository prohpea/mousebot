"""G1-G8: stream/feedback port defaults, migration and validation (plan §6.4).

Schema 5 moves the video stream to UDP 5000 (the plugin has always sent there)
and adds a configurable beep port (4455). These tests pin the fresh defaults,
the one-shot schema-4 migration, the "respect an explicit schema-5 value" rule,
garbage rejection and the JSON round-trip.
"""

import json
import os
import sys
import tempfile
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils.config import (  # noqa: E402
    CURRENT_CONFIG_SCHEMA,
    DEFAULT_AUDIO_FEEDBACK_PORT,
    DEFAULT_UDP_PORT,
    Config,
)


def fresh_config(data=None):
    """Build a Config from defaults only (never the shipped config.json)."""
    previous = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        try:
            cfg = Config()
        finally:
            os.chdir(previous)
    if data is not None:
        cfg.from_dict(data)
    return cfg


class TestConfigPorts(unittest.TestCase):
    # -- G1 ---------------------------------------------------------------
    def test_defaults(self):
        cfg = fresh_config()
        self.assertEqual(cfg.udp_port, "5000")
        self.assertEqual(cfg.udp_ip, "0.0.0.0")
        self.assertEqual(cfg.audio_feedback_port, 4455)
        self.assertIsInstance(cfg.udp_port, str)
        self.assertIsInstance(cfg.audio_feedback_port, int)
        self.assertEqual(CURRENT_CONFIG_SCHEMA, 5)
        self.assertEqual(DEFAULT_UDP_PORT, "5000")
        self.assertEqual(DEFAULT_AUDIO_FEEDBACK_PORT, 4455)

    # -- G2 ---------------------------------------------------------------
    def test_schema4_3110_migrates_to_5000(self):
        cfg = fresh_config({"config_schema": 4, "udp_port": "3110"})
        self.assertEqual(cfg.udp_port, "5000")
        self.assertEqual(cfg.config_schema, 5)

    # -- G3 ---------------------------------------------------------------
    def test_schema4_1234_and_empty_migrate(self):
        for legacy in ("1234", ""):
            cfg = fresh_config({"config_schema": 4, "udp_port": legacy})
            self.assertEqual(cfg.udp_port, "5000", legacy)

        cfg = fresh_config({"config_schema": 4})  # key absent entirely
        self.assertEqual(cfg.udp_port, "5000")

    # -- G4 ---------------------------------------------------------------
    def test_schema5_keeps_explicit_3110(self):
        cfg = fresh_config({"config_schema": 5, "udp_port": "3110"})
        self.assertEqual(cfg.udp_port, "3110")  # an explicit choice is respected
        self.assertEqual(cfg.config_schema, 5)

    # -- G5 ---------------------------------------------------------------
    def test_garbage_port_falls_back(self):
        for garbage in ("abc", "70000", "-1", "  ", "12.5", None):
            cfg = fresh_config({"config_schema": 5, "udp_port": garbage})
            self.assertEqual(cfg.udp_port, "5000", repr(garbage))

        # A numeric value in JSON is coerced to the string schema type.
        cfg = fresh_config({"config_schema": 5, "udp_port": 6000})
        self.assertEqual(cfg.udp_port, "6000")

        # An explicitly chosen valid non-default port survives.
        cfg = fresh_config({"config_schema": 5, "udp_port": "6001"})
        self.assertEqual(cfg.udp_port, "6001")

    # -- G6 ---------------------------------------------------------------
    def test_audio_feedback_port_garbage(self):
        for garbage in ("abc", "70000", "-1", None, ""):
            cfg = fresh_config({"config_schema": 5, "audio_feedback_port": garbage})
            self.assertEqual(cfg.audio_feedback_port, 4455, repr(garbage))

        cfg = fresh_config({"config_schema": 5, "audio_feedback_port": "5001"})
        self.assertEqual(cfg.audio_feedback_port, 5001)
        self.assertIsInstance(cfg.audio_feedback_port, int)

    # -- G7 ---------------------------------------------------------------
    def test_round_trip_to_dict(self):
        cfg = fresh_config({"config_schema": 5, "udp_port": "5000"})
        payload = cfg.to_dict()
        self.assertEqual(payload["udp_port"], "5000")
        self.assertEqual(payload["audio_feedback_port"], 4455)
        self.assertEqual(payload["config_schema"], 5)
        self.assertIsInstance(payload["audio_feedback_port"], int)

        encoded = json.dumps(payload)
        decoded = json.loads(encoded)
        restored = fresh_config(decoded)
        self.assertEqual(restored.udp_port, "5000")
        self.assertEqual(restored.audio_feedback_port, 4455)

    # -- G8 ---------------------------------------------------------------
    def test_shipped_config_files_use_5000(self):
        path = os.path.join(PROJECT_ROOT, "config.json")
        if not os.path.exists(path):
            self.skipTest("config.json is not shipped in this checkout")
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        self.assertEqual(str(data.get("udp_port")), "5000")
        self.assertEqual(data.get("config_schema"), 5)

        cfg = fresh_config()
        cfg.from_dict(data)
        self.assertEqual(cfg.udp_port, "5000")
        self.assertEqual(cfg.audio_feedback_port, 4455)


if __name__ == "__main__":
    unittest.main()
