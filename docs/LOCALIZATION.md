# Localization data

## Feasibility

Most N3 text is data-driven and can be represented as localization sheets.
The loose `data/Text` tables are the safest first replacement target:

- all five PAL language slots use the same logical files, numeric keys, and
  row order;
- their record grammar and encodings are understood;
- the existing Graphics-menu integration already copies, extends, and mounts
  these files from a profile cache without modifying the owned extraction; and
- the offline mod stager can replace the resulting complete loose files.

The remaining text is also structurally suitable for sheets, but writing it
requires SOX serialization and, for two tables, complete PAK rebuilding.
Thirty-two localized interface textures per PAL slot contain additional baked
labels that a text-only workflow cannot replace.

The standard PAL surfaces contain 6,182 string cells per language slot. About
4,850 are nonempty, with small differences caused by briefing line wrapping.

| Surface | Per PAL language slot | Observed format | Stable sheet key | Replacement status |
| --- | ---: | --- | --- | --- |
| UI, dialogue, subtitles, objectives, and system text | 3,849 rows in 33 loose files; 3,747 nonempty | 32 single-byte text tables plus one UTF-16BE dashboard table | logical file plus numeric text ID | Sheet-ready; exporter/importer not implemented |
| Mission briefings | 1,120 string slots in seven loose SOX files; 279-286 nonempty | SOX `_Text` byte strings | logical file plus SOX row ID plus field | Needs a SOX writer and runtime test |
| Character abilities | 771 string cells in 257 rows across seven loose SOX files; 514 nonempty | SOX `_Name`, `_Command`, and `_Caption` byte strings | logical file plus SOX row ID plus field | Needs a SOX writer and runtime test |
| Item descriptions and character profiles | 442 string cells in two localized SOX members; 310 nonempty | `ITEMDESC_<LANG>.SOX` and `MENULIBCHARINFO_<LANG>.SOX` inside `res_init<lang>.pak` | logical table plus SOX row ID plus field | Needs SOX and PAK writers |
| Baked interface labels | 32 `.36t` files | Texture data | logical texture name | No texture writer |

English also has a 70-row generic `abilitylocaltable_eng.sox` with no
equivalent in the other PAL folders. It should be treated as an English-only
surface rather than forced into the shared 257-row character-ability sheet.

## Loose text tables

The PAL slots are `ENG`, `FRA`, `GER`, `ITA`, and `SPA`. Each contains 32
ordinary tables and one `dashboardutf16_<lang>.txt` table.

Ordinary records have one of these forms:

```text
123 "Translatable text"
124 "Translatable text", "_LOCKED_TEXTURE_OR_CUE"
```

The complete loose corpus has 3,569 one-field records and 280 two-field
records per language. The first quoted field is translatable. The optional
second field commonly identifies a texture, voice cue, event, or another
locale-specific resource and must remain locked to the target language's
template.

The ordinary English files contain ASCII. The French, German, Italian, and
Spanish files use Windows-1252. All use CRLF line endings. Dashboard tables
have a UTF-16BE byte-order mark, use CRLF after decoding, and contain 27 keyed
records each.

The parser must also retain:

- blank lines and `//` comments;
- whitespace before and between fields;
- file and row order;
- empty strings;
- the target file's encoding, byte-order mark, and line endings; and
- the target slot's companion field rather than the source slot's value.

This is not strict RFC CSV syntax. Some records contain whitespace between the
closing quote and comma. No literal or escaped double quote was found inside a
field, so an importer should reject quotes until an actual game escape syntax
is established.

All five language slots have matching logical filenames, numeric key
sequences, and field counts. Comments are not stable across languages and
must not be used as keys. Companion values also differ in a few retail rows,
which is why copying a complete English row into another language is unsafe.
`defaulttexttabledefine.h` supplies symbolic context for 148 default-table
IDs, but the numeric ID remains authoritative.

The strings contain game markup, controller icons, literal `\n` line breaks,
and a small number of printf-like placeholders. Retail translations
legitimately change markup placement and line wrapping, so exact token and
line-break parity should produce review warnings rather than blanket
rejection. Malformed markup, unsafe format-placeholder changes, and
unencodable output should fail validation.

## Proposed sheet contract

The first tool should export one sheet for a selected source and target PAL
slot. A UTF-8-with-BOM CSV is sufficient as a canonical exchange format if
spreadsheet applications import every column as text. Many game strings begin
with `@`, so double-clicking a CSV in software that interprets formula-like
prefixes is not a safe editing workflow. A later XLSX frontend should mark all
cells explicitly as strings.

Recommended columns are:

| Column | Purpose |
| --- | --- |
| `surface` | `loose_text`, `briefing`, `ability`, `item`, or `profile` |
| `logical_table` | Locale-neutral file or table name |
| `row_id` | Numeric text ID or preserved SOX row ID |
| `field` | `text`, `_Text`, `_Name`, `_Command`, `_Caption`, `Name`, or `Desc` |
| `symbol` | Optional authoring symbol such as a default-table define |
| `context` | Read-only filename, character, mission, or field context |
| `source_language` | Language slot used for source text |
| `target_language` | Language slot whose files and metadata will be rebuilt |
| `source_text` | Read-only source string |
| `translation` | Editable target string |
| `locked_target_metadata` | Read-only companion string or numeric metadata |
| `status` | Explicit workflow state so an empty translation is not ambiguous |

A versioned companion manifest should record the supported game build, sheet
schema, selected language slots, every input relative path, and SHA-256 hashes.
An importer must reject a stale or mismatched target template instead of
silently applying keys to different files.

Sheet rows are keyed by `surface + logical_table + row_id + field`, never by
row number or source text. Import should reject duplicate and unknown keys.
A strict release build should also require an explicit status for every
expected key, including intentionally empty strings and rows that retain the
target text.

## Safe loose-text build

A first importer does not need to normalize or regenerate the source files.
It can patch only the first quoted-field span in each target template and
leave every other byte-level convention intact:

1. verify the build and target-template hashes from the sheet manifest;
2. parse all expected target keys and reject duplicates or malformed records;
3. validate translations for quotes, encoding, markup syntax, and format
   placeholders;
4. replace only the first quoted value while preserving comments, whitespace,
   order, line endings, byte-order marks, and target companion fields;
5. encode ordinary files according to the target slot and dashboard files as
   UTF-16BE;
6. write complete files atomically beneath
   `mods/<id>/files/data/Text/<LANG>/`; and
7. stage the mod through the existing launcher, never by editing
   `private/game/`.

Length expansion, changed game-markup tokens, changed literal line-break
counts, and likely UI overflow should be reported for review. They cannot all
be hard errors because the shipped PAL translations already differ in these
ways.

For a new translation, repurposing one existing PAL slot is the lowest-risk
route. Adding a sixth slot also requires runtime language-selection and
resource-name changes. The English slot uses the English font path, while the
four European slots share a Euro font atlas; therefore an accented translation
should normally target one of the Euro slots.

## SOX localization

The seven briefing files per PAL slot use `_TextId` and `_Text` columns.
Their file coverage and SOX row IDs align, but `_TextId` values can differ
because retail languages split and omit wrapped lines differently. A sheet
must use the actual SOX row ID as its identity and preserve the target slot's
`_TextId`.

The seven per-character ability files expose `_Level`, `_Name`, `_Command`,
and `_Caption`. Their 257 row IDs and numeric levels align across PAL slots.
Only the three string fields are localization cells; `_Level` remains locked.

All localized SOX strings examined in the PAL files decode as Windows-1252.
The read-only gameplay codec understands their schemas, row IDs, and string
lengths, but it intentionally has no checked-in writer. A writer should first
pass byte-identical no-op round trips against every loose and packed SOX
sample before it is allowed to emit a mod.

## Packed item and profile text

Each PAL `res_init<lang>.pak` has 206 members and 23 SOX tables. Only two of
those tables vary for PAL localization:

- `ITEMDESC_<LANG>.SOX`: 200 rows with `Name` and `Desc`; and
- `MENULIBCHARINFO_<LANG>.SOX`: seven rows with six localized string fields.

These account for 442 string cells per slot. The mechanics, library, sound,
and item-mechanics members compared across the five PAL archives are
unchanged. Replacing the localized members still requires rebuilding the
complete PAK because changed string lengths move later SOX data and can change
member offsets.

A PAK writer must preserve member order, duplicate records, reserved bytes,
alignment, unchanged member payloads, compression behavior, and archive
padding. Structural reproduction alone does not prove the game accepts an
edited archive.

## Baked labels and fonts

`data/interface/Local/<LANG>/` contains the same 32 logical `.36t` filenames
for every PAL slot. They include menu text atlases, mission and result labels,
map names, and character-name artwork. A complete new-language release needs
translated versions of these textures or a runtime replacement for their
baked labels. No `.36t` writer is implemented.

The five PAL texture initialization archives contain byte-identical
`FONT_0_ENG.36T`, `FONT_0_EURO.36T`, and `FONT_SPECIAL.36T` payloads. The loose
Euro mapping covers byte positions through 255 and is consistent with the
observed Windows-1252 text. This supports the existing PAL character set; it
does not establish visual coverage for another code page or script.

Languages outside the existing single-byte repertoire need font-atlas,
mapping, and likely text-decoding changes in addition to translated sheets.
The UTF-16 dashboard table alone does not make the rest of the localization
pipeline Unicode-capable.

## Validation boundary and staged plan

The existing PAL language setting and both hooked `XGetLanguage` call sites
select among English, German, French, Spanish, and Italian after restart. The
Graphics-menu implementation demonstrates that generated copies of the loose
Text tables can be mounted and consumed without changing the extraction. It
does not prove every translated surface, arbitrary string length, or a new
language slot.

Recommended milestones are:

1. export, validate, and rebuild the 3,849 loose keyed rows for an existing
   PAL slot;
2. stage one reversible string change with an isolated profile and verify it
   visually through restart and reload;
3. add a bounded SOX writer for briefing and ability sheets;
4. add complete PAK rebuilding for item and profile sheets;
5. decode and author the 32 localized textures; and
6. extend fonts and runtime decoding only when a target language requires it.

No owned game data should be edited or distributed. A successful sheet
round-trip, build, or surviving process does not establish visual fit,
correct markup, gameplay correctness, save compatibility, or complete
localization coverage.
