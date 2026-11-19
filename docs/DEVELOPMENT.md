# Development and build

This guide covers a local Windows build of the maintained fork. Read
[fork relationship](FORK.md) before comparing it with upstream instructions.

## Requirements

- Windows 10/11 x64
- PowerShell 7
- Node.js 18 or newer for disc extraction
- Python 3.10 or newer for tooling
- 7-Zip for the pinned LLVM installer
- Several GB for downloaded tools, pinned SDK sources, and native build outputs
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

`tools\build.ps1` uses the pinned binary SDK for code generation, then builds
the modular runtime and D3D12, Vulkan, and null Xenos drivers from the exact
stable source under `.tools\rexglue-source`. Bootstrap verifies ReXGlue
`v0.11.0` commit `a3e1d82678ca20d68d4837a8e9ee4652ff073745`, prepares every
submodule, pins Vulkan-Headers and Vulkan Memory Allocator, and applies the
small patches under `tools\rexglue\patches`.

ReXGlue 0.11 removed the earlier presentation-effect API. Patch `0005` restores
the vendor-neutral spatial FSR1 EASU+RCAS path from the last upstream parent
before that removal, adapted to the v0.11 D3D12 and Vulkan presenters. The base
remains pinned to stable v0.11.0 rather than downgrading the runtime. Generated
shader headers and AMD's MIT notice are tracked so the prepared source does not
depend on an older checkout.

No modern temporal FidelityFX or NVIDIA DLSS SDK is bundled. FSR4 and DLSS
Super Resolution need real motion vectors, depth, jitter, exposure, history
reset, and related per-frame metadata that ReXGlue's final-color presenter does
not currently receive. Frame generation additionally needs consecutive real
frames, camera and UI separation data, latency integration, and pacing. A
single-frame path with zero motion/depth and a reset every frame would not be a
correct temporal implementation, so those modes are not exposed.

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

# Gameplay PAK/SOX reader and inspector models
python -m unittest tools.n3_gameplay_data_test

# Offline NAV parser, topology, route search, and funnel model
python -m unittest tools.n3_nav_test

# SDK lock and release packaging
python -m unittest `
  tools.sdk_lock_test `
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
- Put narrowly scoped stable-SDK adaptations in `tools\rexglue\patches\` and
  regenerate the ignored source tree with `tools\prepare-rexglue.py`.
- Regenerate translated sources; do not edit `generated/default/` manually.
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
