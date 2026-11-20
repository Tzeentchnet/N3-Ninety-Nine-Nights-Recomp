# Documentation

These documents describe the supported USA/Europe `0.0.0.3` executable unless
a section explicitly says otherwise.

## Active documentation

| Document | Contents |
| --- | --- |
| [Installation and first-run setup](../INSTALL.md) | Release-package installation, source bootstrap, game-data setup, build, launch, updates, and removal |
| [Fork relationship](FORK.md) | Upstream baseline, fork-only changes, remotes, and release ownership |
| [Development status](STATUS.md) | Observed milestones, validation evidence, unresolved issues, and explicit limits |
| [Development and build](DEVELOPMENT.md) | Bootstrap, game extraction, builds, targeted checks, and release workflow |
| [Installed launcher and F4 settings](SETTINGS.md) | Packaged graphics, language, audio, controller, keyboard/mouse, shared configuration, and advanced overlay |
| [Development launcher](LAUNCHER.md) | Window and graphics overrides, profiles, native setup, paths, and mod staging |
| [Native engine modules](NATIVE-CODE.md) | Typed C++ replacements, guest adapters, equivalence boundaries, and test coverage |
| [Game-code conversion plan](CONVERSION-PLAN.md) | Converted domains, remaining generated code, and criteria for future native modules |
| [Native code and platform roadmap](PORTING.md) | Portable components, renderer/platform work, and deeper game changes |
| [Modding](MODDING.md) | Safe loose-file staging, manifests, load order, verified asset inventory, and future mod hooks |
| [Gameplay data inspector](GAMEPLAY-INSPECTOR.md) | Read-only visual and command-line browser for gameplay PAK and SOX data |
| [AI and navigation architecture](AI-NAVIGATION.md) | Mission, troop, unit, NAV, route-search, dynamic-topology, and modernization findings |
| [Localization data](LOCALIZATION.md) | PAL text inventory, sheet identity, safe replacement path, and asset/font limits |
| [Blender asset authoring](BLENDER-MODDING.md) | Blender 5.2 import/export roadmap, format gates, and versioned mod handoff |
| [Reference projects](REFERENCES.md) | Reviewed projects, exact revisions, adopted ideas, and licensing boundaries |
| [Supported game build](game-build.json) | Disc and executable identity used by import and compatibility checks |
| [Release documentation](releases/README.md) | Current package-document contract and archived upstream release records |

## Reporting issues

Report fork-specific problems through the
[fork issue tracker](https://github.com/Tzeentchnet/N3-Ninety-Nine-Nights-Recomp/issues).
Include the commit, active profile and mod configuration, logs, and reproduction
steps. Never upload game files, disc images, saves, or private paths.

## Evidence labels

Reverse-engineering and modding claims use these labels:

- **Verified**: reproduced by a checked-in tool or test against the supported
  image, executable, or synthetic fixture.
- **Observed**: directly seen in owned data or a runtime trace, but the complete
  behavior or format is not established.
- **Inferred**: supported by naming, structure, or another implementation and
  still requires an N3-specific test.
- **Planned**: a design direction, not a current compatibility promise.
- **Historical**: a record of an upstream release or past development state,
  not a statement about the current private branch.

Update the relevant document in the same change whenever code establishes or
invalidates one of these claims. Build success and process survival are not
gameplay validation.
