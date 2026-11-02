# Blender asset authoring roadmap

## Status and selected scope

This track is **Planned**. As of 2 November 2026, the separate N3 Blender
project defines a Blender 5.2 development target and a headless-testable codec
boundary, but it has no parser, importer, exporter, or redistributable format
fixture yet. This document is therefore a contract and acceptance plan, not a
format-support claim.

The selected order is:

1. read-only `.skin` dependency inspection and `.bm` model import;
2. read-only `.36t` texture preview after model structure is established;
3. constrained loose-asset export only after reader and round-trip gates pass;
4. bounded read-only `.pak` research after the loose-asset path works;
5. no package writer until the complete container format is verified.

The first milestone deliberately excludes export. A Blender scene that looks
plausible is not evidence that an N3 writer is safe.

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

Build bounded readers independently of Blender UI code.

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

Treat `.skin` first as a dependency descriptor, not as skeletal data.

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

Prove each interpretation before creating Blender geometry:

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

Add texture work only after model/material dependencies can name what needs a
preview.

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

Enable a writer only for a named profile whose fields are understood. Start
with the smallest static-mesh subset; do not begin with arbitrary skinned
characters.

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

For each exported asset set:

1. run `python tools/mods.py validate`;
2. stage with `python tools/mods.py stage --replace`;
3. retain `.n3-mods.json` and the Blender receipt;
4. launch with an isolated user/cache root;
5. compare an unmodified export against the original route first;
6. test the edited asset from all relevant camera distances and effects states;
7. reproduce any failure without the mod before changing the runtime.

File-level load order remains the only merge policy. Two mods editing different
semantic records inside the same file still conflict at the whole-file level.

### 6. Read-only packed-resource research

After loose assets work, add a bounded `.pak` reader for inspection and local
extraction. Reuse the corruption, duplicate-name, normalized-path,
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

Example shape, using placeholder hashes:

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
