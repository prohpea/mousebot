import unittest

from src.utils.mouse.keycodes import to_hid_code, to_key_token, to_vk_code


class KeycodeConversionTests(unittest.TestCase):
    def test_letters_convert_between_names_vk_and_hid(self):
        self.assertEqual(to_vk_code("a"), 0x41)
        self.assertEqual(to_vk_code("VK:0x41"), 0x41)
        self.assertEqual(to_vk_code("HID:4"), 0x41)
        self.assertEqual(to_hid_code("A"), 4)
        self.assertEqual(to_hid_code("VK:65"), 4)

    def test_numeric_and_prefixed_inputs(self):
        self.assertEqual(to_vk_code(65), 65)
        self.assertEqual(to_vk_code("0x41"), 0x41)
        self.assertEqual(to_hid_code("HID:4"), 4)

    def test_aliases_and_unknown_values(self):
        self.assertEqual(to_vk_code("esc"), 0x1B)
        self.assertEqual(to_vk_code("ctrl"), 0x11)
        self.assertEqual(to_key_token("a"), "KEY_A")
        self.assertEqual(to_key_token("VK:65"), "65")
        self.assertIsNone(to_vk_code("not-a-key"))
        self.assertIsNone(to_vk_code(True))


if __name__ == "__main__":
    unittest.main()
