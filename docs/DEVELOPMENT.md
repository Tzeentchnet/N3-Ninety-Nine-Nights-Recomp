# Development and build

This guide covers a local Windows build of the maintained fork. Read
[fork relationship](FORK.md) before comparing it with upstream instructions.

## Requirements

- Windows 10/11 x64
- PowerShell 7
- Node.js 18 or newer for disc extraction
- Python 3.10 or newer for tooling
- 7-Zip for the pinned LLVM installer
- Approximately 1 GB for downloaded tools
- Approximately 5.8 GB for an extracted owned game image

Bootstrap keeps downloaded tools in `.tools/`; it does not install Visual
Studio globally. Original game data stays under ignored `private/` paths.

## Fresh checkout

```powershell
# AcceptVisualStudioLicense accepts Microsoft's development-tool license.
pwsh -NoProfile -File tools\bootstrap.ps1 `
  -AcceptVisualStudioLicense `
  -Python python

node tools\disc.mjs extract `
  "path\to\your-disc.iso" `
  private\game `
  private\disc-manifest.json

pwsh -NoProfile -File tools\build.ps1
pwsh -NoProfile -File tools\launch.ps1
```

The extractor refuses an existing destination and records a SHA-256 for every
file. Code generation verifies the supported `default.xex` before using
build-specific function hints.

To use an existing Visual Studio 2022 x64 development environment, run
`tools\bootstrap.ps1 -ToolsOnly`. Exact SDK, compiler, CMake, Ninja, URL, and
archive pins are in `tools\toolchain.lock.json`. See the
[porting roadmap](PORTING.md#sdk-and-build-baseline) for the enforced ReXGlue
identity and source-provenance flow.

## Launcher and profiles

```powershell
pwsh -NoProfile -File tools\launch.ps1
pwsh -NoProfile -File tools\launch.ps1 -DryRun -Setup
pwsh -NoProfile -File tools\launch.ps1 -Profile test
```

The default launcher uses a 1280 x 720 window, `private\game`,
`private\user`, `private\cache`, and `logs\runtime-windowed.log`.
See the [launcher guide](LAUNCHER.md) for graphics overrides, profile isolation,
native ISO/XEX setup, remembered-path reset, custom paths, and mod staging.

## Targeted checks

Run the smallest check that covers a change:

```powershell
# Disc extraction
node --test tools\disc.test.mjs

# Offline mod staging and launcher arguments
python -m unittest tools.mods_test
pwsh -NoProfile -File tools\launch_test.ps1

# SDK lock, generated CMake repair, and release packaging
python -m unittest `
  tools.sdk_lock_test `
  tools.fix_generated_cmake_test `
  tools.package_release_test
python tools\check-sdk.py

# Full native runtime/GPU build and CTest
pwsh -NoProfile -File tools\build.ps1 `
  -Configuration RelWithDebInfo `
  -Jobs 4

# Isolated startup check
pwsh -NoProfile -File tools\smoke.ps1 -Seconds 30
```

Smoke-test survival establishes startup progress only. It does not establish
correct rendering, input, performance, save compatibility, or gameplay.

## Source boundaries

- Put function-discovery hints in `n3_manifest.toml`.
- Put host/runtime fixes in `src/`.
- Regenerate translated sources; do not edit `generated/default/` manually.
- `generated/rexglue.cmake` is the only tracked generated integration file.
- Keep original game data in `private/` and downloaded tools in `.tools/`.
- Never commit profiles, caches, logs, saves, generated game translations, or
  release material copied from the game.

## Release workflow

Release packaging requires a committed source tree:

```powershell
pwsh -NoProfile -File tools\build.ps1 -Configuration Release
python tools\bundle-sdk-source.py
python tools\package-release.py --version <tag>
```

The package tool uses an explicit allowlist, includes the project and
third-party licenses, scans binaries for build-machine identifiers, records
source/SDK provenance, and writes checksums under `out/release/`.

Inspect and test the extracted package before publishing. Current naming,
release-note, and publication conventions are in
[release documentation](releases/README.md).
