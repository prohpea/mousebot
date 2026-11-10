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

    def test_no_duplicate_keys_in_locales(self):
        import json
        locales_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "locales")
        for fname in ["en.json", "vi.json", "zh-CN.json"]:
            fpath = os.path.join(locales_dir, fname)
            if not os.path.exists(fpath):
                continue
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read()
            seen_keys = set()
            duplicates = []
            def check_pairs(pairs):
                for k, v in pairs:
                    if k in seen_keys:
                        duplicates.append(k)
                    seen_keys.add(k)
                return dict(pairs)
            json.loads(content, object_pairs_hook=check_pairs)
            self.assertEqual(duplicates, [], f"Found duplicate translation keys in {fname}: {duplicates}")

if __name__ == "__main__":
    unittest.main()
