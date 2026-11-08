import unittest
import sys
import os

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.utils.i18n import i18n, t

class TestI18nVietnamese(unittest.TestCase):
    def test_vietnamese_locale_registered(self):
        available = dict(i18n.available())
        self.assertIn("vi", available, "Vietnamese 'vi' language code should be registered")
        self.assertEqual(available["vi"], "Tiếng Việt")

    def test_vietnamese_translations_content(self):
        i18n.set_language("vi")
        self.assertEqual(i18n.language, "vi")
        
        # Verify core translations
        start_txt = t("START")
        self.assertIn(start_txt, ["BẮT ĐẦU", "CHẠY"], f"Unexpected translation for START: {start_txt}")
        
        self.assertEqual(t("Main Aimbot"), "Aimbot Chính")
        self.assertEqual(t("Secondary Aimbot"), "Aimbot Phụ")
        self.assertTrue("FOV" in t("FOV Size") or "Bán kính" in t("FOV Size"))
        self.assertTrue("WindMouse" in t("WindMouse Humanizer"))

        # Restore default language
        i18n.set_language("en")

if __name__ == "__main__":
    unittest.main()
