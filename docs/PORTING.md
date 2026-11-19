# Native code and platform roadmap

The translated PowerPC functions already compile into native machine code.
Portability depends on the runtime, graphics backend, platform services, and
game-specific timing as well as the CPU target. Replacing a function with more
readable C++ is useful when it removes a measured bottleneck or provides a tested
gameplay interface; it does not by itself establish a faster or correct port.

## SDK and build baseline

As verified against GitHub's release API on 19 November 2026, the project pins
stable ReXGlue `v0.11.0`, full commit
[`a3e1d82678ca20d68d4837a8e9ee4652ff073745`](https://github.com/rexglue/rexglue-sdk/tree/a3e1d82678ca20d68d4837a8e9ee4652ff073745).
The official Windows archive supplies the matching code generator; the game
build compiles the modular runtime from the exact stable source plus two
narrowly scoped renderer fixes.

The lock file is the single source for SDK version, full commit, release tag,
asset name, URL, and SHA-256. The current build process enforces it at each
boundary:

1. `tools/bootstrap.ps1` verifies the downloaded archive, validates the CLI's
   reported version, and records the complete installed identity. A changed or
   inconsistent lock installs into a temporary directory before replacing the
   prior SDK.
2. `tools/prepare-rexglue.py` checks out the locked source and all submodules,
   adds the pinned Vulkan-Headers and Vulkan Memory Allocator trees, applies
   `tools/rexglue/patches` in lexical order, and records hashes of the resulting
   source state. Preparation is transactional and rejects stale or modified
   trees.
3. `tools/codegen.ps1` refuses a stale CLI before reading the supported XEX.
   CMake independently compares the prepared source marker and SDK version with
   the lock before compiling the game.
4. `tools/bundle-sdk-source.py --if-needed` fingerprints the complete SDK pin,
   extra source dependencies, patches, and local integration files. Its
   commit-named corresponding-source archive contains every dependency and the
   exact patch/build recipe.
5. `tools/build.ps1` verifies the prepared source, builds the D3D12, Vulkan,
   null, and supporting runtime modules with the host/generated code, and runs
   CTest.
6. Packaging refuses uncommitted sources. Release manifests carry the source
   commit and exact SDK binary/source provenance in addition to all packaged
   file hashes.

Run `python tools/check-sdk.py` to compare the lock with the newest published
Windows asset. This is an explicit network audit, not an automatic floating
upgrade. The offline `tools.sdk_lock_test` suite covers the lock and pinned
source dependencies.

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
stack. N3 now retains the official v0.11 code generator while building the
matched stable runtime modules from source.
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

The pinned [ReXGlue SDK](https://github.com/rexglue/rexglue-sdk/tree/a3e1d82678ca20d68d4837a8e9ee4652ff073745)
builds both Windows D3D12 and Vulkan drivers. The launcher makes D3D12 the
default and Vulkan an explicit opt-in so profiles and shader caches can remain
isolated.

Bounded validation on an NVIDIA GeForce RTX 5070 reached Vulkan device and
swapchain creation, sustained the standard build for 25 seconds with
Khronos validation enabled, and emitted neither the original binary-semaphore
reuse VUID nor the old-swapchain-destroyed-while-in-use VUID after the tracked
fix. This proves that the tested path initializes and presents without those
specific synchronization violations; it does not prove correct images,
performance, or gameplay.

Remaining work is to compare the title/menu, opening cutscene, first mission,
effects, save/load, and frame times across D3D12 and Vulkan on multiple drivers.
Vulkan should not become the default until those checks establish a benefit and
acceptable compatibility. macOS/ARM64 additionally requires platform UI,
filesystem, packaging, and MoltenVK validation rather than only compiling the
backend.

## Deeper game changes

The first extracted engine primitive is the [native frame clock](NATIVE-CODE.md).
It is independent of the graphics backend and is checked against the retained
translated initializer. Direct3D 12 remains the default; Vulkan remains an
opt-in development backend pending broader gameplay, image, performance, and
driver validation.

The current 30/40/60 choices are host presentation targets and deliberately keep
the title on the established original-speed 30 FPS game-clock policy.
Establishing true higher-rate gameplay still requires matched traces of
animation, combat, scripted-event updates, and render production at the same
gameplay point, followed by understood interpolation or time-step changes.
Extract those routines into typed native modules with explicit guest-memory
adapters, units and ownership; compare outputs against the retained translated
implementation before switching.

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
completed release, with nine read-only imports and zero exports. Synthetic
Blender 5.2.2 source/save-reopen smoke passed on the integration changes. At
add-on commit `e90f41354eb40ecf941a11114ad4ba82a1ee54ae`, the exact
Blender-built ZIP also passed source/archive verification, isolated
installation, synthetic import, and save/reopen. Verified candidate ZIPs may
be published only as GitHub prereleases; clean-pinned corpus, visual, runtime,
writer, staging, and in-game gates remain open for stable approval. Its
configured CI covers synthetic Python and packaging, not Blender, private
fixtures, or recomp parity.

The companion evidence matrix separates the completed character/root source
inventories from preview-only deformation and partial signal/attachment
research. Later bounded animation probes matched one archive-content/member
identity and sampled quaternion-helper values, but recorded no actor/root/child
matrices and bound no actor. They cannot establish source FPS, interpolation, world root
motion, an equipped attachment, or gameplay event effects. The next runtime
work must bind winning package members and actors before synchronized
controller/pose, root/child and dispatch/effect comparisons on at least two
characters. This does not authorize notify markers, root extraction, a writer,
or receipt consumption.

Milestones are a rendered Vulkan Windows build, matching Graphics controls,
normal-speed high-FPS gameplay, a rendered ARM64 Mac build, then mission coverage
and measured performance improvements. None is established by a core-only build.
