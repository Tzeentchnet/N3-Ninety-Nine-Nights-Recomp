# Blender asset authoring roadmap

## Status and selected scope

The separate N3 Blender project's **0.14.0 read-only baseline**, recorded on
2 November 2026, targets Blender 5.2 and implements eight bounded import
operators. Package members are read in memory, not extracted. Redistributable
tests use synthetic fixtures. There is no exporter or native N3 writer, and
the recomp stager does not consume the optional Blender receipt. The visual
and in-game/runtime acceptance gates below remain unmet; an import or a
structurally valid reader is not proof of game-correct presentation. This is a
named historical baseline, not a claim about a later working tree or release.

The companion source manifest is now the **0.14.1 ungated candidate**,
with nine read-only imports and zero exports. The ninth operator creates only
an explicitly selected, detached attachment diagnostic; it does not infer a
character, socket, local transform, parent, or constraint. The manifest has
49 explicit shipped paths and 50 archive files including the implicit
manifest. Blender 5.2.2 synthetic source/save-reopen smoke passed and a
private deformation preview ran on the validated integration changes, not as
clean-pinned stable release acceptance. Add-on commit
`e90f41354eb40ecf941a11114ad4ba82a1ee54ae` produced a Blender-built
`0.14.1` ZIP with SHA-256
`0efe0f874de65018af383e132f67aee9a4dc2cfe0aa37a1720b91c57147cea8e`;
the exact archive passed source/archive verification, isolated installation,
synthetic import, and save/reopen. This permits GitHub prerelease distribution
only; the remaining corpus, visual, runtime, writer, staging, and in-game gates
still block stable approval. CI runs synthetic Python and packaging checks,
not Blender or the private corpus. The current stager still ignores the
optional receipt.

The latest local lane passed 456 synthetic tests per Python interpreter.
Hosted [run 41683738344](https://github.com/Tzeentchnet/N3_Blender/actions/runs/41683738344)
passed 316 tests in each Ubuntu 24.04 and Windows 2022 Python 3.13 job for
add-on commit `fd27105854501f2edd701c71f01a9578b78a53bd` with zero artifacts.
That historical 41-file packaging run does not cover later integration
changes, Blender, or private-corpus acceptance.

The companion's source-only
`docs\snapshots\character-animation-0.14.0.json` is the version-1 aggregate
character snapshot (SHA-256
`dfebfcd60b38d090b6cca0d36ffc8286712714d3be0ceacc308946563b28240a`).
Two checks matched with identical 103-byte comparison JSON (SHA-256
`3b0a36d794e247105482c80952a14a90626630af5b6d6ad23b338f1d2999c02b`).
They classify 36 character pairs, 3,121 candidates, and 67 unique animation
payloads: 49 accepted, 11 with trailing data, and seven outside the current
inverse-bind profile. Its `complete` field means discovery and classification,
not full release, writer, visual, or in-game approval. To repeat the
read-only check from the companion source checkout:

```powershell
Set-Location '<addon-source-checkout>'
python -B tools\character_corpus_report.py '<owned-packed-resource-root>' --check docs\snapshots\character-animation-0.14.0.json
```

The original snapshot comparison used this repository at HEAD
`62ebd5c139ff9bd169dd3b8eca7c9cd5bb5c0a16`; an earlier closeout used
`74897d56dfc9ed853a752a4ffd853040d63526a4`. This integration lane began from
clean base revisions add-on `fd27105854501f2edd701c71f01a9578b78a53bd` and
recomp `bc062b2b7b148ae5f53cf14bfc69464f1ada2d37`; the current changes were
validated on top and are not included in those hashes. They are not release
pins; the companion release procedure requires a clean, explicitly pinned
recomp commit and the remaining applicable format-corpus gates.

The companion's completed/partial/blocked evidence matrix and detailed
`docs/RUNTIME-ANIMATION.md`, `docs/ROOT-MOTION.md`, and
`docs/ATTACHMENT-EVIDENCE.md` distinguish source inventories, preview
regressions and runtime acceptance. Six parser-eligible animation/model pairs
cover 71 candidate occurrences. A private Blender comparison measured all
six and 54 selected samples: bone preview max and per-bone RMS thresholds
passed, while the result remains `preview-regression-only`. Vertex units are
unverified; metre and release approval are false. Exact per-profile residuals
and hash identities are in the
companion roadmap; this is not visual or runtime conformance. The rechecked
root snapshot covers 49 strict payloads and 565 occurrences (SHA-256
`9335eeecb6416167979dbfcf21bc1ed441ee466a4b696496e491ebf5822a090b`);
runtime actor/root/child transforms and loop policy remain unknown. The 44
item-to-weapon matches are inferred name-based candidates, with no proven
equipped actor, socket, local transform or attachment parenting. Occurrence
inventory v2 and the explicitly selected detached preview retain ambiguity;
unresolved assets remain unparented.

The bounded signal study in `docs/NATIVE-CODE.md` found 85 AS payloads with
4,300 groups and 18,477 records, and 86 heuristic BA/AS/INFO triples; a
same-row static path is not a live member/actor/effect binding. The next
discriminating experiment must correlate resolver-selected members, actor,
row, dispatch and an independently observed effect for at least two
characters. Pure AS-101/INFO-100 readers and synthetic bounds/preservation
tests now exist, but no record is linked to a live actor/clip/effect. Keep
`Clip_###`, `source_fps_unverified`, no notify markers,
no root extraction, and the 11 trailing/seven inverse-bind rejections until
their separate gates pass.

The `n3-blender-baseline` HTML comment is a machine-readable documentation
snapshot checked against the add-on. Its receipt-schema fingerprint is the
SHA-256 of UTF-8 JSON with sorted keys, compact separators, and unescaped
non-ASCII characters. It is not an export receipt or a stager input.

<!-- n3-blender-baseline
{
  "marker_version": 1,
  "addon_version": "0.14.1",
  "blender_minimum": "5.2.0",
  "read_only": true,
  "import_operator_count": 9,
  "import_operators": [
    "import_scene.n3_bm",
    "import_scene.n3_skin",
    "import_scene.n3_character_package",
    "import_scene.n3_static_resource_package",
    "import_scene.n3_bsmap_terrain_package",
    "import_scene.n3_level_package",
    "import_scene.n3_navigation_package",
    "import_scene.n3_camera_package",
    "import_scene.n3_detached_attachment"
  ],
  "package_members": "in-memory",
  "redistributable_fixtures": "synthetic",
  "exporter": false,
  "native_writer": false,
  "recomp_receipt_consumer": false,
  "receipt_schema_version": 1,
  "receipt_schema_sha256": "90875ac34aaca8d7a81524b6215582900b7da7d707951738de808e98fdb5855b",
  "visual_gates_passed": false,
  "runtime_gates_passed": false
}
-->

| Read-only import | Operator |
| --- | --- |
| Loose model `.bm` | `import_scene.n3_bm` |
| Loose model descriptor `.skin` | `import_scene.n3_skin` |
| Rigged character package | `import_scene.n3_character_package` |
| Static resource package | `import_scene.n3_static_resource_package` |
| Terrain package | `import_scene.n3_bsmap_terrain_package` |
| Level package | `import_scene.n3_level_package` |
| Navigation package | `import_scene.n3_navigation_package` |
| Camera package | `import_scene.n3_camera_package` |
| Detached attachment diagnostic | `import_scene.n3_detached_attachment` |

The companion's local corpus reports bounded parsing of all 187 loose `.bm`
and 216 loose `.skin` files and mip-zero previews of 1,047 loose `.36t` files.
Its supported package profile covers 521 packages and 63,127 entries;
`portrait_cache.pak` is a different, rejected profile. These are reported
structural results, not newly reproduced in this update or visual/runtime
approval. The add-on's `tests/test_package.py` exercises synthetic package
lookup, ambiguity, and malformed inputs; `tests/blender_smoke.py` checks all
nine registrations and synthetic imports with scene save/reopen. The
companion runs them with `python -m unittest discover -s tests` and
`tools/test_blender.ps1`, respectively.

Character imports offer no Actions, representative candidates, selected
zero-based clip indices/ranges, or all supported source clips. Direct
selected/all Actions use neutral `Clip_###` names; representative labels are
motion-based candidates, not proven game names. Timing, interpolation, signal
payload-to-clip linkage, multi-character deformation, and evidence-backed
attachments remain active research. Do not create event markers or bone
parenting from schema vocabulary or names alone.

The original milestone order was:

1. read-only `.skin` dependency inspection and `.bm` model import;
2. read-only `.36t` texture preview after model structure is established;
3. constrained loose-asset export only after reader and round-trip gates pass;
4. bounded read-only `.pak` research after the loose-asset path works;
5. no package writer until the complete container format is verified.

Bounded package reading already exists despite that original ordering; the
remaining acceptance work is not a request to implement it from scratch.
The read-only milestones deliberately exclude export. A Blender scene that
looks plausible is not evidence that an N3 writer is safe.

## Repository boundary

| Surface | Responsibility |
| --- | --- |
| N3 Blender project | Pure-Python binary readers, Blender 5.2 adapters, import UI, future constrained writers, and headless tests |
| N3 recomp project | Supported-game identity, owned local corpus, mod path rules, offline staging, runtime launch, and in-game validation |
| Mod source folder | Author-owned replacement payloads under `files/data/`, `mod.toml`, and an optional authoring receipt |
| `out/game/` | Disposable runtime stage produced only by `tools/mods.py`; never an authoring destination |

Format code must not depend on `bpy`. Blender operators translate between the
codec's typed intermediate representation and Blender data blocks. This keeps
bounds checks, endianness, dependency resolution, and serialization testable
with ordinary Python and Blender's background mode.

The add-on may read owned assets from a user-selected extraction. It must never
copy retail fixtures, decoded raw chunks, or generated game data into its
repository. Synthetic fixtures and aggregate structural metadata are the
portable test boundary.

## Observed loose-model corpus

A read-only local scan of the verified owned extraction produced these
**Observed** facts:

| Property | Observation |
| --- | ---: |
| Loose `.bm` files | 187 |
| Loose `.skin` files | 216 |
| Same-relative-stem `.bm` / `.skin` pairs | 162 |
| `.bm` size, minimum / median / maximum | 48 / 12,510 / 493,717 bytes |
| `.skin` size, minimum / median / maximum | 130 / 297 / 2,429 bytes |
| `.skin` files with a NUL-terminated `.bm` reference | 216 of 216 |
| `.skin` files containing an `.fx` reference | 216 of 216 |
| `.skin` files containing a `.dds` reference | 205 of 216 |

Each loose `.skin` sample contained exactly one NUL-terminated `.bm` reference.
Of those 216 references, 168 matched the `.skin` basename and 173 matched the
basename of some loose `.bm`. The remaining references may use a variant name,
refer to packed data, or require another lookup rule.

These strings support an **Inferred** dependency/material-descriptor role for
`.skin`. They do not establish record boundaries, effect semantics, texture
lookup rules, bone data, weights, or animation binding. In particular, the
extension name is not evidence that `.skin` should become a Blender armature.

## Data flow

```text
owned extraction (read only)
        |
        v
pure codec -> typed asset graph -> Blender adapter -> Blender scene
                                                    |
                                      future constrained exporter
                                                    |
                                                    v
mods/<id>/
  mod.toml
  n3-blender-export.json
  files/data/...              author-owned replacement outputs
        |
        v
tools/mods.py validate -> tools/mods.py stage -> out/game/ -> launch
```

The diagram shows a future authoring layout, not a receipt-consumption path:
the stager reads `mod.toml` and payloads beneath `files/data/`, but does not
read, validate, or stage the receipt beside `mod.toml`.

The typed asset graph should retain:

- normalized game-relative source paths and source SHA-256 values;
- explicit byte order and format-profile version;
- meshes, streams, indices, material slots, and dependency edges only when
  their layouts are verified;
- unknown ranges as bounded opaque records when they can be preserved safely;
- warnings and unsupported features as explicit diagnostics, never silent
  defaults.

Host absolute paths, Blender object names, and UI selection state are not game
asset identities.

## Milestones and acceptance gates

### 0. Corpus inspector and codec foundation

Bounded readers and synthetic fixtures exist independently of Blender UI code.
The companion reports loose `.bm` and `.skin` corpus parsing; the following
checks remain the acceptance criteria, not a claim that every gate is closed.

- Use checked reads for every integer, count, offset, range, and multiplication.
- Make byte order explicit at each field; do not infer it from the host.
- Reject truncation, overlap, impossible counts, and ranges outside the file.
- Emit deterministic structural summaries without embedding retail bytes.
- Run the reader over all 187 loose `.bm` and 216 loose `.skin` files locally.
- Keep synthetic malformed fixtures for every rejected boundary in source
  control.

**Exit gate:** every loose sample is either classified successfully or rejected
with a stable, specific reason. A crash, unbounded allocation, partial
success, or catch-all fallback fails the milestone.

### 1. Read-only `.skin` dependency inspection

Read-only descriptor inspection and import exist. Treat `.skin` as a
dependency descriptor, not as skeletal data; unresolved dependencies and
unverified secondary material structures remain explicit.

- Locate and validate the observed `.bm`, `.fx`, `.dds`, and occasional `.bmp`
  references.
- Preserve original spelling while resolving paths case-insensitively with the
  same Windows rules used by the mod stager.
- Report unresolved and ambiguous references.
- Identify record boundaries and unknown ranges before assigning field names.
- Expose material/effect references to Blender as metadata or placeholder
  nodes; do not invent shader semantics.

**Exit gate:** all 216 loose files parse without out-of-bounds reads, each
observed `.bm` dependency is represented exactly once, and unresolved lookups
remain visible to the user.

### 2. Read-only `.bm` mesh import

Read-only geometry import exists, but these interpretations still require
evidence before they can become writer invariants:

- stream count, stride, offsets, and vertex count;
- index width, primitive topology, winding, and restart behavior;
- position scale and coordinate handedness;
- normal/tangent packing and normalization;
- UV component encoding and vertical origin;
- submesh, material-slot, bounds, LOD, collision, and morph relationships.

Import source identity, profile version, and unresolved fields as namespaced
custom properties. Do not expose an export operator during this milestone.

**Exit gate:** representative `Fx`, `Prop`, `Sky`, and root assets have
structural summaries that agree with imported Blender counts and bounds.
Multiple viewpoints and an in-game reference capture are required before
calling orientation, scale, normals, or UVs verified. Full-corpus parsing must
still pass.

### 3. Read-only `.36t` texture preview

Read-only mip-zero previews exist for the supported profiles. Complete
texture, color-space, and in-game presentation semantics remain unverified.

- Verify dimensions, format, mip count and offsets, array/cube semantics,
  endianness, Xbox 360 tiling, and block-compression handling.
- Resolve how `.dds` names observed in `.skin` map to loose `.36t` paths.
- Decode to an in-memory Blender image or a disposable cache outside the game
  and mod trees.
- Retain source color-space and alpha assumptions as explicit metadata.

**Exit gate:** decoded dimensions and mip ranges are valid across the loose
corpus, representative previews match captured game presentation within known
color-space limits, and corrupt synthetic inputs fail closed. No encoder is
implied.

### 4. Constrained loose-asset export

No native writer or export operator exists. Enable one only for a named
profile whose fields are understood. Start with the smallest static-mesh
subset; do not begin with arbitrary skinned characters.

- An unedited parse/serialize cycle must be byte-identical for every sample in
  the profile's local corpus.
- Modified output must reparse, satisfy every range/count invariant, and avoid
  truncating or relocating unknown data unless that relocation is verified.
- Reject unsupported topology, attributes, material edits, limits, and
  dependency changes before writing.
- Write atomically into `mods/<id>/files/data/...`; never write to the owned
  extraction or `out/game/`.
- Generate the versioned receipt described below.

**Exit gate:** synthetic writer tests, private-corpus round trips, output
reparse, mod validation, staging, and an isolated in-game visual route all
pass. Export success does not by itself establish animation, collision,
effects, or gameplay correctness.

### 5. Staging and runtime validation

For each future exported asset set:

1. run `python tools/mods.py validate`;
2. stage with `python tools/mods.py stage --replace`;
3. retain the staged `.n3-mods.json` and the Blender receipt separately beside
   the mod's `mod.toml`; the current stager does not consume the receipt;
4. launch with an isolated user/cache root;
5. compare an unmodified export against the original route first;
6. test the edited asset from all relevant camera distances and effects states;
7. reproduce any failure without the mod before changing the runtime.

File-level load order remains the only merge policy. Two mods editing different
semantic records inside the same file still conflict at the whole-file level.

### 6. Read-only packed-resource research

The add-on already has a bounded `.pak` reader and reads package members in
memory; generic package extraction is not implemented. Any future extraction
research must retain the corruption, duplicate-name, normalized-path,
decompression-limit, and range checks listed in [Modding](MODDING.md).

Do not add a package writer merely because entries can be listed. Deterministic
alignment, compression, metadata, checksums, duplicate behavior, and
byte-identical unmodified reconstruction are separate gates. A runtime overlay
may ultimately be safer than repacking.

## Versioned Blender handoff

The future exporter writes `n3-blender-export.json` beside `mod.toml`. Version 1
is defined by
[`schemas/n3-blender-export-v1.schema.json`](schemas/n3-blender-export-v1.schema.json).
The receipt is metadata only and is not placed beneath `files/`, so the current
stager does not copy it into the game tree.

The receipt binds:

- the mod ID;
- the exact title, media, executable version, and XEX SHA-256;
- producer, add-on, and Blender versions;
- a versioned format profile for each exported asset set;
- game-relative source and output paths, roles, and SHA-256 values;
- the exact capabilities claimed by the exporter;
- unknown-data preservation policy and validation results;
- explicit limitations.

Hypothetical example shape, using placeholder hashes and a fictional producer
version; it is not an output from the 0.14.0 baseline:

```json
{
  "schemaVersion": 1,
  "modId": "author.example-model",
  "target": {
    "titleId": "4D5307DB",
    "mediaId": "5D48689C",
    "version": "0.0.0.3",
    "xexSha256": "0fe8973b6ff45d3f8bd03a51a8c0d8cdf278b3d43e793497777e075f4e94a804"
  },
  "producer": {
    "id": "n3-blender",
    "version": "0.1.0",
    "blenderVersion": "5.2.0"
  },
  "exports": [
    {
      "id": "prop.example",
      "kind": "loose-model-set",
      "profile": "n3.loose-model.static-v1",
      "sourceFiles": [
        {
          "path": "data/Prop/example.bm",
          "role": "model",
          "sha256": "1111111111111111111111111111111111111111111111111111111111111111"
        }
      ],
      "outputFiles": [
        {
          "path": "data/Prop/example.bm",
          "role": "model",
          "sha256": "2222222222222222222222222222222222222222222222222222222222222222"
        }
      ],
      "capabilities": [
        "mesh.positions",
        "mesh.indices",
        "mesh.uv0"
      ],
      "preservation": "opaque-sections-preserved",
      "validation": {
        "sourceParse": "complete",
        "unmodifiedRoundTrip": "byte-identical",
        "outputReparse": "complete"
      },
      "limitations": [
        "Static triangle-list profile; no armature or material edits"
      ]
    }
  ]
}
```

Receipts must use forward-slash game paths, lexicographically ordered file
lists, lowercase SHA-256 values, UTF-8, LF endings, two-space JSON indentation,
and no timestamp or host path. These rules make equivalent exports
deterministic.

The JSON Schema checks the structural envelope. A future recomp-side validator
must additionally reuse the mod stager's Windows path checks, reject
case-insensitive duplicates, compare `modId` with `mod.toml`, verify every
output beneath `files/`, hash those files, and reject unsupported schema or
profile versions. The current stager deliberately ignores the optional receipt;
the contract does not claim integration that has not been implemented.
`tools.mods_test.ModTests.test_ignores_malformed_blender_receipt_when_validating_and_staging`
uses an invalid JSON receipt beside `mod.toml` to verify that validation and
staging still succeed, the receipt is not copied, and only the synthetic
payload appears as an override in `.n3-mods.json`.

## Questions that block any writer

| Domain | Required evidence |
| --- | --- |
| Coordinates | Handedness, up/forward axes, unit scale, transform ownership |
| Geometry | Stream semantics, topology, winding, index limits, degenerate handling |
| Shading | Normal/tangent encoding, UV origin, material-slot and `.fx` meaning |
| Dependencies | `.skin` record layout, `.bm` lookup rules, texture-name mapping |
| Deformation | Whether any loose format carries bones, weights, bind poses, or morphs |
| Limits | Maximum counts, alignments, strides, offsets, and integer widths |
| Unknown data | Which ranges can be copied, relocated, regenerated, or must block export |
| Runtime | Loader failure behavior, cache invalidation, and companion-file requirements |

None may be answered solely from a file extension, one sample, or a successful
Blender import.

## Test and content rules

- Unit tests use synthetic redistributable bytes and malformed boundary cases.
- Private corpus tests may record hashes, counts, offsets, and aggregate
  structural summaries, but not retail payloads.
- Blender integration tests run with `--background --factory-startup` and an
  isolated profile.
- UI tests do not replace codec tests.
- Writers use temporary siblings and atomic replacement; a failed export leaves
  the previous mod source untouched.
- No broad exception handler may turn an unsupported field into a successful
  import or export.
- Mods contain only author-owned content. The add-on, receipt, and stager do not
  grant redistribution rights for original or modified retail assets.

## Non-goals for the first milestones

- live-linking a running game to Blender;
- writing directly to the extraction or staged game tree;
- armatures or animation inferred from the `.skin` extension;
- generic shader recreation from an `.fx` filename;
- `.pak` repacking;
- executable patches or generated-code edits;
- claiming broad compatibility from one visually plausible asset.
