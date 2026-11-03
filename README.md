# N3 Recompiled

<img src="resources/n3-icon.png" width="128" height="128" alt="N3 Recompiled icon">

A native Windows recompilation of **N3: Ninety-Nine Nights** using
[ReXGlue](https://github.com/rexglue/rexglue-sdk). PowerPC game code is
translated ahead of time and runs through a native Windows host with a
Direct3D 12 Xenos renderer.

> [!IMPORTANT]
> This repository is the maintained
> [Tzeentchnet fork](https://github.com/Tzeentchnet/N3-Ninety-Nine-Nights-Recomp)
> of [WK2D/N3-Ninety-Nine-Nights-Recomp](https://github.com/WK2D/N3-Ninety-Nine-Nights-Recomp).
> Upstream remains the source of the published Alpha 12 binary. Fork releases
> and upstream releases are separate and do not contain the same changes.

No game assets, executable, generated game translations, or downloaded
toolchains are included. You must supply your own supported game data.

## Fork status

| | Repository |
| --- | --- |
| Maintained fork | [Tzeentchnet/N3-Ninety-Nine-Nights-Recomp](https://github.com/Tzeentchnet/N3-Ninety-Nine-Nights-Recomp) |
| Upstream project | [WK2D/N3-Ninety-Nine-Nights-Recomp](https://github.com/WK2D/N3-Ninety-Nine-Nights-Recomp) |
| Upstream baseline | [`d1416e5`](https://github.com/WK2D/N3-Ninety-Nine-Nights-Recomp/commit/d1416e56cf3066e4b07d0bd50fa8dbd1bd1e590d) |
| Fork releases | [Releases](https://github.com/Tzeentchnet/N3-Ninety-Nine-Nights-Recomp/releases) |
| Upstream Alpha 12 | [Release and downloads](https://github.com/WK2D/N3-Ninety-Nine-Nights-Recomp/releases/tag/v0.1.0-alpha.12) |

The fork is currently based directly on upstream `main`. See
[fork relationship and differences](docs/FORK.md) for the exact divergence and
release relationship.

## Differences from upstream

This fork adds:

- hardened, provenance-checked ReXGlue SDK installation, code generation,
  GPU-source preparation, builds, and release packaging;
- selected ReIGlue renderer fixes, PAL text-language selection, validated
  alternate voice overlays, and additional profile/frame-pacing work;
- an expanded development launcher with window modes, graphics overrides,
  isolated profiles, native setup/reset, custom paths, dry runs, and mod staging;
- deterministic offline loose-file mods plus a Blender-oriented asset-authoring
  and handoff plan;
- expanded engineering, release, and historical documentation; and
- a project-level BSD 3-Clause license.

Detailed evidence and validation limits are recorded in
[development status](docs/STATUS.md). A newer fork commit is not, by itself,
evidence of broader gameplay compatibility.

## Current status

- **Platform:** Windows 10/11 x64 with Direct3D 12.
- **Supported game:** USA/Europe executable `0.0.0.3`, identified in
  [game-build.json](docs/game-build.json).
- **Validated route:** opening mission, following cutscene, and save/load on the
  tested opening path.
- **Known limitation:** full-game coverage is incomplete, and higher frame-rate
  modes can accelerate animation.

## Build and run

Requirements are PowerShell 7, Node.js 18+, Python 3.10+, and 7-Zip on Windows
x64. From a fresh checkout:

```powershell
pwsh -NoProfile -File tools\bootstrap.ps1 -AcceptVisualStudioLicense -Python python
node tools\disc.mjs extract "path\to\your-disc.iso" private\game private\disc-manifest.json
pwsh -NoProfile -File tools\build.ps1
pwsh -NoProfile -File tools\launch.ps1
```

The launcher defaults to a 1280 x 720 window and keeps development profiles,
caches, logs, and game data in ignored local paths. See
[development and build](docs/DEVELOPMENT.md) for prerequisites, validation
commands, source boundaries, and release tooling, and the
[launcher guide](docs/LAUNCHER.md) for all runtime options.

This fork does not currently publish a binary release. The linked
[upstream Alpha 12 release](https://github.com/WK2D/N3-Ninety-Nine-Nights-Recomp/releases/tag/v0.1.0-alpha.12)
predates and does not include the fork-only changes listed above.

## Documentation

| Document | Contents |
| --- | --- |
| [Fork relationship](docs/FORK.md) | Upstream baseline, fork-only changes, remotes, and release ownership |
| [Development status](docs/STATUS.md) | Verified milestones, unresolved issues, and validation limits |
| [Development and build](docs/DEVELOPMENT.md) | Bootstrap, extraction, builds, tests, and release workflow |
| [Development launcher](docs/LAUNCHER.md) | Graphics, profiles, setup, custom paths, and mod staging |
| [Modding](docs/MODDING.md) | Safe loose-file staging, manifests, load order, and format limits |
| [Gameplay inspector](docs/GAMEPLAY-INSPECTOR.md) | Read-only character, enemy, item, ability, PAK, and SOX data browser |
| [Localization data](docs/LOCALIZATION.md) | Text surfaces, encodings, sheet keys, replacement stages, and font/art limits |
| [Blender authoring](docs/BLENDER-MODDING.md) | Read-only-first asset roadmap and versioned handoff |
| [Native conversion](docs/NATIVE-CODE.md) | Typed native modules and translated-code equivalence |
| [Porting roadmap](docs/PORTING.md) | SDK baseline, renderer/platform work, and portability boundaries |
| [Documentation index](docs/README.md) | Complete active and archived documentation |

Report fork-specific problems through the
[fork issue tracker](https://github.com/Tzeentchnet/N3-Ninety-Nine-Nights-Recomp/issues).
Include the commit, active profile/mod configuration, logs, and reproduction
steps, but never upload game files, disc images, saves, or private paths.

## License

Project-authored source and documentation are available under the
[BSD 3-Clause License](LICENSE). Third-party and adapted work retain their own
terms; see [third-party notices](THIRD_PARTY.md) and [`LICENSES/`](LICENSES/).

The license does not grant rights to **N3: Ninety-Nine Nights**, its executable,
game data, artwork, audio, trademarks, or other proprietary material.
