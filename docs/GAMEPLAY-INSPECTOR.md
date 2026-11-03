# Gameplay data inspector

The gameplay inspector is a dependency-free, read-only Python/Tkinter
application for exploring a user-owned N3 extraction. It decodes the verified
PAK container variants and SOX tables without changing the extraction.

## Launch

Python 3.10 or newer with Tcl/Tk support is required. The standard Windows
Python installer includes Tcl/Tk by default.

From the repository root:

```powershell
python tools\gameplay_inspector.py
```

The application automatically offers `private\game` when that extraction
exists. Choose another extraction explicitly with:

```powershell
python tools\gameplay_inspector.py --game 'D:\Games\N3'
```

The selected folder must contain `default.xex` and
`data\PackedResources\res_init.pak`. A missing or mismatched executable is
reported prominently, but the read-only table view remains available for
format research.

## Views

### Overview

The overview displays:

- the supported executable SHA-256 result;
- the `res_init.pak` container variant and member counts;
- loaded SOX table counts grouped by category;
- the comparison result for all ten language-specific `res_init*.pak`
  archives; and
- explicit warnings and validation limits.

### Units and stats

The unit view joins `CHARDATA.SOX` with related unit-keyed tables. It presents:

- all 100 unit definitions;
- playable character names where they can be correlated with the English menu
  table;
- identity, resource, scale, type, level, sound, and physical fields;
- twelve visible level rows spanning attack, defense, HP, critical, Orb,
  experience, defense probability, True Orb attenuation, and level matching;
- nine hero-progression rows for movement, slots, Orb use, guard stats, troop
  limits, and attack range; and
- every related raw field without renaming duplicate or unknown headings.

The `enemy`, `friend`, and `hero` labels reproduce table field names. The
application does not infer damage formulas, units, or runtime ownership.

### Items

The item view joins the 200 `ITEMTABLE.SOX` rows with
`ITEMDESC_ENG.SOX`. It displays English names and descriptions, minimum level,
hero/type restrictions, all seven effect ID/value slots, conditions, and the
complete raw record. Effect IDs remain numeric until their meanings are
independently verified.

### Abilities

The ability view combines localized per-character move tables for English,
French, German, Italian, and Spanish. Character, unlock level, move name,
command text, caption, and source table remain visible. This describes
available data; it does not establish that changing a localized table would
change move behavior.

### All tables

The generic browser exposes every SOX table in `res_init.pak` plus every loose
SOX table beneath `data/`. Tables are grouped by observed purpose, support
text filtering, preserve duplicate column headings with occurrence numbers,
and show a vertical field/value view for wide rows.

## Structural report

Use **File > Export Structural Report** to write deterministic JSON containing
schemas, counts, hashes, archive comparisons, and warnings. It intentionally
omits row values and absolute extraction paths.

The same operation is available without opening the UI:

```powershell
python tools\gameplay_inspector.py `
  --game private\game `
  --report out\n3-gameplay-structure.json
```

The report is a local diagnostic artifact. Do not commit reports derived from
an extraction unless their contents have been reviewed for the intended use.

## Corpus validation

Run the bounded readers against every local packed resource and SOX table:

```powershell
python tools\gameplay_inspector.py `
  --game private\game `
  --validate-corpus
```

For the supported owned extraction, the checked-in reader validates:

| Property | Result |
| --- | ---: |
| PAK archives | 522 |
| Zlib-wrapped / raw archives | 521 / 1 |
| PAK members | 63,170 |
| Archives with duplicate names | 29 |
| Extra duplicate records | 76 |
| Non-identical duplicate-name payload groups | 0 |
| Packed / loose SOX tables | 238 / 72 |
| Total / unique SOX contents | 310 / 111 |

Validation rejects unsupported reserved values, unaligned or out-of-range PAK
members, invalid zlib sizes or trailing data, unsupported SOX types, malformed
descriptor padding, impossible row counts, nonsequential row IDs, truncated
strings, and missing footers.

## Implementation

The application is intentionally split into two modules:

- `tools/n3_gameplay_data.py` contains bounded PAK/SOX readers, typed data
  models, joins for units/items/abilities, build and variant checks, structural
  report generation, and full-corpus validation.
- `tools/gameplay_inspector.py` contains the Tkinter presentation and command
  line entry point.

The UI consumes typed read-only models rather than archive byte offsets.
Future editing should be a separate layer with explicit write models,
round-trip preservation, output validation, and mod-folder publication.

Run the synthetic regression suite with:

```powershell
python -m unittest tools.n3_gameplay_data_test
```

The fixtures contain no retail game bytes.

## Current boundary

The inspector does not:

- edit a SOX value or write a PAK;
- alter `private\game`, a staged game, saves, or profiles;
- prove which language-specific archive the runtime selects;
- assign meanings to unnamed item-effect IDs;
- decode attack, AI, mission, map, navigation, or save payloads; or
- establish that an observed field is loaded, writable, or save-compatible at
  runtime.

The next safe milestone is a separate numeric SOX editing model that preserves
all schemas, strings, duplicate archive records, unknown bytes, footers, member
order, and alignment, then writes complete replacement archives into a normal
mod folder. Its first result must be validated with one reversible, visible
stat change and an isolated profile.
