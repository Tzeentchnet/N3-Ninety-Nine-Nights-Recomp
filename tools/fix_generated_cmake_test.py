import unittest

from tools import fix_generated_cmake


class GeneratedCMakeFixTests(unittest.TestCase):
    def test_patches_official_block_and_is_idempotent(self):
        original = "prefix\n" + fix_generated_cmake.OFFICIAL_OUTPUTS + "\nsuffix\n"
        patched = fix_generated_cmake.patch_text(original)
        self.assertNotIn(fix_generated_cmake.OFFICIAL_OUTPUTS, patched)
        self.assertIn(fix_generated_cmake.N3_OUTPUTS, patched)
        self.assertEqual(fix_generated_cmake.patch_text(patched), patched)

    def test_rejects_template_drift(self):
        with self.assertRaisesRegex(ValueError, "no longer matches"):
            fix_generated_cmake.patch_text("unrelated generated file")

    def test_rejects_duplicate_blocks(self):
        duplicated = fix_generated_cmake.OFFICIAL_OUTPUTS * 2
        with self.assertRaisesRegex(ValueError, "no longer matches"):
            fix_generated_cmake.patch_text(duplicated)


if __name__ == "__main__":
    unittest.main()
