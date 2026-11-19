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
| Import N3 assets into Blender | **Separate add-on's 0.14.0 baseline: eight read-only operators; current ungated 0.14.1 source has nine; visual/runtime gates unmet** |
| Emit or consume a Blender export receipt | **Version 1 contract documented; no exporter or receipt consumer** |
| Decode `.pak` containers and `.sox` tables | **Bounded read-only codec and full-corpus validation implemented** |
| Inspect global character, unit, combat, troop, item, or ability tables | **Read-only visual application implemented and fixture-tested** |
| Export and rebuild loose PAL localization text | **Format and sheet contract investigated; tooling not implemented** |
| Rebuild localized SOX tables or their containing PAKs | **Not implemented; formats mapped for staged writer work** |
| Edit global gameplay tables | **Not implemented; no runtime-edited package validation yet** |
| Decode `.36t`, `.bm`, or `.skin` formats | **Supported read-only profiles in the separate add-on; opaque to the stager** |
| Encode native `.36t`, `.bm`, or `.skin` formats | **Not implemented; named-profile writer gates apply** |
| Override individual members inside `.pak` containers | **Not implemented** |
| Hot-load mods or change load order while the game is running | **Not implemented** |
| Distribute original game files as mods | **Not permitted by this project** |

This support proves safe path replacement, not that arbitrary replacement
payloads are valid game resources.

The companion's source manifest is now `0.14.1`, an ungated candidate carrying
the historical `0.14.0` baseline. Its nine imports remain read-only, with
zero exports and no native writer or receipt consumer. Synthetic Blender
source/save-reopen smoke passed on the integration changes. At add-on commit
`e90f41354eb40ecf941a11114ad4ba82a1ee54ae`, the Blender-built ZIP and exact
isolated-install smoke also passed. Verified candidate ZIPs may be published
only as GitHub prereleases; the clean-pinned corpus, visual, runtime, writer,
staging, and in-game gates remain open for stable approval.

## Data flow

```text
private/game/             verified owned extraction; never modified
mods/
  enabled.txt             enabled IDs, lowest to highest priority
  author.example/
    mod.toml
    n3-blender-export.json  optional authoring receipt; currently ignored
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
pwsh -NoProfile -File tools\launch.ps1 -ListMods
pwsh -NoProfile -File tools\launch.ps1 -UseEnabledMods
```

The launcher validates and stages the enabled mods into `out/game/`, then passes
that disposable tree to the game. Stage without launching, or choose an explicit
low-to-high priority list without editing `enabled.txt`:

```powershell
pwsh -NoProfile -File tools\launch.ps1 -UseEnabledMods -StageOnly
pwsh -NoProfile -File tools\launch.ps1 `
  -Mod author.base,author.compatibility,author.personal
```

See the [development launcher guide](LAUNCHER.md) for custom game/mod paths,
profile isolation, `-CopyModBase`, dry-run planning, and option conflicts.

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
| `.skin` | 216 | Small companion data with observed `.bm` / `.fx` references; opaque whole-file replacement |
| `.txt` | 196 | PAL `data/Text` localization subset decoded; other text/configuration files remain file-specific |
| `.bm` | 187 | Model-like resources; opaque whole-file replacement |
| `.bpf` | 143 | Binary data; format not decoded |
| `.xwb` | 113 | XACT wave banks; use the validated voice-directory path for full voice sets |
| `.bfx` | 105 | Effect-related binary; format not decoded |
| `.sox` | 72 | Generic tabular data; loose and packed samples include gameplay and localization definitions |
| `.n3sb` | 36 | N3-specific binary; format not decoded |
| `.xsb` | 35 | XACT sound banks; cues must remain compatible with their wave banks |
| `.uitb` | 34 | UI-related binary; format not decoded |
| `.bik` | 11 | Bink video |
| `.xgs` | 2 | XACT global settings |

Counts are evidence for research scope, not a promise that every file can be
edited safely. Multi-file assets should be replaced with all known companions.

## Blender authoring track

The separate Blender 5.2 add-on's 0.14.0 baseline has eight read-only operators
for loose `.bm` models and `.skin` descriptors, plus character, static
resource, terrain, level, navigation, and camera packages. Supported `.36t`
textures can be previewed, and package members are read in memory without
generic extraction. Tests use synthetic redistributable fixtures; visual and
in-game/runtime acceptance gates remain open.

Character imports can create no Actions, representative candidates, selected
zero-based clip indices/ranges, or all supported source clips. Direct clips
use neutral `Clip_###` names. Source timing, interpolation, event linkage,
multi-character deformation, and evidence-backed attachments remain research,
not writer guarantees.

The companion's `0.14.1` source is an ungated read-only candidate, not a
completed release. Its ninth import is an explicit detached diagnostic.
One bounded runtime probe matched an animation archive-content/member
identity, not an actor or a unique runtime mount path; root-motion extraction,
notify markers and attachment sockets remain unknown. Unresolved imported
assets remain detached.
See its `docs/ROADMAP.md` evidence matrix and detailed runtime/root/attachment
records, and this repository's [signal and runtime trace](NATIVE-CODE.md).
Synthetic Blender source/save-reopen smoke passed on the integration changes.
At add-on commit `e90f41354eb40ecf941a11114ad4ba82a1ee54ae`, the exact
Blender-built `0.14.1` ZIP also passed source/archive verification, isolated
installation, synthetic import, and save/reopen. It may be published only as
a GitHub prerelease with the remaining stable gates disclosed.

A local scan found that every loose `.skin` sample contains exactly one
NUL-terminated `.bm` reference and at least one `.fx` reference; 205 of 216
also contain a `.dds` reference. This is evidence for a model/material
dependency descriptor, not evidence for bones or animation. The add-on must not
map `.skin` directly to a Blender armature based on its extension.

The complete architecture, format questions, acceptance gates, validation
ladder, and future versioned export receipt are in
[Blender asset authoring](BLENDER-MODDING.md). The current stager neither reads
nor validates a `n3-blender-export.json` beside `mod.toml`, and does not copy
it to the staged tree. The synthetic
`tools.mods_test.ModTests.test_ignores_malformed_blender_receipt_when_validating_and_staging`
regression exercises validation and staging with malformed receipt JSON. This
is evidence of non-consumption, not receipt validation. No exporter or native
writer exists; a future named writer profile must pass the complete corpus
round-trip, modified-output reparse, mod validation, staging, and isolated
in-game gates before it is exposed.

## Packed-resource format

A read-only investigation on 2 November 2026 decoded all 522 archives beneath
`data/PackedResources/`:

- 521 use a four-byte big-endian uncompressed size, zero padding through
  offset `0x7ff`, and a standard zlib stream beginning at `0x800`;
- `portrait_cache.pak` stores the same inner archive directly, without the
  outer size, padding, or zlib stream;
- the inner archive begins with a big-endian member count followed by 268-byte
  records: a 256-byte NUL-padded name, a four-byte reserved field, a
  big-endian offset, and a big-endian size;
- every observed reserved field is zero, every member offset is `0x800`
  aligned, and compressed streams use zero padding to an `0x800` boundary; and
- all 63,170 member records have valid ranges. Twenty-nine archives contain
  duplicate names, accounting for 76 extra records. Every duplicate payload
  is byte-identical, but runtime lookup precedence has not been traced.

Four representative zlib archives were reproduced byte-for-byte with Python
zlib level 6 before restoring their original alignment padding. This is
format evidence, not proof that the game accepts an edited archive.

The current stager still permits only a complete package supplied by the user.
The checked-in gameplay inspector provides a bounded read-only reader,
malformed synthetic fixtures, and a full-corpus validation command. It does
not contain a writer, and no rebuilt package has been loaded by the running
game. A future writer must preserve member order, duplicate records, unknown
bytes, alignment, and unmodified payloads. It should emit complete replacement
archives into a mod rather than alter `private/game/`.

## Gameplay tables

SOX is a generic table format rather than an audio-specific format. The
investigation parsed 72 loose and 238 packed tables, representing 111 unique
contents. All 310 samples completed byte-identical parse/serialize round trips:

- offset `0x00` contains a preserved four-byte table key;
- big-endian column and row counts follow at offsets `0x04` and `0x08`;
- the header reserves 128 descriptors, each containing a 64-byte padded field
  name and a big-endian type;
- row data begins at fixed offset `0x220c`, with a sequential big-endian row ID
  at the start of every row;
- observed type 1 values are length-prefixed byte strings, while types 2 and 3
  are signed big-endian 32-bit integers; and
- a `THEND` footer and its variable padding must be preserved.

The ten language-specific `res_init*.pak` archives contain byte-identical
copies of fourteen central mechanics tables:

| Table | Observed data |
| --- | --- |
| `CHARDATA.SOX` | 100 unit definitions, resource paths, unit/troop types, scale, maximum level, level offsets, size, weight, sound, and crowd metadata |
| `ATTACKTABLE.SOX` | Enemy and friendly attack curves for 100 units |
| `DEFENSETABLE.SOX` | Defense curves and True Orb attenuation |
| `HPTABLE.SOX` | Enemy and friendly HP curves |
| `CRITICALTABLE.SOX` | Critical values and ratios |
| `ORBTABLE.SOX` | Orb Spark and experience values |
| `DEFENSEPROBTABLE.SOX` | Enemy, friendly, and hero defense probabilities |
| `LEVELMATCHINGTABLE.SOX` | Twelve level-matching slots per unit |
| `HEROTABLE.SOX` | Nine hero levels with movement speed, equipment slots, Orb consumption, guard stats, troop limits, and attack range |
| `TROOPTABLE.SOX` | Twelve troop levels with movement and range values |
| `ITEMTABLE.SOX` | 200 item rows with seven effect/value pairs, conditions, minimum level, hero restrictions, and item type |
| `ITEMLEVELTABLE.SOX` | Item-level availability |
| `ITEMDROPTABLE.SOX` | Item-drop probability data |
| `ITEMSETTABLE.SOX` | Item-set composition |

Additional loose tables expose 70 character ability rows with unlock levels
and localized move lists. Shipped source-like definitions expose nine
experience thresholds, kill/combo reward thresholds, item IDs, AI operations,
troop behavior, trigger parameters, animation signals, and UI control IDs.
It has not been established whether each loose authoring file is read at
runtime or is a leftover input whose values were compiled elsewhere.

The seven playable unit IDs can be correlated with Aspharr, Inphyy, Tyurru,
Klarrann, Myifee, Vigk Vagk, and Dwingvatt through character resources and
voice identifiers. Item descriptions correlate many effect IDs with maximum
HP, guard HP, attack, defense, Orb charging, drop rate, attack range, automatic
guard, and conditional effects. The complete effect-ID enum remains unnamed.

Compiled AI and mission resources are also information-rich but are not yet
safe editor targets. Unit `.aib` and `.ai_funcb` files retain function names,
parameters, includes, original source paths, target searches, level branches,
counterattacks, and troop commands. Stage groups contain attack scripts and
unit metadata in `*_res2_res.pak`, mission triggers in `*_res3_res.pak`, and
runtime/event sequences in `*_pak_res.pak`. The shipped trigger list names 52
conditions and 299 actions covering areas, HP, attacks, units, items, AI,
camera, sound, variables, and mission state. Binary layouts and runtime
semantics remain incomplete.

The read-only inspector now indexes the 39 relevant stage-resource archives.
It verifies and collapses 664 AIB instances to 95 logical programs, 350
AI-function instances to 19 modules, and 637 instances each to 85 attack
scripts and 85 unit-info files. Same-name payloads are identical on the
supported corpus; a conflict is treated as an error. Seventy-eight of 86 named
NPC definitions have a direct `<UNIT>_DEFAULT.AIB` match. Per-unit programs
compose shared functions and 47 of those 78 programs contain `iflevel`
branches, so this is composition rather than a single inherited template
pointer.

`CHARDATA.SOX` has a separate inheritance-like surface: five nonnegative
`Second Job Index` values resolve as zero-based row positions. The linked rows
still define their own resources and core fields, so the inspector presents
these as explicit job links rather than general record inheritance. Exact
shared assets, exact seven-table stat profiles, and inferred naming families
remain separate relationship classes.

The shipped debug-menu layout also defines two list boxes and matching debug
control IDs. No executable handler or activation path has been identified.

## Editor path

The first offline read-only inspector is implemented. It validates the
supported executable, both PAK variants, the core-table copies in all ten
`res_init*.pak` archives, and every displayed SOX table. Its visual views join
unit stat curves, hero progression, English item descriptions, item effect
slots, localized ability lists, NPC variant relationships, compiled AI
composition, and observed NPC attribute ranges while retaining raw tables and
duplicate headings. Structural JSON export omits row values and absolute
extraction paths.

The playable-hero view now distinguishes the nine direct `HEROTABLE.SOX`
progression levels from eleven stat-curve slots and the twelfth
level-matching-only slot. Hover guidance reports exact source fields,
interpretations, units, observed retail values, and independently supported
UI limits. It also corrects the five hero names that were previously
mismatched by joining hero and profile tables by row position. Observed ranges
remain evidence for editor controls, not validated write limits.

Launch it with:

```powershell
python tools\gameplay_inspector.py --game private\game
```

See [gameplay data inspector](GAMEPLAY-INSPECTOR.md) for the visual views,
headless report, full-corpus validation, tests, and extension boundaries.

A first writable release should limit changes to existing numeric SOX cells.
It should preserve schemas, row counts, strings, member order, duplicate
members, footers, alignment, and every unknown byte. Global-table changes
should be applied consistently to all ten `res_init*.pak` variants unless
language-selection tracing proves a narrower rule.

The first runtime experiment should alter one unmistakable, reversible value,
such as one hero's level-1 HP or movement speed, stage the rebuilt archives
through the existing mod system, and use an isolated profile. Successful
round trips and a surviving process do not establish that the game loaded the
changed value, that gameplay is correct, or that saves remain compatible.

Attack-script, AI, mission, spawn, map, and navigation editing should follow
only after their binary layouts have the same corpus, corruption-fixture, and
runtime-validation coverage. Save editing is a separate track: a historical
closed-source N3 save editor advertised a Max ORB operation, but no public
payload schema, offsets, checksum, or source code were found.

Public manuals and contemporary guides corroborate the seven characters,
level-9 cap, level-gated moves, red/blue Orb behavior, equipment stat domains,
and mission-result categories. They provide useful test cases, not binary
schemas. No credible public numeric enemy-stat table, N3 archive writer,
mission-spawn format, or open-source save editor was found during this
investigation.

## Localization data

The five PAL language slots contain a sheet-ready loose-text surface:

- 32 ordinary keyed tables plus one UTF-16BE dashboard table per slot;
- 3,849 matching numeric keys and 3,747 nonempty strings per slot;
- ASCII English and Windows-1252 French, German, Italian, and Spanish ordinary
  tables, all with CRLF line endings; and
- 280 two-field rows whose locale-specific texture, voice, or event companion
  must remain locked to the target slot.

The existing Graphics-menu integration already copies, extends, and mounts
these tables from a profile cache. This supports a first exporter/importer that
patches only the translated string span in a target template, preserves all
other formatting and metadata, and emits complete files beneath a normal
mod's `files/data/Text/<LANG>/` tree.

Additional localization is stored in seven briefing SOX files, seven
per-character ability SOX files, and two localized SOX members inside each PAL
`res_init<lang>.pak`. These expand the standard PAL sheet surface to 6,182
string cells per slot, about 4,850 of them nonempty. They require SOX and
eventually PAK writers before replacement. English also has one unmatched
generic ability table.

Thirty-two `.36t` interface textures per PAL slot contain baked labels. The
PAL initialization archives share the same English, Euro, and special font
atlases, and the observed text fits the current ASCII/Windows-1252 pipeline.
A complete new script or code page therefore needs texture, font, and runtime
decoding work in addition to translated sheets.

The complete inventory, proposed stable sheet keys, target-metadata rules,
validation policy, and staged implementation path are in
[localization data](LOCALIZATION.md). No localization exporter, importer, SOX
writer, PAK writer, texture writer, or edited-string runtime test exists yet.

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
