# Reference projects and design notes

Reviewed 19 November 2026. These are reference projects rather than game-data
dependencies. No original game assets are included.

## Lost Odyssey Recomp

- [Repository](https://github.com/freefrank/LostOdysseyRecomp)
- [Build workflow](https://github.com/freefrank/LostOdysseyRecomp/blob/main/docs/BUILDING.md)
- [Recompilation notes](https://github.com/freefrank/LostOdysseyRecomp/blob/main/docs/notes/recomp.md)

Useful practices: keep original game files and generated translations local;
record manual function/switch corrections; diagnose runtime-only indirect targets;
separate build success from scene correctness; isolate profiles for regression
runs. Its notes specifically discuss functions referenced through pointers that
static analysis misses. That is directly relevant to the N3 startup traps.

Its custom runtime, shader pipeline, importer, configuration, saves, and packaging
are useful longer-term references. N3 currently uses the reusable ReXGlue runtime
to establish a first boot before considering subsystem replacements.

## Unleashed Recompiled

- [Repository and port features](https://github.com/hedge-dev/UnleashedRecomp)
- [Build structure](https://github.com/hedge-dev/UnleashedRecomp/blob/main/CMakeLists.txt)
- [XenonRecomp](https://github.com/hedge-dev/XenonRecomp)
- [XenosRecomp](https://github.com/hedge-dev/XenosRecomp)

Useful practices: build translated game code as its own target, keep the host
runtime distinct, supply an asset importer, and develop display/input/settings
features alongside a validated rendering pipeline. Native shader recompilation
is a possible future direction; N3 presently uses ReXGlue's Xenos GPU plugin.

## Current SDK

[ReXGlue](https://github.com/rexglue/rexglue-sdk), pinned to commit
`a3e1d82678ca20d68d4837a8e9ee4652ff073745`, is the stable
[v0.11.0 release](https://github.com/rexglue/rexglue-sdk/releases/tag/v0.11.0).
It provides the analyser, C++ generator, modular runtime kernel, and
GPU/audio/input integration. N3 uses the official release CLI for code
generation and builds the matched runtime modules from that exact source.

The v0.11 driver rewrite removes the earlier FSR1, CAS, temporal presentation,
and `present_effect` surfaces. N3 therefore uses bilinear presentation for this
milestone and defers FSR1 restoration instead of retaining a mixed v0.10/v0.11
runtime.

The renderer audit compared stable v0.11 with current `main` and `development`.
No upstream commit fixed the two hardware failures found in N3. N3 carries
small patches for:

- keeping ReXGlue's precommitted raw physical GPU view read/write across guest
  allocation and protection changes while retaining title-facing alias
  protections and write watches; and
- owning Vulkan presentation semaphores per swapchain image, then waiting for
  the presentation queue only when retiring a swapchain.

Development did provide a useful reproducibility improvement: pinning
Vulkan-Headers and Vulkan Memory Allocator as sources rather than depending on
whatever headers a machine Vulkan SDK happens to install. N3 backports that
approach with the exact dependency commits recorded in
`tools/toolchain.lock.json`.

## Forza Horizon 1: ReImagined and ReIGlue

- [Forza tree at `a27387e4`](https://github.com/FH1-ReImagined/ForzaHorizon1-ReImagined/tree/a27387e45a5187089a748f12c98af72045408bf9)
- [ReIGlue at `6e47a08c`](https://github.com/FH1-ReImagined/ReIGlue/tree/6e47a08c972a23944504af48996330262dfc64e5)

Forza and its BSD ReIGlue fork were reviewed for texture-watch validity,
shared-memory fast paths, D3D12 fence checks, input behavior, and
floating-point accuracy. The prior v0.10 renderer patch stack was retired with
the v0.11 migration rather than being applied blindly across the rewritten GPU
architecture.

Forza's wheel, online-service, VR, HDR, custom upscaler, texture-pack, and
title-specific resolve changes are outside N3's current requirements. Its
audio fallback and XMA hardening have no matching N3 failure evidence, so those
larger changes remain candidates rather than untested imports.

The follow-up build review also examined ReIGlue's loaded-only RenderDoc probe,
keyboard tap queue, opt-in CPU/GPU readback synchronization, and VMX
floating-point accuracy work through `6e47a08c`. They affect broader runtime or
generator behavior and remain deferred pending specific N3 evidence and
gameplay checks.

## Recent ReXGlue build references

- [Forza Horizon 1: ReImagined at `9ca04916`](https://github.com/FH1-ReImagined/ForzaHorizon1-ReImagined/tree/9ca049165d5441483c4aa3325f3ca8093d63ca60)
  records final payload hashes and public build provenance. Its project is
  GPL-3.0; no launcher or build code was copied.
- [Fable 2 Recomp at `4d86f4a1`](https://github.com/himdo/Fable-2-Recomp/tree/4d86f4a10d61f9f0e105b836a1e6587520e8c191)
  stages matched source-built runtime/plugin binaries with explicit SDK
  provenance. It is MIT-licensed and informed the compatibility review; N3 did
  not import its title patches or fork.
- [NocturneRecomp at `35e7deed`](https://github.com/birabittoh/NocturneRecomp/tree/35e7deed54f1a2d1922009c74ece8a79c51ed78a)
  uses architecture-aware CMake preset selection in an MIT-licensed build
  wrapper. N3 already has platform presets and retains its pinned Windows tools.
- [openNG2 at `18e6029b`](https://github.com/KamiTK2/openNG2/tree/18e6029be7039bf0639d0d4a69a16da83614eef8)
  and [Viva Pinata Recomp at `e094c650`](https://github.com/crabinacrabic/VivaPinataRecomp/tree/e094c650cab222d7d3d280d63c5a09ebbaa51b55)
  were reviewed for current preset/build structure only. No source was copied
  because an applicable repository license was not established.

N3 independently adopted the general outcomes: one validated SDK lock,
transactional tool replacement, exact CMake/codegen/source checks,
commit-derived source bundle names, and SDK provenance in release manifests.

## Recompiled Halo Reach

- [Repository at `329148bb`](https://github.com/Dyotson/RecompiledHaloReach/tree/329148bb156e0710bcf7f89ced1044461ea7f18f)

Halo Reach independently carries the texture-validity and shared-memory fixes,
and reports reduced command-processor lock waits from the latter. That
cross-title evidence informed the earlier v0.10 review, but those patches were
not carried blindly across the v0.11 GPU rewrite. Most of its remaining patches
target Vulkan, Linux/POSIX behavior, Reach shaders,
tessellation, occlusion queries, or high-refresh simulation and are not safe
proxies for N3's Direct3D 12 behavior.

## pgr4-native

- [Repository at `89705a9b`](https://github.com/safzanpirani/pgr4-native/tree/89705a9bef1a6e23ffcbde1a5d064c5eb4254dec)

PGR4 demonstrates a measured native-renderer path that hooks title-specific D3D
commands while retaining ReXGlue for guest execution. Its cache invalidation,
capture-oracle, frame-trace, and A/B measurement practices are useful references.
The renderer itself assumes PGR4 command streams and shaders and disables the
stock draw/present path, so it is not transplanted into N3 without equivalent
title-specific captures and image comparisons.

## N3-ReGPU sibling project

- Reviewed local revision: `c03c26e7b80851a391ffb5f19bbc499c0f84fb5c`
- License: MIT; preserved in [the N3-ReGPU notice](../LICENSES/N3-ReGPU.txt)

The user's separate same-title XenonRecomp/ReGPU project verified the supported
disc inventory and developed an immutable-extraction mod model: validate
manifests and paths, build a disposable merged tree, unlink before replacing a
hardlinked base file, record deterministic conflict winners, and keep the
runtime's writable data outside the game tree. That stager and its synthetic
regression tests were adapted for this repository.

Its custom kernel/XAM host, generated translation, ReGPU renderer, and runtime
status are not transplanted. This project retains ReXGlue and its working D3D12
path. ReGPU's architecture and format observations remain cross-checks unless
they are independently reproduced here; the ISO identity and extension counts
listed in [Modding](MODDING.md) were reproduced during this audit.

## Donelys N3 fork

- [Repository at `c408ddfe`](https://github.com/donelysentretenimiento/Donelys-N3recomp/tree/c408ddfe25e2bd07809841f6cb92446415c8a693)

The fork established two useful title facts: the supported PAL data contains
five complete text/font languages even though the pinned runtime always reports
English, and Japanese voices can occupy the game's English `SoundRes` slot
independently of text language. N3 implements those capabilities in its existing
runtime: two manifest hooks return a validated language cvar, and a read-only
VFS mount validates and overlays a user-supplied voice directory without making
a hard-link copy of the game tree. It also preserves an explicit
`fullscreen=true` value and reports pacing percentiles in the existing trace.

Donelys's launcher, native menu/theme modules, and documentation are
GPL-3.0-or-later; its icon and launcher art are all-rights-reserved. None of
that code or artwork is included. The Electron launcher duplicates N3's native
disc setup and graphics menu, its F5 menu lacks controller input and leaks
keyboard input to the game, and its fullscreen/60 FPS defaults conflict with
this project's documented 1280 x 720 window and 30 FPS policy. Those surfaces
remain reference-only.
