import unittest
import sys
import os
try:
    import customtkinter as ctk
except Exception:
    ctk = None

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class TestUIComponents(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import _tkinter
            from unittest.mock import MagicMock
            if ctk is None or isinstance(_tkinter, MagicMock) or not hasattr(_tkinter, "__file__"):
                raise unittest.SkipTest("real tkinter unavailable")
            ctk.set_appearance_mode("Dark")
            cls.root = ctk.CTk()
            cls.root.withdraw()
            from src.ui_components import ModernCard, ModernSlider, ModernSwitch, StatusPill
            globals()["ModernCard"] = ModernCard
            globals()["ModernSlider"] = ModernSlider
            globals()["ModernSwitch"] = ModernSwitch
            globals()["StatusPill"] = StatusPill
        except Exception as exc:
            raise unittest.SkipTest(f"customtkinter unavailable: {exc}")

    @classmethod
    def tearDownClass(cls):
        try:
            cls.root.destroy()
        except Exception:
            pass

    def test_modern_card_creation(self):
        card = ModernCard(self.root, title="Targeting & FOV", icon="🎯", badge_text="Core")
        self.assertIsNotNone(card)
        self.assertEqual(card.title, "Targeting & FOV")
        self.assertIsNotNone(card.content)

    def test_modern_slider_value_change(self):
        changed_val = []
        slider = ModernSlider(
            self.root,
            label="FOV Size",
            key="fovsize",
            min_val=10,
            max_val=150,
            init_val=28,
            command=lambda v: changed_val.append(v),
            is_float=False
        )
        self.assertEqual(slider.get_value(), 28)
        slider.set_value(45)
        self.assertEqual(slider.get_value(), 45)
        self.assertIn(45, changed_val)

    def test_modern_switch(self):
        changed_switch = []
        switch = ModernSwitch(
            self.root,
            title="Recoil Immunity",
            subtitle="Suppresses Y axis recoil",
            init_val=True,
            command=lambda v: changed_switch.append(v)
        )
        self.assertTrue(switch.get_value())
        switch.set_value(False)
        self.assertFalse(switch.get_value())
        self.assertIn(False, changed_switch)

    def test_status_pill(self):
        pill = StatusPill(self.root, label="OBS UDP", value="120 FPS", dot_color="#10B981")
        self.assertEqual(pill.value_text, "120 FPS")
        pill.update_value("144 FPS", dot_color="#06B6D4")
        self.assertEqual(pill.value_text, "144 FPS")

if __name__ == "__main__":
    unittest.main()
