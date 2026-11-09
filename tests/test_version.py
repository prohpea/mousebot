"""Version single-source tests (plan section 6.3 / V8).

The version used to live in six places: ``version.json``, the window title, the
title-bar label, a card badge, the AppUserModelID and the README/CHANGELOG. These
tests fail as soon as one of them drifts again.
"""

import os
import re
import sys
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src import version as version_module  # noqa: E402
from src.version import (  # noqa: E402
    VersionInfo,
    get_changelog,
    get_engine_badge,
    get_version,
    get_version_label,
    get_window_title,
    load_version_info,
    parse_version_payload,
)


def read_text(relative_path):
    with open(os.path.join(PROJECT_ROOT, relative_path), "r", encoding="utf-8") as handle:
        return handle.read()


class TestVersionFile(unittest.TestCase):
    def setUp(self):
        version_module.reset_cache()

    def test_version_json_is_2_1_0(self):
        info = load_version_info(refresh=True)
        self.assertEqual(info.version, "2.1.0")
        self.assertEqual(info.codename, "Flick V2")
        self.assertEqual(info.schema, 3)

    def test_release_date_is_iso(self):
        info = load_version_info(refresh=True)
        self.assertRegex(info.release_date, r"^\d{4}-\d{2}-\d{2}$")

    def test_changelog_describes_flick_v2(self):
        changelog = get_changelog()
        self.assertIn("2.1.0", changelog)
        self.assertIn("Flick V2", changelog)

    def test_payload_validation(self):
        info = parse_version_payload(
            {"version": "3.4.5", "codename": "Test", "schema": 4, "changelog": "hi"}
        )
        self.assertEqual(info.version, "3.4.5")
        self.assertEqual(info.codename, "Test")
        self.assertEqual(info.schema, 4)
        with self.assertRaises(ValueError):
            parse_version_payload({"version": "not-a-version"})
        with self.assertRaises(ValueError):
            parse_version_payload([1, 2, 3])

    def test_missing_fields_fall_back(self):
        info = parse_version_payload({"version": "9.9.9"})
        self.assertEqual(info.codename, version_module.CODENAME_FALLBACK)
        self.assertEqual(info.schema, version_module.SCHEMA_FALLBACK)

    def test_cache_uses_mtime_and_size(self):
        first = load_version_info(refresh=True)
        second = load_version_info()
        self.assertIs(first, second)
        third = load_version_info(refresh=True)
        self.assertEqual(third.version, first.version)


class TestVersionLabels(unittest.TestCase):
    def setUp(self):
        self.info = VersionInfo(
            version="2.1.0", codename="Flick V2", release_date="2026-11-09", schema=3
        )

    def test_label(self):
        self.assertEqual(self.info.label(), "v2.1.0 PRO")

    def test_badge_is_dynamic(self):
        self.assertEqual(self.info.badge(), "v2.1.0 \u00b7 Flick V2")

    def test_title(self):
        self.assertEqual(self.info.title(), "CVM colorBot v2.1.0 PRO")

    def test_summary(self):
        self.assertEqual(self.info.summary(), "v2.1.0 (Flick V2)")

    def test_optional_codename(self):
        info = VersionInfo(version="2.1.0", codename="")
        self.assertEqual(info.badge(), "v2.1.0")
        self.assertEqual(info.summary(), "v2.1.0")


class TestVersionIsNotDuplicated(unittest.TestCase):
    """No current source file may hard-code the old version string."""

    STALE_PATTERNS = (
        r"v2\.0 Pro Engine",
        r"v2\.0 PRO",
        r"mycompany\.colorbot\.v2\.0",
        r"version-2\.0\.0--PRO",
    )

    STALE_FILES = (
        "main.py",
        "src/ui.py",
        "src/utils/updater.py",
        "README.md",
    )

    def test_no_stale_version_strings(self):
        for relative in self.STALE_FILES:
            text = read_text(relative)
            for pattern in self.STALE_PATTERNS:
                with self.subTest(file=relative, pattern=pattern):
                    self.assertIsNone(
                        re.search(pattern, text),
                        f"{relative} still contains {pattern!r}",
                    )

    def test_title_and_badge_come_from_helper(self):
        ui = read_text("src/ui.py")
        self.assertIn("get_version_label()", ui)
        self.assertIn("get_engine_badge()", ui)

    def test_app_user_model_id_is_stable(self):
        main_py = read_text("main.py")
        self.assertIn("mycompany.colorbot", main_py)
        self.assertNotIn("mycompany.colorbot.v2", main_py)

    def test_readme_badge_matches_version_json(self):
        readme = read_text("README.md")
        self.assertIn("version-2.1.0--PRO", readme)
        self.assertNotIn("version-2.0.0--PRO", readme)

    def test_changelog_has_current_entry(self):
        changelog = read_text("CHANGELOG.md")
        self.assertIn("## [v2.1.0]", changelog)
        # History must be preserved, not replaced.
        self.assertIn("## [v2.0.0]", changelog)
        self.assertIn("## [v1.2.1]", changelog)

    def test_updater_uses_single_source(self):
        updater = read_text("src/utils/updater.py")
        self.assertIn("from src.version import get_version", updater)

    def test_window_title_matches_helper(self):
        version_module.reset_cache()
        self.assertEqual(get_window_title(), f"CVM colorBot {get_version_label()}")
        self.assertIn(get_version(), get_window_title())

    def test_current_version_is_2_1_0(self):
        self.assertEqual(get_version(), "2.1.0")
        self.assertEqual(get_engine_badge(), "v2.1.0 \u00b7 Flick V2")


if __name__ == "__main__":
    unittest.main()
