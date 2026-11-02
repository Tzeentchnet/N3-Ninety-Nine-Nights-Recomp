# Modding

## Current boundary

N3 Recompiled now supports **offline loose-file staging**. Mods are validated,
ordered, and merged with an owned extraction into the disposable `out/game/`
tree before launch. The original extraction remains the compatibility source
and is never edited by the stager.

| Capability | Status |
| --- | --- |
| Replace or add safe paths beneath `data/` | **Implemented and fixture-tested** |
| Deterministic load order, conflict winners, and staging report | **Implemented and fixture-tested** |
| Whole-file replacement of loose assets or complete `.pak` files | **Implemented as opaque path replacement** |
| Override `default.xex`, system-update files, or paths outside `data/` | **Rejected** |
| Decode or encode `.36t`, `.bm`, `.skin`, or N3 `.pak` formats | **Not implemented** |
| Override individual members inside `.pak` containers | **Not implemented** |
| Hot-load mods or change load order while the game is running | **Not implemented** |
| Distribute original game files as mods | **Not permitted by this project** |

This support proves safe path replacement, not that arbitrary replacement
payloads are valid game resources.

## Data flow

```text
private/game/             verified owned extraction; never modified
mods/
  enabled.txt             enabled IDs, lowest to highest priority
  author.example/
    mod.toml
    files/
      data/
        interface/
          Item/
            replacement.36t
        PackedResources/
          complete_group_tex.pak
out/game/                 disposable merged tree used for a modded launch
  .n3-mods.json           generated load-order, override, and conflict report
```

Base files are hardlinked into `out/game/` when the filesystem supports it.
Every overridden path is unlinked and copied from the winning mod before it is
published. If hardlinks are unavailable, the stager copies the affected base
files and reports the count.

Treat the staged tree as read-only. Editing a hardlinked base file in place
would also edit the original extraction. Use `--copy-base` when physical
separation is more important than disk usage, and always edit mod source files
then restage instead of editing `out/game/`.

## Quick start

The defaults use `private/game/`, `mods/`, `mods/enabled.txt`, and `out/game/`:

```powershell
python tools/mods.py validate
python tools/mods.py stage --replace
pwsh -NoProfile -File tools/launch.ps1 -GameDirectory out\game
```

Use an explicit owned extraction when it is stored elsewhere:

```powershell
python tools/mods.py stage `
  --game 'D:\Games\N3' `
  --mods mods `
  --order mods\enabled.txt `
  --output out\game `
  --replace
```

The output is intentionally restricted to this repository's `out/game/`.
Source/output ancestor overlap, resolved aliases, symlink or reparse-point
staging paths, unsafe Windows names, duplicate case-insensitive paths, and a
base `.n3-mods.json` collision are rejected before replacement.

## Manifest and load order

Each mod folder has a `mod.toml`:

```toml
[mod]
id = "author.example"
name = "Example loose-file replacement"
version = "1.0.0"
description = "Replaces one user-supplied interface texture."
```

The folder name must match `mod.id`. IDs contain lowercase ASCII letters,
digits, `.`, `_`, or `-`, start with a letter or digit, and are at most 64
characters. Only regular files beneath `files/data/` are accepted.

List enabled IDs in `mods/enabled.txt`, one per line. Later entries have higher
priority. The generated report records every provider and the final winner for
each conflict. Rebuilding uses a temporary sibling directory and swaps the
completed stage into place; `--replace` is required when a prior stage exists.

## Verified asset inventory

On 2 November 2026, a fresh hash of the owned ISO matched the repository's
checked-in XDVDFS build record. A fresh inventory using the sibling N3-ReGPU
reader reproduced the same partition and extraction totals. Node.js was not
available in that audit session, so this repository's reader was not rerun:

| Property | Value |
| --- | ---: |
| ISO SHA-256 | `252ec1da879e938cfcd8601af784436e6bc38e5bf95d37400b601ad6e2a2f3f9` |
| Image size | `7,834,892,288` bytes |
| Game partition offset | `265,879,552` (`0x0FD90000`) |
| Files | `3,342` |
| Extracted file bytes | `5,770,038,003` |

The owned image contains these relevant file counts:

| Extension | Count | Current modding interpretation |
| --- | ---: | --- |
| `.36t` | 1,047 | Loose texture-like resources; opaque whole-file replacement |
| `.pak` | 523 | Complete-container replacement only; 522 are under `data/PackedResources/` |
| `.fxw` | 509 | Effect-related binary; format not decoded |
| `.skin` | 216 | Model/skin companion data; opaque whole-file replacement |
| `.txt` | 196 | Text or configuration data; encoding/schema remains file-specific |
| `.bm` | 187 | Model-like resources; opaque whole-file replacement |
| `.bpf` | 143 | Binary data; format not decoded |
| `.xwb` | 113 | XACT wave banks; use the validated voice-directory path for full voice sets |
| `.bfx` | 105 | Effect-related binary; format not decoded |
| `.sox` | 72 | Audio-related binary; format not decoded |
| `.n3sb` | 36 | N3-specific binary; format not decoded |
| `.xsb` | 35 | XACT sound banks; cues must remain compatible with their wave banks |
| `.uitb` | 34 | UI-related binary; format not decoded |
| `.bik` | 11 | Bink video |
| `.xgs` | 2 | XACT global settings |

Counts are evidence for research scope, not a promise that every file can be
edited safely. Multi-file assets should be replaced with all known companions.

## Packed-resource limitation

Many character and level resources are grouped in paired `*_res.pak` and
`*_tex.pak` files. Their entry tables, compression, alignment, checksums, and
duplicate-name behavior are not verified. The stager therefore permits only a
complete package supplied by the user; it does not unpack or repack members.

Per-entry package mods require either:

1. a bounded, deterministic reader/writer verified against multiple owned
   samples and synthetic corruption fixtures; or
2. a runtime archive hook that checks a mod overlay before the original member.

Neither exists yet. A recognized extension or sample header is not sufficient
evidence for a writer.

## Runtime and gameplay hooks

The current voice override demonstrates a validated read-only VFS replacement
for one complete directory. ReXGlue symbolic links replace a subtree rather
than providing union/fallback semantics, so the same mechanism is not a safe
generic loose-file overlay. Offline staging remains the default until a tested
union device or archive lookup hook exists.

Typed native modules expose another future mod boundary: understood gameplay
state can gain explicit, validated settings without patching generated code.
Such hooks require equivalence tests, save-compatibility analysis, deterministic
configuration, and a retained path for unsupported state. The conversion count
alone does not establish a stable gameplay mod API.

## Content and support rules

- Never place the ISO, `default.xex`, extracted base assets, generated game
  translations, caches, or saves in a mod or commit.
- Mods must contain only content the author may redistribute.
- Keep saves, configuration, logs, and caches outside the staged game tree.
- Report the active `.n3-mods.json`, load order, game revision, and reproduction
  steps when diagnosing a modded failure.
- Reproduce a problem without mods before treating it as a base-game regression.

The stager and safety model were adapted from the user's MIT-licensed N3-ReGPU
project at commit `c03c26e7b80851a391ffb5f19bbc499c0f84fb5c`. See
[reference notes](REFERENCES.md) and [the preserved notice](../LICENSES/N3-ReGPU.txt).
