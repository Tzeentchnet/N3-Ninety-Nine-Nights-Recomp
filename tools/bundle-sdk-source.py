"""Bundle the pinned SDK and dependency sources for binary releases."""
import argparse
import concurrent.futures
import configparser
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import tarfile
import urllib.request
import zipfile

from sdk_lock import load_sdk_lock, load_sdk_source_dependencies

ROOT = Path(__file__).resolve().parent.parent
SDK = load_sdk_lock()
SDK_SOURCE_DEPENDENCIES = load_sdk_source_dependencies()
COMMIT = SDK.commit
OUT = ROOT / "out" / "release"
CACHE = ROOT / ".tools" / "source-archives"
def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "N3-release-tools"})
    with urllib.request.urlopen(req, timeout=120) as response:
        return response.read()


def snapshot(repo, commit):
    CACHE.mkdir(parents=True, exist_ok=True)
    cache = CACHE / (repo.replace("/", "-") + "-" + commit + ".tar.gz")
    url = f"https://codeload.github.com/{repo}/tar.gz/{commit}"
    if not cache.exists():
        data = fetch(url)
        temp = cache.with_suffix(".tmp")
        temp.write_bytes(data)
        temp.replace(cache)
    data = cache.read_bytes()
    return data, {"repository": f"https://github.com/{repo}", "commit": commit,
                  "archive": url, "sha256": hashlib.sha256(data).hexdigest()}


def add_snapshot(archive, data, prefix):
    # Never extract archive paths to disk. Only regular files inside one root
    # are admitted to the new source zip; symlinks and archive metadata are omitted.
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as source:
        for member in source:
            path = PurePosixPath(member.name)
            if not member.isfile() or len(path.parts) < 2:
                continue
            relative = PurePosixPath(*path.parts[1:])
            if relative.is_absolute() or ".." in relative.parts or ".git" in relative.parts:
                raise ValueError("Unsafe source archive path")
            contents = source.extractfile(member).read()
            add_file(archive, prefix + "/" + relative.as_posix(), contents)


def add_file(archive, name, data):
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    archive.writestr(info, data)


def extension_files():
    return [
        "tools/bundle-sdk-source.py",
        "tools/codegen.ps1",
        "tools/prepare-rexglue.py",
        "tools/sdk_lock.py",
        "tools/toolchain.lock.json",
        "tools/build.ps1",
        "CMakeLists.txt",
        "THIRD_PARTY.md",
        "LICENSE",
    ] + [
        path.relative_to(ROOT).as_posix()
        for path in sorted((ROOT / "tools" / "rexglue" / "patches").glob("*.patch"))
    ]


def bundle_fingerprint(files):
    digest = hashlib.sha256(b"N3 ReXGlue source bundle inputs v2\0")
    for value in vars(SDK).values():
        digest.update(value.encode())
        digest.update(b"\0")
    for dependency in SDK_SOURCE_DEPENDENCIES:
        for value in vars(dependency).values():
            digest.update(value.encode())
            digest.update(b"\0")
    for name in sorted(files):
        digest.update(name.encode())
        digest.update(b"\0")
        digest.update(hashlib.sha256((ROOT / name).read_bytes()).digest())
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--if-needed",
        action="store_true",
        help="reuse a bundle whose complete local input fingerprint still matches",
    )
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    destination = OUT / SDK.source_archive_name
    inputs = extension_files()
    fingerprint = bundle_fingerprint(inputs)
    fingerprint_file = destination.with_suffix(destination.suffix + ".inputs.sha256")
    if (
        args.if_needed
        and destination.is_file()
        and fingerprint_file.is_file()
        and fingerprint_file.read_text(encoding="ascii").strip() == fingerprint
    ):
        print(f"Pinned SDK source bundle is up to date: {destination.name}")
        return
    sdk, sdk_manifest = snapshot("rexglue/rexglue-sdk", COMMIT)
    tree = json.loads(fetch(f"https://api.github.com/repos/rexglue/rexglue-sdk/git/trees/{COMMIT}?recursive=1"))
    modules = {item["path"]: item["sha"] for item in tree["tree"] if item["type"] == "commit"}
    with tarfile.open(fileobj=io.BytesIO(sdk), mode="r:gz") as archive:
        member = next(m for m in archive if m.name.endswith("/.gitmodules"))
        config = configparser.ConfigParser()
        config.read_string(archive.extractfile(member).read().decode())
    jobs = []
    for section in config.sections():
        path = config[section]["path"]
        repo = config[section]["url"].removesuffix(".git").removeprefix("https://github.com/")
        jobs.append((path, repo, modules[path]))
    for dependency in SDK_SOURCE_DEPENDENCIES:
        repo = dependency.url.removesuffix(".git").removeprefix("https://github.com/")
        jobs.append((dependency.path, repo, dependency.commit))
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda job: (job[0], *snapshot(job[1], job[2])), jobs))
    local_manifest = {
        name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        for name in inputs
    }
    temporary_destination = destination.with_suffix(destination.suffix + ".tmp")
    with zipfile.ZipFile(temporary_destination, "w", compresslevel=6) as archive:
        add_snapshot(archive, sdk, "rexglue-sdk")
        for path, data, manifest in results:
            manifest["path"] = path
            add_snapshot(archive, data, "rexglue-sdk/" + path)
        add_file(archive, "SOURCE-MANIFEST.json", json.dumps([sdk_manifest] + [r[2] for r in results], indent=2).encode())
        add_file(archive, "SDK-LOCK.json", json.dumps(vars(SDK), indent=2).encode())
        for name in inputs:
            add_file(archive, "n3-build-metadata/" + name, (ROOT / name).read_bytes())
        add_file(archive, "n3-build-metadata/SHA256.json", json.dumps(local_manifest, indent=2).encode())
        readme = f"""Corresponding source for the modular ReXGlue SDK libraries.
SDK version {SDK.version}; base commit {SDK.commit}; upstream sources preserved.
Every SDK submodule and the pinned Vulkan headers and VMA sources are included.
The released D3D12, Vulkan, null, UI, input, audio and filesystem modules are
built from that stable source plus the N3 patches under
n3-build-metadata/tools/rexglue/patches/. N3's lock and integration build files
are under n3-build-metadata/, with hashes in SHA256.json. License texts and
build scripts are preserved in each source directory. No game material is
included. FFmpeg and libmspack are LGPL components; see their COPYING files.

Rebuilding: consult rexglue-sdk/README.md and CMakePresets.json. On Windows use
Clang 20+ and VS 2022 x64 tools. Initialize a local Git repository in each of
the included thirdparty submodule directories (git init) to satisfy the SDK's
source checkout presence checks. From rexglue-sdk/, apply the patches in lexical
order with `git apply --ignore-space-change <patch>`, then build the Release
configuration. FFmpeg is built by the SDK's supplied CMake scripts. Compatible
rebuilt modular DLLs may replace the supplied libraries. This application does
not restrict their replacement. Reverse engineering for debugging modifications
to LGPL components is permitted. The project's own source is available at the
matching GitHub tag; recompiling the game translation requires a matching
executable from your disc.

Build recipe used by the prebuilt SDK is preserved in
rexglue-sdk/.github/workflows/build-win-amd64.yaml,
rexglue-sdk/.github/workflows/_build-platform.yaml and their referenced scripts.
SOURCE-MANIFEST.json records source URLs, commit IDs, and archive SHA-256 values.
SDK-LOCK.json records the exact stable SDK base and source dependencies.
"""
        add_file(archive, "README.txt", readme.encode())
    temporary_destination.replace(destination)
    temporary = fingerprint_file.with_suffix(fingerprint_file.suffix + ".tmp")
    temporary.write_text(fingerprint + "\n", encoding="ascii")
    temporary.replace(fingerprint_file)
    print(f"Bundled SDK and {len(results)} dependencies: {destination.name} ({destination.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
