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
- eleven stat-curve slots plus a twelfth row used only by level matching;
- nine hero-progression rows for movement, accessory slots, Orb decrease,
  guard stats, troop groups, units per group, derived total guard capacity, and
  attack-range bonus; and
- every related raw field without renaming duplicate or unknown headings.

The unit list labels the raw `CHARDATA.SOX` value as `Unit MaxLevel` and shows
the separate nine-level hero progression explicitly. This avoids presenting
the playable rows' raw `MaxLevel = 1` as the player level cap.

Hover a hero-progression or stat-curve heading or value to see:

- the exact source table and numbered field family;
- the current value;
- the best-supported interpretation and units;
- all retail values observed across the seven playable rows;
- independently supported UI/schema limits; and
- the evidence and remaining runtime uncertainty.

The `enemy`, `friend`, and `hero` labels still reproduce table field names.
Friendly-side attack and HP are character-specific and are likely the
player/ally branch, but runtime branch selection and damage formulas have not
been traced.

#### Playable hero identity

`HEROTABLE.SOX` order does not match `MENULIBCHARINFO_ENG.SOX` order. Joining
those tables by row position mislabeled five characters. The inspector now
uses the supported build's internal unit identities, corroborated by character
resources and voice identifiers:

| Internal unit | Hero |
| --- | --- |
| `C_LP_KM` | Aspharr |
| `C_LP_KF` | Inphyy |
| `C_LP_MF` | Tyurru |
| `C_LP_PM` | Klarrann |
| `C_LP_WM` | Myifee |
| `C_DP_TR` | Vigk Vagk |
| `C_DP_GB` | Dwingvatt |

#### Hero progression fields

| Field family | Retail hero values | Interpretation and limits |
| --- | --- | --- |
| `MoveSpeed1..9` | 100-160 in steps of 5 | Percentage-like movement scale with 100 as the retail baseline. Item movement bonuses use percentage points; engine-safe bounds are unknown. |
| `SlotCount1..9` | 1-5 | Unlocked accessory slots. The weapon is separate, and the shipped status UI defines exactly five accessory controls. |
| `OrbDecrease1..9` | 100 only | Orb gauge decrease/consumption scalar by name. Formula, direction, and non-100 behavior remain untraced. |
| `GuardianDefense1..9` | 65, 70, 76, 84, 94, 106, 120, 136, 154 | Base guard-unit defense stat. Retail item text independently identifies Guard defense modifiers. |
| `GuardianHP1..9` | 810, 891, 980, 1078, 1186, 1305, 1435, 1578, 1725 | Base guard maximum-HP stat. Whether this is per-unit or a shared pool remains untraced. |
| `GuardianControlTroopCount1..9` | 1-2 | Independently controlled guard groups. The shipped UI has separate left and right Guardian screens. |
| `GuardianControlTroopUnitCount1..9` | 15, 18, 24, 30, 36, 42, 50 | Units assigned to each guard group. The value resets when a second group unlocks, supporting the per-group interpretation. |
| Derived total guard units | 15, 18, 24, 30, 36, 48, 60, 72, 84, 100 | Display-only multiplication of group count by units per group; not a separate SOX field. |
| `AttackRange1..9` | 0, 5, 10, 15, 20 | Innate percentage-point range bonus. Retail items use the same unit and can exceed 20, so 20 is not an engine cap. |

Only hero level 1-9, accessory count 1-5, and troop-group count 1-2 have
independent schema or UI support as domains. Every other number is labeled as
an observed retail value, not a validated edit range.

The core attack, defense, HP, critical, Orb, and defense-probability tables
provide eleven numbered slots. `LEVELMATCHINGTABLE.SOX` alone provides twelve.
Playable rows map slots 1-9 directly and map slots 10-12 back to level 9.
Therefore the grid now calls these rows **curve slots**, not hero levels.
Playable `ORBTABLE.SOX` EXP values are all zero and are not the hero level-up
thresholds.

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

The fifteen tests include playable-identity joins, retail-range guide
generation, and exclusion of nonhero rows from hero ranges. The fixtures
contain no retail game bytes.

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
