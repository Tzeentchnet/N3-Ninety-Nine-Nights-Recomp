"""Validate and expose the repository's pinned ReXGlue SDK metadata."""

from dataclasses import dataclass
import json
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parent.parent
LOCK_PATH = ROOT / "tools" / "toolchain.lock.json"


@dataclass(frozen=True)
class SdkLock:
    version: str
    commit: str
    release_tag: str
    asset_name: str
    url: str
    sha256: str

    @property
    def source_archive_name(self):
        return f"ReXGlue-{self.commit[:7]}-corresponding-source.zip"


def load_toolchain_lock(path=LOCK_PATH):
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Cannot read toolchain lock {path}: {error}") from error
    if not isinstance(document, dict):
        raise ValueError("Toolchain lock root must be an object")
    return document


def load_sdk_lock(path=LOCK_PATH):
    document = load_toolchain_lock(path)
    try:
        record = document["sdk"]
        lock = SdkLock(
            version=record["version"],
            commit=record["commit"],
            release_tag=record["release_tag"],
            asset_name=record["asset_name"],
            url=record["url"],
            sha256=record["sha256"],
        )
    except (KeyError, TypeError) as error:
        raise ValueError(f"Toolchain lock has incomplete SDK metadata: {error}") from error
    if not all(isinstance(value, str) and value for value in vars(lock).values()):
        raise ValueError("Every SDK lock field must be a nonempty string")
    if not re.fullmatch(r"[0-9a-f]{40}", lock.commit):
        raise ValueError("SDK commit must be a full lowercase Git commit")
    if not re.fullmatch(r"[0-9a-f]{64}", lock.sha256):
        raise ValueError("SDK SHA-256 must be a lowercase hexadecimal digest")
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:\.[0-9]+-dev\.g[0-9a-f]{7})?", lock.version):
        raise ValueError("SDK version has an unsupported format")
    if "-dev." in lock.version:
        if not lock.version.endswith("-dev.g" + lock.commit[:7]):
            raise ValueError("SDK version does not identify the pinned commit")
        if not lock.release_tag.endswith("-" + lock.commit[:8]):
            raise ValueError("SDK release tag does not identify the pinned commit")
    elif lock.release_tag != "v" + lock.version:
        raise ValueError("Stable SDK release tag does not match its version")
    expected_asset = f"rexglue-sdk-{lock.version}-win-amd64.zip"
    if lock.asset_name != expected_asset:
        raise ValueError(f"SDK asset must be named {expected_asset}")
    parsed = urlsplit(lock.url)
    path_parts = unquote(parsed.path).strip("/").split("/")
    expected_path = [
        "rexglue",
        "rexglue-sdk",
        "releases",
        "download",
        lock.release_tag,
        lock.asset_name,
    ]
    if parsed.scheme != "https" or parsed.hostname != "github.com" or path_parts != expected_path:
        raise ValueError("SDK URL does not match the pinned GitHub release asset")
    return lock


def verify_latest_release(lock, releases):
    candidates = []
    for release in releases:
        if not isinstance(release, dict) or release.get("draft"):
            continue
        for asset in release.get("assets", []):
            name = asset.get("name", "")
            if name.endswith("-win-amd64.zip"):
                candidates.append((release, asset))
    if not candidates:
        raise ValueError("GitHub returned no published Windows AMD64 SDK assets")
    release, asset = max(candidates, key=lambda item: item[0].get("published_at", ""))
    digest = asset.get("digest", "")
    observed = {
        "release_tag": release.get("tag_name"),
        "commit": release.get("target_commitish"),
        "asset_name": asset.get("name"),
        "url": asset.get("browser_download_url"),
        "sha256": digest.removeprefix("sha256:"),
    }
    expected = {
        "release_tag": lock.release_tag,
        "commit": lock.commit,
        "asset_name": lock.asset_name,
        "url": lock.url,
        "sha256": lock.sha256,
    }
    mismatches = [
        f"{name}: lock={expected[name]!r}, latest={observed[name]!r}"
        for name in expected
        if expected[name] != observed[name]
    ]
    if mismatches:
        raise ValueError("Pinned SDK is not the latest published Windows asset:\n" + "\n".join(mismatches))
    return release.get("published_at")
