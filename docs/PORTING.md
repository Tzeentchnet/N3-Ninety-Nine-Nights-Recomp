# Native code and platform roadmap

The translated PowerPC functions already compile into native machine code.
Portability depends on the runtime, graphics backend, platform services, and
game-specific timing as well as the CPU target. Replacing a function with more
readable C++ is useful when it removes a measured bottleneck or provides a tested
gameplay interface; it does not by itself establish a faster or correct port.

## SDK and build baseline

As verified against GitHub's release API on 2 November 2026, the newest
published ReXGlue Windows SDK is nightly `0.10.0.24-dev.gbd833a2`, full commit
[`bd833a2ab69d305f99ddf57418fc38ffec8af93d`](https://github.com/rexglue/rexglue-sdk/tree/bd833a2ab69d305f99ddf57418fc38ffec8af93d).
That is the exact archive already pinned in `tools/toolchain.lock.json`.
ReXGlue `main` still diverges at the older v0.10.0 release; replacing the
nightly with `main` would discard later codegen fixes, including Xenon memory
ordering fences.

The lock file is the single source for SDK version, full commit, release tag,
asset name, URL, and SHA-256. The current build process enforces it at each
boundary:

1. `tools/bootstrap.ps1` verifies the downloaded archive, validates the CLI's
   reported version, and records the complete installed identity. A changed or
   inconsistent lock installs into a temporary directory before replacing the
   prior SDK.
2. `tools/codegen.ps1` refuses a stale CLI before reading the supported XEX.
   CMake independently compares `REXGLUE_VERSION_STRING` with the lock before
   compiling the game. A tested post-codegen step restores N3's generated
   header outputs and routes incremental Ninja codegen through the same checks,
   so SDK regeneration cannot silently undo the ordering fix.
3. `tools/bundle-sdk-source.py --if-needed` fingerprints the SDK pin and every
   local renderer-extension input. The commit-named corresponding-source
   archive and `tools/prepare-gpu.py` are derived from the lock rather than
   hardcoded to one revision.
4. `tools/build.ps1` regenerates source provenance when its inputs change,
   refreshes the disposable SDK source tree across pin changes, builds the
   D3D12 plugin, builds the host/generated code, and runs CTest.
5. Packaging refuses uncommitted sources. Release manifests carry the source
   commit and exact SDK binary/source provenance in addition to all packaged
   file hashes.

Run `python tools/check-sdk.py` to compare the lock with the newest published
Windows asset. This is an explicit network audit, not an automatic floating
upgrade. The offline `tools.sdk_lock_test` and
`tools.fix_generated_cmake_test` suites cover lock selection and post-codegen
build integration.

## Recent project review

The build review also checked current revisions of
[ReIGlue `6e47a08c`](https://github.com/FH1-ReImagined/ReIGlue/tree/6e47a08c972a23944504af48996330262dfc64e5),
[Forza Horizon 1: ReImagined `9ca04916`](https://github.com/FH1-ReImagined/ForzaHorizon1-ReImagined/tree/9ca049165d5441483c4aa3325f3ca8093d63ca60),
[Fable 2 Recomp `4d86f4a1`](https://github.com/himdo/Fable-2-Recomp/tree/4d86f4a10d61f9f0e105b836a1e6587520e8c191),
[NocturneRecomp `35e7deed`](https://github.com/birabittoh/NocturneRecomp/tree/35e7deed54f1a2d1922009c74ece8a79c51ed78a),
[openNG2 `18e6029b`](https://github.com/KamiTK2/openNG2/tree/18e6029be7039bf0639d0d4a69a16da83614eef8),
and [Viva Pinata Recomp `e094c650`](https://github.com/crabinacrabic/VivaPinataRecomp/tree/e094c650cab222d7d3d280d63c5a09ebbaa51b55).

Useful general practices adopted here are exact SDK/runtime provenance,
transactional tool staging, preset-driven builds, final-package hashes, and
tests that exercise lock-selection failures. They were independently
implemented for N3's existing scripts. No GPL Forza launcher code or code from
projects without an applicable source license was copied.

Fable demonstrates building matched runtime and GPU binaries from a source
fork, while Forza/ReIGlue test an extensive source-built runtime and codegen
stack. N3 deliberately retains the official prebuilt runtime/codegen plus its
source-built D3D12 plugin until a runtime change has title-specific evidence.
Recent ReIGlue fixes for loaded-only RenderDoc attachment, fast keyboard taps,
CPU/GPU readback ranges, and Xenon-accurate VMX floating-point operations are
credible upstream candidates, but they modify runtime or generator components
that N3 does not currently rebuild. Adopting them requires a matched source SDK,
regenerated translations where applicable, retained/native equivalence tests,
and a repeated gameplay route. A newer fork commit is not by itself an SDK
upgrade.

## First portable components

Configure without the SDK, original executable, or generated translations:

```sh
cmake -S . -B out/portable-core -DN3_BUILD_GAME=OFF -DCMAKE_BUILD_TYPE=Release
cmake --build out/portable-core --config Release
ctest --test-dir out/portable-core -C Release --output-on-failure
```

This builds the native disc verifier/importer and menu asset transformations.
Windows uses CNG for SHA-256, macOS uses CommonCrypto, and Linux uses OpenSSL
Crypto (install its development package). Windows keeps wide-character command
line paths. Destination checks reject symbolic links and Windows reparse points.
Tests use synthetic fixtures; CI never needs or uploads game files.
The portable-components workflow checks Windows, Linux, and an Apple Silicon
macOS runner. Passing these tests does not mean the game runs on those platforms.

## Development launcher boundary

The PowerShell [development launcher](LAUNCHER.md) is a Windows game-running
tool, not a portable runtime layer. It now centralizes one-launch graphics
overrides, isolated local profiles, explicit user/cache/log roots, native ISO/XEX
setup, remembered-path reset, and offline mod staging. Direct packaged
executables retain their native `%LOCALAPPDATA%\N3Recompiled` behavior.

Launcher mod selection calls the existing Python stager and still publishes only
to the disposable `out/game/` tree. It does not add runtime hot loading, asset
codecs, or a platform-independent game-data API. Future platform launchers should
preserve the same profile isolation, setup validation, immutable base extraction,
and deterministic mod-order semantics without treating PowerShell argument
construction as an engine interface.

## Vulkan migration

The pinned [ReXGlue SDK](https://github.com/rexglue/rexglue-sdk/tree/bd833a2ab69d305f99ddf57418fc38ffec8af93d)
contains Vulkan and macOS/ARM64 support. Its macOS route uses Vulkan through
MoltenVK. N3 currently packages a D3D12-only Windows runtime and a custom Xenos
plugin; enabling a compiler flag alone is insufficient.

1. Build a separate Vulkan-capable runtime/plugin from pinned SDK/dependency
   sources, preserving the working D3D12 release.
2. Make renderer selection explicit. Preserve a D3D12 fallback while validating
   Vulkan on Windows with isolated profiles and shader caches.
3. Implement the same Graphics behavior on Vulkan: synchronized presentation,
   filtering overrides, live render-scale changes, failure rollback and backend
   traces. Do not silently accept a setting that the selected backend ignores.
4. Compare title/menu, opening cutscene, first mission, effects, save/load and
   frame times. Measure shader compilation stalls, CPU/GPU time and memory before
   choosing optimizations or making Vulkan the default.
5. Replace Windows picker/import progress, display sizing, crash reporting and
   packaging adapters. Build the translated game/runtime for ARM64, stage
   MoltenVK in a macOS application bundle, then validate on Apple Silicon hardware.

The SDK's [macOS release notes](https://github.com/rexglue/rexglue-sdk/releases/tag/v0.10.0)
describe the upstream backend. N3's existing live-resolution and VSync extensions
are D3D12-specific and require separate Vulkan implementations.

## Deeper game changes

The first extracted engine primitive is the [native frame clock](NATIVE-CODE.md).
It is independent of the graphics backend and is checked against the retained
translated initializer. The active game build remains on Direct3D 12; Vulkan
development is parked following a system-freeze report.

First establish original-speed timing: trace animation, combat and scripted
event updates at the same gameplay point across 30/40/60 FPS. The current clock
hooks do not establish correct animation speed. Extract understood routines into
typed native modules with explicit guest-memory adapters, units and ownership;
compare outputs against the retained translated implementation before switching.

Offline loose-file staging now provides the first asset-override boundary; see
[Modding](MODDING.md). The separate Blender 5.2 add-on's 0.14.0 baseline has
eight read-only import operators and reads supported package members in memory.
Its bounded codecs and Blender adapters remain outside the runtime. It has no
exporter or native writer, and visual and in-game/runtime gates remain unmet.
The [Blender authoring contract](BLENDER-MODDING.md) defines a future versioned
receipt, not an implemented handoff: the current stager does not consume,
validate, or stage a receipt beside `mod.toml`; it stages payloads beneath
`files/data/`. Future runtime or gameplay hooks should build on typed interfaces
and verified archive lookups rather than patching generated code. Keep save
formats and original data compatible until a migration is deliberately
implemented and tested. Profiles, traces and original assets stay local.

The companion manifest is now `0.14.1`, an ungated candidate rather than a
completed release. Its Blender 5.2.2 source/save-reopen, Blender-built ZIP,
and isolated-install gates are unexecuted; ZIPs remain local-only. Its
configured CI covers synthetic Python and packaging, not Blender, private
fixtures, or recomp parity.

The companion evidence matrix separates the completed character/root source
inventories from partial deformation, signal, and attachment research. The
bounded animation capture counts pose-output calls without recording matrices
and binds no actor; it cannot establish source FPS, interpolation, world root
motion, an equipped attachment, or gameplay event effects. The next runtime
work must bind winning package members and actors before synchronized
controller/pose, root/child and dispatch/effect comparisons on at least two
characters. This does not authorize notify markers, root extraction, a writer,
or receipt consumption.

Milestones are a rendered Vulkan Windows build, matching Graphics controls,
normal-speed high-FPS gameplay, a rendered ARM64 Mac build, then mission coverage
and measured performance improvements. None is established by a core-only build.
