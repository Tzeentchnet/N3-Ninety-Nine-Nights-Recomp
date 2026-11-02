# Reference projects and design notes

Reviewed 2 November 2026. These are reference projects rather than game-data
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
`bd833a2ab69d305f99ddf57418fc38ffec8af93d`, provides the analyser, C++ generator,
runtime kernel, and GPU/audio/input integration. Its bundled CLI differs from
older wiki examples: this revision uses `n3_manifest.toml` with `[project]` and
`[entrypoint]` sections. The local scripts follow the installed CLI/parser.

This remains the newest published nightly and the head of ReXGlue's development
branch at review time. The repository's `main` branch points to the older
v0.10.0 release, so replacing the nightly with `main` would be a downgrade.

## Forza Horizon 1: ReImagined and ReIGlue

- [Forza tree at `a27387e4`](https://github.com/FH1-ReImagined/ForzaHorizon1-ReImagined/tree/a27387e45a5187089a748f12c98af72045408bf9)
- [ReIGlue at `330770d1`](https://github.com/FH1-ReImagined/ReIGlue/tree/330770d17b64bdf17fcff975b82789418c230db5)

Forza uses the same ReXGlue nightly plus its BSD ReIGlue fork. N3 carries three
title-independent changes that apply to its D3D12 Xenos plugin: rechecking
texture backing memory before marking a load current (`0008`), avoiding an
allocation and global lock when requested shared-memory pages are already valid
(`0031`), and checking both D3D12 fence HRESULTs before waiting (`0408`). The
generated-header output declaration (`0096`) is also reflected in
`generated/rexglue.cmake` to prevent stale PCH/header scheduling under Ninja.

Forza's wheel, online-service, VR, HDR, upscaler, Vulkan, texture-pack, and
Forza-specific resolve changes are outside N3's current requirements. Its audio
fallback and XMA hardening would require replacing the prebuilt runtime rather
than the project-built GPU plugin; N3 has no matching failure evidence, so those
larger changes remain candidates rather than untested imports.

## Recompiled Halo Reach

- [Repository at `329148bb`](https://github.com/Dyotson/RecompiledHaloReach/tree/329148bb156e0710bcf7f89ced1044461ea7f18f)

Halo Reach independently carries the texture-validity and shared-memory fixes,
and reports reduced command-processor lock waits from the latter. That
cross-title evidence supports the two changes selected above. Most of its
remaining patches target Vulkan, Linux/POSIX behavior, Reach shaders,
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
