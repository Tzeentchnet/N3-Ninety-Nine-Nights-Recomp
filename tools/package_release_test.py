import importlib.util
import os
from pathlib import Path
import sys
import unittest
from unittest import mock


TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
SPEC = importlib.util.spec_from_file_location(
    "n3_package_release", TOOLS / "package-release.py"
)
package_release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(package_release)


class PackageReleaseTests(unittest.TestCase):
    def test_username_substring_inside_symbol_is_allowed(self):
        with mock.patch.dict(os.environ, {"USERNAME": "KENP"}):
            package_release.check_binary(
                "runtime.dll",
                b"AdjustTokenPrivileges\x00LookupPrivilegeValueW",
            )

    def test_standalone_username_is_rejected(self):
        with mock.patch.dict(os.environ, {"USERNAME": "KENP"}):
            with self.assertRaisesRegex(ValueError, "Build-machine identifier"):
                package_release.check_binary("runtime.dll", b"owner=KENP;")

    def test_wide_username_path_component_is_rejected(self):
        with mock.patch.dict(os.environ, {"USERNAME": "KENP"}):
            with self.assertRaisesRegex(ValueError, "Build-machine identifier"):
                package_release.check_binary(
                    "runtime.dll",
                    "C:\\Users\\KENP\\build".encode("utf-16le"),
                )


if __name__ == "__main__":
    unittest.main()
