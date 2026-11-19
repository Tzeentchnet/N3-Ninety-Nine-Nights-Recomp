"""Verify that toolchain.lock.json pins GitHub's latest ReXGlue Windows SDK."""

import json
import os
import urllib.error
import urllib.request

from sdk_lock import load_sdk_lock, verify_latest_release


API = "https://api.github.com/repos/rexglue/rexglue-sdk/releases?per_page=100"
TAG_API = "https://api.github.com/repos/rexglue/rexglue-sdk/git/ref/tags/"


def main():
    lock = load_sdk_lock()
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "N3-sdk-audit",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(API, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            releases = json.load(response)
    except (OSError, urllib.error.HTTPError, json.JSONDecodeError) as error:
        raise RuntimeError(f"ReXGlue release lookup failed: {error}") from error
    if not isinstance(releases, list):
        raise RuntimeError("ReXGlue release lookup returned an unexpected document")
    for release in releases:
        if release.get("tag_name") != lock.release_tag:
            continue
        tag_request = urllib.request.Request(
            TAG_API + lock.release_tag, headers=headers
        )
        try:
            with urllib.request.urlopen(tag_request, timeout=60) as response:
                tag = json.load(response)
        except (OSError, urllib.error.HTTPError, json.JSONDecodeError) as error:
            raise RuntimeError(f"ReXGlue tag lookup failed: {error}") from error
        target = tag.get("object", {})
        if target.get("type") != "commit" or not target.get("sha"):
            raise RuntimeError("ReXGlue release tag is not a lightweight commit tag")
        release["resolved_commit"] = target["sha"]
        break
    published = verify_latest_release(lock, releases)
    print(
        f"Latest ReXGlue Windows SDK verified: {lock.version} "
        f"({lock.commit}) published {published}"
    )


if __name__ == "__main__":
    main()
