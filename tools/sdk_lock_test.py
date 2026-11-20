import copy
import json
from pathlib import Path
import tempfile
import unittest

from tools import sdk_lock


class SdkLockTests(unittest.TestCase):
    def setUp(self):
        self.document = sdk_lock.load_toolchain_lock()
        self.lock = sdk_lock.load_sdk_lock()

    def write_lock(self, document):
        temporary = tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".json", delete=False
        )
        self.addCleanup(lambda: Path(temporary.name).unlink(missing_ok=True))
        with temporary:
            json.dump(document, temporary)
        return temporary.name

    def test_repository_lock_is_self_consistent(self):
        self.assertEqual(
            self.lock.source_archive_name,
            "ReXGlue-a3e1d82-corresponding-source.zip",
        )
        self.assertEqual(
            self.lock.source_url,
            "https://github.com/rexglue/rexglue-sdk.git",
        )
        self.assertIn(self.lock.release_tag, self.lock.url)
        self.assertTrue(self.lock.url.endswith("/" + self.lock.asset_name))
        dependencies = {
            dependency.name: dependency
            for dependency in sdk_lock.load_sdk_source_dependencies()
        }
        self.assertEqual(
            dependencies["vulkan_headers"].commit,
            "9fbc2a782ee3f8a4db64e7d991e23da75e893f44",
        )
        self.assertEqual(
            dependencies["vulkan_memory_allocator"].commit,
            "0f1a757da579831283413295cc7f3b47eb521c77",
        )
        setup_tools = {
            tool.name: tool for tool in sdk_lock.load_setup_tool_locks()
        }
        self.assertEqual(set(setup_tools), {
            "powershell", "python", "node", "seven_zip", "git"
        })
        self.assertEqual(setup_tools["powershell"].version, "7.7.0")
        self.assertEqual(setup_tools["python"].version, "3.14.10")
        self.assertEqual(setup_tools["node"].version, "22.23.5")
        self.assertEqual(setup_tools["seven_zip"].version, "25.01")
        self.assertEqual(setup_tools["git"].version, "2.56.1")

    def test_rejects_version_commit_mismatch(self):
        document = copy.deepcopy(self.document)
        document["sdk"]["version"] = "0.10.0.24-dev.g1234567"
        with self.assertRaisesRegex(ValueError, "version does not identify"):
            sdk_lock.load_sdk_lock(self.write_lock(document))

    def test_rejects_release_url_mismatch(self):
        document = copy.deepcopy(self.document)
        document["sdk"]["url"] = "https://example.com/" + self.lock.asset_name
        with self.assertRaisesRegex(ValueError, "GitHub release asset"):
            sdk_lock.load_sdk_lock(self.write_lock(document))

    def test_rejects_source_dependency_outside_thirdparty(self):
        document = copy.deepcopy(self.document)
        document["sdk_source_dependencies"]["vulkan_headers"]["path"] = "../headers"
        with self.assertRaisesRegex(ValueError, "below thirdparty"):
            sdk_lock.load_sdk_source_dependencies(self.write_lock(document))

    def test_rejects_unpinned_source_dependency(self):
        document = copy.deepcopy(self.document)
        document["sdk_source_dependencies"]["vulkan_headers"]["commit"] = "main"
        with self.assertRaisesRegex(ValueError, "full lowercase Git commit"):
            sdk_lock.load_sdk_source_dependencies(self.write_lock(document))

    def test_rejects_incomplete_setup_tools(self):
        document = copy.deepcopy(self.document)
        del document["setup_tools"]["node"]
        with self.assertRaisesRegex(ValueError, "must pin"):
            sdk_lock.load_setup_tool_locks(self.write_lock(document))

    def test_rejects_setup_tool_url_name_mismatch(self):
        document = copy.deepcopy(self.document)
        document["setup_tools"]["python"]["url"] = (
            "https://www.python.org/ftp/python/3.14.10/wrong.zip"
        )
        with self.assertRaisesRegex(ValueError, "HTTPS archive"):
            sdk_lock.load_setup_tool_locks(self.write_lock(document))

    def test_rejects_unsafe_setup_tool_path(self):
        document = copy.deepcopy(self.document)
        document["setup_tools"]["node"]["executable"] = "../node.exe"
        with self.assertRaisesRegex(ValueError, "must be relative"):
            sdk_lock.load_setup_tool_locks(self.write_lock(document))

    def test_accepts_stable_release_naming(self):
        document = copy.deepcopy(self.document)
        record = document["sdk"]
        record["version"] = "0.11.0"
        record["release_tag"] = "v0.11.0"
        record["asset_name"] = "rexglue-sdk-0.11.0-win-amd64.zip"
        record["url"] = (
            "https://github.com/rexglue/rexglue-sdk/releases/download/"
            f"{record['release_tag']}/{record['asset_name']}"
        )
        lock = sdk_lock.load_sdk_lock(self.write_lock(document))
        self.assertEqual(lock.release_tag, "v0.11.0")

    def test_latest_release_must_match_every_locked_field(self):
        releases = [
            {
                "draft": False,
                "prerelease": False,
                "published_at": "2026-11-14T20:45:02Z",
                "tag_name": self.lock.release_tag,
                "target_commitish": "main",
                "resolved_commit": self.lock.commit,
                "assets": [
                    {
                        "name": self.lock.asset_name,
                        "browser_download_url": self.lock.url,
                        "digest": "sha256:" + self.lock.sha256,
                    }
                ],
            }
        ]
        self.assertEqual(
            sdk_lock.verify_latest_release(self.lock, releases),
            "2026-11-14T20:45:02Z",
        )
        releases[0]["assets"][0]["digest"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(ValueError, "not the latest"):
            sdk_lock.verify_latest_release(self.lock, releases)

    def test_newer_windows_release_is_not_hidden_by_other_assets(self):
        exact = {
            "draft": False,
            "prerelease": False,
            "published_at": "2026-11-14T20:45:02Z",
            "tag_name": self.lock.release_tag,
            "target_commitish": "main",
            "resolved_commit": self.lock.commit,
            "assets": [
                {
                    "name": self.lock.asset_name,
                    "browser_download_url": self.lock.url,
                    "digest": "sha256:" + self.lock.sha256,
                }
            ],
        }
        newer = copy.deepcopy(exact)
        newer["published_at"] = "2026-11-15T00:00:00Z"
        newer["tag_name"] = "v0.12.0"
        with self.assertRaisesRegex(ValueError, "release_tag"):
            sdk_lock.verify_latest_release(self.lock, [exact, newer])

    def test_stable_pin_ignores_newer_nightly(self):
        stable = {
            "draft": False,
            "prerelease": False,
            "published_at": "2026-11-14T20:45:02Z",
            "tag_name": self.lock.release_tag,
            "target_commitish": "main",
            "resolved_commit": self.lock.commit,
            "assets": [
                {
                    "name": self.lock.asset_name,
                    "browser_download_url": self.lock.url,
                    "digest": "sha256:" + self.lock.sha256,
                }
            ],
        }
        nightly = copy.deepcopy(stable)
        nightly["published_at"] = "2026-11-17T00:00:00Z"
        nightly["tag_name"] = "nightly-20261117-115171b4"
        nightly["assets"][0]["name"] = (
            "rexglue-sdk-0.11.0.13-dev.g115171b-win-amd64.zip"
        )
        self.assertEqual(
            sdk_lock.verify_latest_release(self.lock, [stable, nightly]),
            stable["published_at"],
        )


if __name__ == "__main__":
    unittest.main()
