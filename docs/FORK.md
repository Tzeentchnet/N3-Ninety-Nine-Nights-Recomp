# Fork relationship and differences

This repository is the maintained Tzeentchnet fork of
[WK2D/N3-Ninety-Nine-Nights-Recomp](https://github.com/WK2D/N3-Ninety-Nine-Nights-Recomp).
The fork preserves upstream history and continues development without
representing fork-only work as an upstream release.

## Baseline and divergence

As checked on 2 November 2026:

| Property | Value |
| --- | --- |
| Fork repository | [Tzeentchnet/N3-Ninety-Nine-Nights-Recomp](https://github.com/Tzeentchnet/N3-Ninety-Nine-Nights-Recomp) |
| Upstream repository | [WK2D/N3-Ninety-Nine-Nights-Recomp](https://github.com/WK2D/N3-Ninety-Nine-Nights-Recomp) |
| Shared upstream baseline | [`d1416e56`](https://github.com/WK2D/N3-Ninety-Nine-Nights-Recomp/commit/d1416e56cf3066e4b07d0bd50fa8dbd1bd1e590d) |
| Upstream-only commits at audit | 0 |
| Published fork releases | None |
| Fork releases | [Tzeentchnet releases](https://github.com/Tzeentchnet/N3-Ninety-Nine-Nights-Recomp/releases) |
| Latest upstream release | [v0.1.0-alpha.12](https://github.com/WK2D/N3-Ninety-Nine-Nights-Recomp/releases/tag/v0.1.0-alpha.12) |

The private repository is an independent GitHub copy rather than a
GitHub-native fork, but its Git history has a direct merge base with upstream.
In local development, `origin` is the read-only WK2D upstream and `private` is
the maintained Tzeentchnet repository.

## Fork-only work

The fork adds:

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

The major implementation milestones through the project-license update are:

| Commit | Area | Difference |
| --- | --- | --- |
| `9360567` | ReXGlue/runtime integration | Retains the newer official ReXGlue nightly, applies selected BSD ReIGlue GPU fixes, hardens generated-header scheduling, and adds PAL text, validated alternate voices, graphics persistence, and frame-pacing work. |
| `343da2e` | Repository workflow | Records private-development data boundaries and repository conventions without tracking game material. |
| `9891d0a` | Modding and documentation | Archives upstream release records and adds deterministic, path-safe offline loose-file staging. |
| `435f7d7` | SDK/build pipeline | Adds central SDK-lock validation, transactional installation, generated-CMake repair, incremental generation, GPU refresh, and release provenance. |
| `9b34fdb` | Release privacy | Corrects bounded build-identifier scanning without weakening actual local-identifier detection. |
| `96e198d` | Release validation | Documents and verifies reproducible package contents and provenance limits. |
| `a94df21` | Blender authoring | Adds the read-only-first `.skin`, `.bm`, and `.36t` roadmap plus a versioned future export receipt. |
| `4a43ec6` | Development launcher | Adds graphics/window controls, profiles, native setup/reset, path overrides, dry-run plans, mod discovery, and launcher-driven staging. |
| `4b6b78c` | Licensing | Adds the BSD 3-Clause project license and carries it into release/source bundles. |

See [development status](STATUS.md) for the validation performed at each
milestone and [reference projects](REFERENCES.md) for exact reviewed revisions
and licensing boundaries.

## Boundaries retained from upstream

The fork does not change these core requirements:

- The supported game executable remains USA/Europe version `0.0.0.3`.
- Original game data and generated game translations remain untracked.
- The active full-game target remains Windows x64 with Direct3D 12.
- Users must provide their own lawfully obtained game data.
- Process survival or a successful build does not establish gameplay
  correctness.

No GPL Donelys launcher/native code, unlicensed branding, original game asset,
or title-specific code from unrelated recompilation projects was copied.

## Release ownership

Always check the repository owner in a release URL:

- `github.com/Tzeentchnet/.../releases` contains releases produced by this fork.
- `github.com/WK2D/.../releases` contains upstream releases.

As of the date above, this fork has no published binary release. Upstream Alpha
12 remains available, but it predates all fork-only commits and therefore does
not contain the fork's launcher, modding, SDK-pipeline, Blender-plan, or license
changes.

Future fork packages must retain exact source/SDK provenance, the project and
third-party licenses, corresponding sources where required, and the existing
game/profile/privacy exclusions. See [release documentation](releases/README.md).

## Updating from upstream

Before integrating future upstream work:

1. Fetch `origin/main` and inspect `origin/main..main` and `main..origin/main`.
2. Review upstream changes against fork-only SDK, launcher, modding, and release
   surfaces rather than replacing them wholesale.
3. Preserve third-party notices and generated-source boundaries.
4. Re-run the checks appropriate to every affected subsystem.
5. Record behavior changes and validation limits in the active documentation.

Do not force-push or rewrite upstream authorship. Fork commits are pushed to
`private/main`; upstream remains a comparison and update source.
