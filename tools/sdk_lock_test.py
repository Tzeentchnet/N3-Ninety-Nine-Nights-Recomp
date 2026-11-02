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
            "ReXGlue-bd833a2-corresponding-source.zip",
        )
        self.assertIn(self.lock.release_tag, self.lock.url)
        self.assertTrue(self.lock.url.endswith("/" + self.lock.asset_name))

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
                "published_at": "2026-10-02T12:11:30Z",
                "tag_name": self.lock.release_tag,
                "target_commitish": self.lock.commit,
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
            "2026-10-02T12:11:30Z",
        )
        releases[0]["assets"][0]["digest"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(ValueError, "not the latest"):
            sdk_lock.verify_latest_release(self.lock, releases)

    def test_newer_windows_release_is_not_hidden_by_other_assets(self):
        exact = {
            "draft": False,
            "published_at": "2026-10-02T12:11:30Z",
            "tag_name": self.lock.release_tag,
            "target_commitish": self.lock.commit,
            "assets": [
                {
                    "name": self.lock.asset_name,
                    "browser_download_url": self.lock.url,
                    "digest": "sha256:" + self.lock.sha256,
                }
            ],
        }
        newer = copy.deepcopy(exact)
        newer["published_at"] = "2026-10-03T00:00:00Z"
        newer["tag_name"] = "nightly-newer"
        with self.assertRaisesRegex(ValueError, "release_tag"):
            sdk_lock.verify_latest_release(self.lock, [exact, newer])


if __name__ == "__main__":
    unittest.main()
