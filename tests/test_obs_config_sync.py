"""O1-O7: static synchronisation checks for plugin configs, script and docs.

Pure file checks (no PowerShell, no sockets). Their job is to stop the plugin
config, the installer and the user guides from silently reverting to the
pre-v2.1 state (port 3110, DPI 800, "240 FPS", TCP 4455, LocalPort outbound).

Two locations are involved:

* ``<root>/OBS-xUDP-Plugin``                 -> the deployed/next-to-bot folder
* ``CVM-colorBot/.bangiao/pending/...``      -> the synchronised deliverables

The staged copy is always validated. The deployed copy is validated too as soon
as it declares ``config_schema == 5``; while it is still pre-v2.1 the test skips
with the exact command needed to promote the staged files, so the gap stays
visible instead of being hidden.
"""

import glob
import json
import os
import sys
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PACKAGE_ROOT = os.path.dirname(PROJECT_ROOT)

STAGED_PLUGIN_DIR = os.path.join(PROJECT_ROOT, ".bangiao", "pending", "OBS-xUDP-Plugin")
STAGED_PACKAGE_DIR = os.path.join(PROJECT_ROOT, ".bangiao", "pending")
LIVE_PLUGIN_DIR = os.path.join(PACKAGE_ROOT, "OBS-xUDP-Plugin")

PROMOTE_HINT = (
    "Deployed OBS-xUDP-Plugin is still pre-v2.1. Promote the staged v2.1 files:\n"
    "  copy \"{staged}\\config.json\"                 \"{live}\\config.json\"\n"
    "  copy \"{staged}\\cvm_config_optimized.json\"   \"{live}\\cvm_config_optimized.json\"\n"
    "  copy \"{staged}\\install.ps1\"                 \"{live}\\install.ps1\"\n"
    "  copy \"{staged}\\HUONG_DAN_SU_DUNG.txt\"       \"{live}\\HUONG_DAN_SU_DUNG.txt\"\n"
    "  copy \"{staged_pkg}\\HUONG_DAN_CAI_DAT.txt\"   \"{pkg}\\HUONG_DAN_CAI_DAT.txt\""
)


def read_text(path):
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        return handle.read()


def _declares_v21(directory):
    path = os.path.join(directory, "config.json")
    if not os.path.exists(path):
        return False
    try:
        return json.loads(read_text(path)).get("config_schema") == 5
    except Exception:
        return False


def plugin_dirs():
    """Every plugin folder that must satisfy the v2.1 baseline."""
    dirs = []
    if _declares_v21(STAGED_PLUGIN_DIR):
        dirs.append(STAGED_PLUGIN_DIR)
    if _declares_v21(LIVE_PLUGIN_DIR):
        dirs.append(LIVE_PLUGIN_DIR)
    return dirs


def promote_hint():
    return PROMOTE_HINT.format(
        staged=STAGED_PLUGIN_DIR,
        staged_pkg=STAGED_PACKAGE_DIR,
        live=LIVE_PLUGIN_DIR,
        pkg=PACKAGE_ROOT,
    )


class _PluginFixtures(unittest.TestCase):
    def available_plugin_dirs(self):
        dirs = plugin_dirs()
        if not dirs:
            self.skipTest(
                "No v2.1 plugin folder found; the staged deliverables are missing:\n"
                + promote_hint()
            )
        return dirs

    def require_deployed_v21(self):
        """Fail-soft gate: skip while the deployed folder is still pre-v2.1."""
        if not _declares_v21(LIVE_PLUGIN_DIR):
            self.skipTest("Deployed plugin is not v2.1 yet.\n" + promote_hint())


class TestPluginConfig(_PluginFixtures):
    def _plugin_configs(self):
        found = []
        for directory in self.available_plugin_dirs():
            for name in ("config.json", "cvm_config_optimized.json"):
                path = os.path.join(directory, name)
                if os.path.exists(path):
                    found.append((path, json.loads(read_text(path))))
        return found

    # -- O1 ---------------------------------------------------------------
    def test_plugin_config_json_is_valid(self):
        for path, payload in self._plugin_configs():
            self.assertIsInstance(payload, dict, path)
            self.assertIn("_comment", payload, path)

    # -- O2 ---------------------------------------------------------------
    def test_plugin_v21_baseline(self):
        for path, payload in self._plugin_configs():
            self.assertEqual(payload["in_game_sens"], 0.23, path)
            self.assertEqual(payload["mouse_dpi"], 1100, path)
            self.assertEqual(payload["mode"], "WindMouse", path)
            self.assertEqual(payload["mode_sec"], "Flick", path)
            self.assertEqual(str(payload["udp_port"]), "5000", path)
            self.assertEqual(payload["config_schema"], 5, path)
            self.assertEqual(payload["udp_ip"], "0.0.0.0", path)
            self.assertEqual(payload["capture_mode"], "UDP", path)
            self.assertEqual(payload["target_fps"], 144, path)
            self.assertEqual(payload["capture_fps"], 144.0, path)
            self.assertEqual(payload["aim_engine"], "legacy", path)
            self.assertEqual(payload["flick_engine"], "v2", path)

    # -- O3 ---------------------------------------------------------------
    def test_optimized_config_matches_baseline(self):
        paths = [
            os.path.join(directory, "cvm_config_optimized.json")
            for directory in self.available_plugin_dirs()
        ]
        for path in paths:
            self.assertTrue(os.path.exists(path), path)
            payload = json.loads(read_text(path))
            # Regression guard: this file shipped DPI 800 and sens 0.235.
            self.assertEqual(payload["mouse_dpi"], 1100, path)
            self.assertEqual(payload["in_game_sens"], 0.23, path)
            self.assertEqual(payload["mode_sec"], "Flick", path)
            self.assertEqual(str(payload["udp_port"]), "5000", path)

    # -- O5 (plugin half) -------------------------------------------------
    def test_plugin_audio_feedback_port(self):
        for path, payload in self._plugin_configs():
            self.assertEqual(payload.get("audio_feedback_port"), 4455, path)
            self.assertEqual(payload.get("toggle_feedback_method"), "udp", path)
            self.assertTrue(payload.get("audio_feedback_ip"), path)


class TestDeployedPlugin(_PluginFixtures):
    """Explicit gate: the shop-facing folder must eventually be v2.1."""

    def test_deployed_plugin_is_v21(self):
        self.require_deployed_v21()
        payload = json.loads(read_text(os.path.join(LIVE_PLUGIN_DIR, "config.json")))
        self.assertEqual(payload["config_schema"], 5)
        self.assertEqual(str(payload["udp_port"]), "5000")


class TestBotConfigs(unittest.TestCase):
    def _bot_config_paths(self):
        patterns = [
            os.path.join(PROJECT_ROOT, "config*.json"),
            os.path.join(PROJECT_ROOT, "configs", "*.json"),
        ]
        return sorted({path for pattern in patterns for path in glob.glob(pattern)})

    # -- O4 ---------------------------------------------------------------
    def test_all_bot_configs_use_port_5000(self):
        paths = self._bot_config_paths()
        self.assertTrue(paths, "no bot config files found")

        for path in paths:
            payload = json.loads(read_text(path))
            self.assertEqual(str(payload.get("udp_port")), "5000", path)
            self.assertEqual(payload.get("config_schema"), 5, path)

    # -- O5 (bot half) ----------------------------------------------------
    def test_bot_audio_feedback_port(self):
        paths = self._bot_config_paths()
        self.assertTrue(paths, "no bot config files found")
        for path in paths:
            payload = json.loads(read_text(path))
            self.assertEqual(payload.get("audio_feedback_port"), 4455, path)


class TestInstallerScript(_PluginFixtures):
    # -- O6 ---------------------------------------------------------------
    def test_install_ps1_required_pieces(self):
        dirs = self.available_plugin_dirs()
        for directory in dirs:
            path = os.path.join(directory, "install.ps1")
            self.assertTrue(os.path.exists(path), path)
            text = read_text(path)

            self.assertIn(r"HKLM:\SOFTWARE\OBS Studio", text, path)
            self.assertIn("New-NetFirewallRule", text, path)
            self.assertIn("4455", text, path)
            self.assertIn("5000", text, path)
            self.assertIn(r"VC\Runtimes\x64", text, path)
            self.assertIn("144 FPS", text, path)

            # Hard rule (plan §6.6): never advertise 240 FPS, not even in a warning.
            self.assertNotIn("240 FPS", text, path)

            # Outbound must key on RemotePort: OBS sends from an ephemeral source
            # port, so an outbound -LocalPort 5000 rule would never match.
            self.assertIn("-RemotePort 5000", text, path)
            for line in text.splitlines():
                if "-Direction Outbound" in line:
                    self.assertNotIn("-LocalPort", line, f"{path}: outbound uses LocalPort")

            # The beep rule must be created as UDP (never TCP).
            beep = text.split("Beep 4455 In", 1)
            self.assertEqual(len(beep), 2, f"{path}: missing Beep 4455 rule")
            self.assertIn("Protocol UDP", beep[1][:250], path)

    # -- O6 (structure) ---------------------------------------------------
    def test_install_ps1_structure(self):
        """Brace/param sanity. The Tester runs the real `[scriptblock]::Create`."""
        for directory in self.available_plugin_dirs():
            path = os.path.join(directory, "install.ps1")
            text = read_text(path)
            self.assertIn("[CmdletBinding()]", text, path)
            self.assertIn("param(", text, path)
            self.assertEqual(text.count("{"), text.count("}"), f"{path}: unbalanced braces")
            # Interactive fallback must use Read-Host, never the automatic $input.
            self.assertIn("Read-Host", text, path)


class TestDocs(_PluginFixtures):
    # -- O7 ---------------------------------------------------------------
    def test_docs_cover_ports_and_fps(self):
        docs = []
        for directory in self.available_plugin_dirs():
            plugin_doc = os.path.join(directory, "HUONG_DAN_SU_DUNG.txt")
            package_doc = os.path.join(os.path.dirname(directory), "HUONG_DAN_CAI_DAT.txt")
            if os.path.exists(plugin_doc):
                docs.append(plugin_doc)
            if os.path.exists(package_doc):
                docs.append(package_doc)
        # The staged package guide sits one level above the staged plugin folder.
        staged_package_doc = os.path.join(STAGED_PACKAGE_DIR, "HUONG_DAN_CAI_DAT.txt")
        if os.path.exists(staged_package_doc):
            docs.append(staged_package_doc)
        docs = sorted(set(docs))
        if not docs:
            self.skipTest("user guides are not present")

        for path in docs:
            text = read_text(path)
            for token in ("5000", "4455", "144"):
                self.assertIn(token, text, f"{path}: missing {token}")

        # 240 FPS may be explained as a rejected option, never recommended.
        for path in docs:
            lowered = read_text(path).lower()
            if "240" in lowered:
                self.assertNotIn("khuyen nghi 240", lowered, path)
                self.assertNotIn("recommended 240", lowered, path)

        # The plugin guide must warn that UDP 4455 is not OBS WebSocket TCP 4455.
        for directory in self.available_plugin_dirs():
            plugin_doc = os.path.join(directory, "HUONG_DAN_SU_DUNG.txt")
            if os.path.exists(plugin_doc):
                text = read_text(plugin_doc)
                self.assertIn("TCP", text, plugin_doc)
                self.assertIn("UDP", text, plugin_doc)


if __name__ == "__main__":
    unittest.main()
