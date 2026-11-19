"""Prepare the exact patched ReXGlue source tree used by N3 builds."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys

from sdk_lock import load_sdk_lock, load_sdk_source_dependencies


ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / ".tools"
SOURCE = TOOLS / "rexglue-source"
STAGING = TOOLS / "rexglue-source.installing"
BACKUP = TOOLS / "rexglue-source.previous"
PATCH_DIR = ROOT / "tools" / "rexglue" / "patches"
MARKER_NAME = ".n3-rexglue-source.json"
MARKER_SCHEMA = 1


def run_git(arguments, cwd=None, input_bytes=None):
    command = ["git", "-c", "core.autocrlf=false", *map(str, arguments)]
    result = subprocess.run(
        command,
        cwd=cwd,
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout = result.stdout.decode("utf-8", errors="replace")
    stderr = result.stderr.decode("utf-8", errors="replace")
    if result.returncode:
        detail = stderr.strip() or stdout.strip()
        raise RuntimeError(f"{' '.join(command)} failed: {detail}")
    return stdout


def patch_files():
    patches = tuple(sorted(PATCH_DIR.glob("*.patch")))
    if not patches:
        raise RuntimeError(f"No ReXGlue patches found below {PATCH_DIR}")
    return patches


def hash_files(paths):
    digest = hashlib.sha256(b"N3 ReXGlue patch set v1\0")
    for path in paths:
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def hash_text(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def remove_readonly(func, path, exc_info):
    if not isinstance(exc_info[1], PermissionError):
        raise exc_info[1]
    os.chmod(path, os.stat(path).st_mode | stat.S_IWRITE)
    func(path)


def remove_tool_directory(path):
    if path.parent.resolve() != TOOLS.resolve() or path.name not in {
        SOURCE.name,
        STAGING.name,
        BACKUP.name,
    }:
        raise RuntimeError(f"Refusing to remove unexpected path: {path}")
    if path.exists():
        if path.is_symlink() or not path.is_dir():
            raise RuntimeError(f"Refusing to remove non-directory tool path: {path}")
        shutil.rmtree(path, onerror=remove_readonly)


def clone_at_commit(url, commit, destination):
    run_git(["clone", "--filter=blob:none", "--no-checkout", url, destination])
    run_git(["config", "core.autocrlf", "false"], destination)
    run_git(["checkout", "--detach", commit], destination)
    observed = run_git(["rev-parse", "HEAD"], destination).strip()
    if observed != commit:
        raise RuntimeError(
            f"Repository {url} resolved to {observed}, expected {commit}"
        )


def source_state(path):
    submodule_status = run_git(["submodule", "status", "--recursive"], path)
    bad_submodules = [
        line for line in submodule_status.splitlines() if line[:1] in {"-", "+", "U"}
    ]
    if bad_submodules:
        raise RuntimeError(
            "ReXGlue submodules are missing or do not match the pinned commits:\n"
            + "\n".join(bad_submodules)
        )
    dependencies = load_sdk_source_dependencies()
    dependency_state = []
    for dependency in dependencies:
        dependency_path = path / Path(dependency.path)
        if not dependency_path.is_dir():
            raise RuntimeError(f"Missing SDK source dependency: {dependency.path}")
        head = run_git(["rev-parse", "HEAD"], dependency_path).strip()
        if head != dependency.commit:
            raise RuntimeError(
                f"{dependency.path} is at {head}, expected {dependency.commit}"
            )
        status = run_git(
            ["status", "--porcelain", "--untracked-files=normal"], dependency_path
        ).strip()
        if status:
            raise RuntimeError(f"SDK source dependency is modified: {dependency.path}")
        dependency_state.append(
            {
                "name": dependency.name,
                "path": dependency.path,
                "url": dependency.url,
                "commit": dependency.commit,
            }
        )
    status = run_git(["status", "--porcelain", "--untracked-files=normal"], path)
    allowed_untracked = {
        f"?? {MARKER_NAME}",
        *(f"?? {dependency.path}/" for dependency in dependencies),
    }
    unexpected = [
        line for line in status.splitlines() if line.startswith("?? ") and line not in allowed_untracked
    ]
    if unexpected:
        raise RuntimeError(
            "ReXGlue source contains unexpected untracked paths:\n"
            + "\n".join(unexpected)
        )
    diff = run_git(["diff", "--binary", "--no-ext-diff", "HEAD", "--"], path)
    return {
        "sourceDiffSha256": hash_text(diff),
        "submoduleStatusSha256": hash_text(submodule_status),
        "dependencies": dependency_state,
    }


def expected_marker(path):
    sdk = load_sdk_lock()
    state = source_state(path)
    return {
        "schema": MARKER_SCHEMA,
        "version": sdk.version,
        "commit": sdk.commit,
        "sourceUrl": sdk.source_url,
        "patchSha256": hash_files(patch_files()),
        **state,
    }


def check_source(path=SOURCE):
    marker_path = path / MARKER_NAME
    if not marker_path.is_file():
        raise RuntimeError(f"Prepared ReXGlue marker is missing: {marker_path}")
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Cannot read prepared ReXGlue marker: {error}") from error
    sdk = load_sdk_lock()
    head = run_git(["rev-parse", "HEAD"], path).strip()
    if head != sdk.commit:
        raise RuntimeError(f"Prepared ReXGlue is at {head}, expected {sdk.commit}")
    expected = expected_marker(path)
    if marker != expected:
        raise RuntimeError(
            "Prepared ReXGlue source does not match its lock or patch set; "
            "run tools/bootstrap.ps1."
        )
    return marker


def prepare_source():
    sdk = load_sdk_lock()
    dependencies = load_sdk_source_dependencies()
    remove_tool_directory(STAGING)
    print(f"Preparing ReXGlue {sdk.version} source at {sdk.commit}")
    try:
        clone_at_commit(sdk.source_url, sdk.commit, STAGING)
        run_git(["submodule", "update", "--init", "--recursive", "--jobs", "4"], STAGING)
        for dependency in dependencies:
            print(f"Preparing {dependency.name} at {dependency.commit}")
            clone_at_commit(
                dependency.url,
                dependency.commit,
                STAGING / Path(dependency.path),
            )
        for patch in patch_files():
            print(f"Applying {patch.name}")
            run_git(
                [
                    "apply",
                    "--ignore-space-change",
                    "--ignore-whitespace",
                    "-",
                ],
                STAGING,
                patch.read_bytes().replace(b"\r\n", b"\n"),
            )
        marker = expected_marker(STAGING)
        (STAGING / MARKER_NAME).write_text(
            json.dumps(marker, indent=2) + "\n", encoding="utf-8"
        )
        check_source(STAGING)
        remove_tool_directory(BACKUP)
        if SOURCE.exists():
            SOURCE.replace(BACKUP)
        STAGING.replace(SOURCE)
        remove_tool_directory(BACKUP)
    except Exception:
        remove_tool_directory(STAGING)
        if not SOURCE.exists() and BACKUP.exists():
            BACKUP.replace(SOURCE)
        raise
    print(f"Prepared patched ReXGlue source: {SOURCE}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the prepared tree without downloading or changing it",
    )
    args = parser.parse_args()
    if args.check:
        check_source()
        print(f"Prepared patched ReXGlue source verified: {SOURCE}")
        return
    try:
        check_source()
    except (OSError, RuntimeError, ValueError):
        prepare_source()
    else:
        print(f"Prepared patched ReXGlue source is current: {SOURCE}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
