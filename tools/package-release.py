"""Create an allowlisted Windows release ZIP; exclude local game and build data."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import zipfile

from sdk_lock import load_sdk_lock, load_sdk_source_dependencies

ROOT = Path(__file__).resolve().parent.parent
SDK = load_sdk_lock()
SDK_SOURCE_DEPENDENCIES = load_sdk_source_dependencies()
PACKAGE_DOCUMENTS = {
    "LICENSE.txt": ROOT / "LICENSE",
    "README.txt": ROOT / "docs/releases/PACKAGE-README.txt",
    "THIRD_PARTY.md": ROOT / "THIRD_PARTY.md",
    "licenses/AMD-FidelityFX-FSR1.txt": ROOT / "LICENSES/AMD-FidelityFX-FSR1.txt",
}
PACKAGE_BINARIES = (
    "n3.exe",
    "n3_import.exe",
    "SDL3.dll",
    "rexapp.dll",
    "rexapu.dll",
    "rexapu-sdl3.dll",
    "rexbase.dll",
    "rexfilesystem.dll",
    "rexgpu.dll",
    "rexgpu-xenos-d3d12.dll",
    "rexgpu-xenos-null.dll",
    "rexgpu-xenos-vulkan.dll",
    "rexhid.dll",
    "rexhid-sdl3.dll",
    "rexhid-xinput.dll",
    "rexkernel.dll",
    "rexppc.dll",
    "rexui.dll",
    "rexui-sdl3.dll",
    "rexxam.dll",
    "rexxbdm.dll",
    "TracyClient.dll",
)


def zip_entry(archive, name, data):
    entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    entry.create_system = 0
    entry.external_attr = 32
    entry.compress_type = zipfile.ZIP_DEFLATED
    archive.writestr(entry, data)


def contains_identifier(data, identifier, token_boundaries=False):
    haystack = data.lower()
    for spelling in {identifier, identifier.replace("\\", "/")}:
        for encoding, width in (("utf-8", 1), ("utf-16le", 2)):
            needle = spelling.lower().encode(encoding)
            offset = 0
            while (index := haystack.find(needle, offset)) >= 0:
                if not token_boundaries:
                    return True
                before = haystack[max(0, index - width):index]
                after = haystack[index + len(needle):index + len(needle) + width]

                def is_word_unit(unit):
                    return (
                        len(unit) == width
                        and (width == 1 or unit[1] == 0)
                        and (
                            ord("0") <= unit[0] <= ord("9")
                            or ord("a") <= unit[0] <= ord("z")
                            or unit[0] == ord("_")
                        )
                    )

                if not is_word_unit(before) and not is_word_unit(after):
                    return True
                offset = index + 1
    return False


def check_binary(name, data):
    # Inspect both narrow and wide strings without putting identifiers in output.
    identifiers = [
        (str(ROOT), False),
        (str(Path.home()), False),
        (os.environ.get("USERNAME", ""), True),
    ]
    for identifier, token_boundaries in identifiers:
        if len(identifier) < 4:
            continue
        if contains_identifier(data, identifier, token_boundaries):
            raise ValueError(f"Build-machine identifier found in {name}")
    if re.search(rb"(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|sk-proj-[A-Za-z0-9_-]{30,})", data):
        raise ValueError(f"Credential-like string found in {name}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+(?:-[a-z0-9.]+)?", args.version):
        raise ValueError("Invalid release version")
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT).strip():
        raise ValueError("Commit source changes before packaging")
    build = ROOT / "out/build/win-amd64-release"
    release = ROOT / "out/release"
    release.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools/bundle-sdk-source.py"), "--if-needed"],
        cwd=ROOT,
    )
    if result.returncode != 0:
        raise ValueError("Pinned SDK source preparation failed")
    sources = release / SDK.source_archive_name
    if not sources.is_file():
        raise ValueError("Run bundle-sdk-source.py first")
    files = {name: (build / name).read_bytes() for name in PACKAGE_BINARIES}
    # Only the release x64 CRT directory from the official tool download is used.
    crt_packages = sorted((ROOT / ".tools/downloads").glob("Microsoft.VC.*.CRT.Redist.X64.base.vsix"))
    if len(crt_packages) != 1:
        raise ValueError("Expected one Microsoft x64 CRT redistributable archive")
    with zipfile.ZipFile(crt_packages[0]) as crt:
        for name in crt.namelist():
            if "/x64/Microsoft.VC143.CRT/" in name and name.endswith(".dll") and "/debug_nonredist/" not in name:
                files[PurePosixPath(name).name] = crt.read(name)
    for required in ["msvcp140.dll", "msvcp140_atomic_wait.dll", "vcruntime140.dll", "vcruntime140_1.dll"]:
        if required not in files:
            raise ValueError("Missing release C/C++ runtime")
    for name, data in files.items():
        check_binary(name, data)
    for name, path in PACKAGE_DOCUMENTS.items():
        files[name] = path.read_bytes()
    files["supported-game.json"] = (ROOT / "docs/game-build.json").read_bytes()
    # Preserve all separately supplied upstream notices, including nested libraries.
    with zipfile.ZipFile(sources) as source:
        for name in source.namelist():
            path = PurePosixPath(name)
            if path.name.lower().startswith(("license", "copying", "notice", "copyright", "authors")):
                files["licenses/" + name] = source.read(name)
        # Small vendored libraries keep notices in source headers instead.
        prefixes = ["rexglue-sdk/thirdparty/" + name + "/" for name in
                    ["crypto", "disasm", "disruptorplus", "dxbc", "dxc", "pe", "renderdoc", "stb", "tiny-aes-c"]]
        for name in source.namelist():
            if any(name.startswith(prefix) for prefix in prefixes) and name.endswith((".h", ".hpp", ".c", ".cpp")):
                data = source.read(name)
                if b"license" in data.lower() or b"copyright" in data.lower():
                    files["licenses/embedded-notices/" + name] = data
    files["licenses/Microsoft-runtime.txt"] = b"""Microsoft Visual C++ runtime 14.44, release x64.
Copyright (c) Microsoft Corporation. All rights reserved.
Distributed as application-local runtime dependencies under the applicable
Microsoft Visual Studio license terms and distributable-code list:
https://visualstudio.microsoft.com/license-terms/
https://learn.microsoft.com/visualstudio/releases/2022/redistribution
https://learn.microsoft.com/cpp/windows/redistributing-visual-cpp-files
No Microsoft development tools or debug runtimes are included.
"""
    hashes = {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())}
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    manifest = {
        "version": args.version,
        "platform": "Windows x64",
        "sourceCommit": commit,
        "sdk": {
            "version": SDK.version,
            "commit": SDK.commit,
            "releaseTag": SDK.release_tag,
            "binaryArchiveSha256": SDK.sha256,
            "sourceDependencies": {
                dependency.name: {
                    "path": dependency.path,
                    "url": dependency.url,
                    "commit": dependency.commit,
                }
                for dependency in SDK_SOURCE_DEPENDENCIES
            },
            "patches": {
                path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted((ROOT / "tools/rexglue/patches").glob("*.patch"))
            },
        },
        "files": hashes,
        "sdkSourceArchive": sources.name,
        "sdkSourceSha256": hashlib.sha256(sources.read_bytes()).hexdigest(),
    }
    files["release-manifest.json"] = json.dumps(manifest, indent=2).encode()
    destination = release / f"N3-Recompiled-{args.version}-windows-x64.zip"
    with zipfile.ZipFile(destination, "w", compresslevel=9) as archive:
        for name, data in sorted(files.items()):
            zip_entry(archive, name, data)
    checksums = "".join(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n" for path in [destination, sources])
    (release / "SHA256SUMS.txt").write_text(checksums, encoding="ascii")
    print(f"Packaged {len(files)} allowlisted files: {destination.name} ({destination.stat().st_size} bytes)")
    print("Binary identifier scan passed; no game files, profiles, logs, PDBs, or images admitted")


if __name__ == "__main__":
    main()
