# Native engine modules

The translated PowerPC game already executes as native machine code. The modules
below replace understood engine behavior with typed C++ that can be inspected,
tested without the Xbox runtime, and extended through explicit adapters. A
replacement is not a performance claim or proof of broader game compatibility.

## Frame clock

| Layer | File | Responsibility |
| --- | --- | --- |
| Native model | `src/native/frame_clock.h` and `.cpp` | Game timebase frequency, frame deadline, integer ticks per frame and live rate changes |
| Guest adapter | `src/guest_frame_clock.h` | Read/write the verified big-endian clock fields and enable byte |
| Runtime hook | `src/frame_rate.cpp` | Clock source, selected FPS, frame-boundary calls, and guest calling convention |

The hook at `0x82248D38` now initializes recognized 30/40/60 Hz game clocks through
the native model. Unrecognized rates use the retained translated implementation.
Original mode preserves the game's exact float step bits. Live switching changes
the period/deadline while preserving the enable byte, including suspended clocks.
The global guest/audio/movie clock frequency and scalar are unchanged.

The adapter covers this layout for executable version 0.0.0.3:

| Offset | Type | Meaning |
| --- | --- | --- |
| `+1` | byte | Enabled; set to 1 only by initialization |
| `+4` | uint32 | Frames per second |
| `+8` | float32 bits | Simulation step in seconds |
| `+16` | uint64 | Ticks per second |
| `+24` | uint64 | Frame start/deadline origin in game ticks |
| `+40` | uint64 | Integer ticks per frame |

The pinned runtime's frequency import returns 32 bits; the hook deliberately
keeps that truncation. This avoids an accidental semantic change when rewriting
the routine. The native model accepts an explicit frequency and timestamp, so
tests and future engine callers do not depend on a host clock or global state.
All other bytes remain unchanged. Callers keep their stack and nonvolatile
registers; the initializer returns the original success value in `r3`.

## Shape bounds

Five additional engine entries now use `src/native/shape_bounds.h` and `.cpp`
through the guest adapter in `src/shape_bounds_hooks.cpp`:

| Entry | Native operation | Input fields | Output |
| --- | --- | --- | --- |
| `0x8235FB80` | Sphere bounds around a center | Center at `+68`, radius at `+288` | Six min/max float components |
| `0x8235FBE8` | Sphere bounds around the origin | Radius at `+288` | Six min/max float components |
| `0x82366970` | Local capsule bounds along Y | Radius at `+288`, half-height at `+292` | Six min/max float components |
| `0x82360478` | Local box bounds | Three half-extents at `+292` | Six min/max float components |
| `0x82366918` | Capsule's enclosing sphere | Center at `+68`, radius at `+288`, half-height at `+292` | Center and combined radius |

These names describe the verified arithmetic and layout; surrounding game class
names and all users of these bounds have not been reconstructed. Units remain
game units. Native operations accept explicit values and own no guest memory.
The hooks read/write big-endian fields and preserve the original return register,
stack, nonvolatile state, rounding mode and scalar flush-mode transition.

Arithmetic keeps the original double-intermediate/float32-rounding sequence.
Floating-point contraction is disabled, and strict/dynamic rounding is enabled
for the native library. The capsule's lower Y extent deliberately remains
`-half_height - radius`, since rewriting it as `-(half_height + radius)` changes
directed-rounding and signed-zero cases. Negative dimensions are not clamped.

NaNs, infinities and subnormal source values retain the translated implementation.
Outputs overlapping the first 304 bytes of the source also use the original,
preserving its ordered reads and writes. The conservative adapter does not try
to broaden these cases for a larger native-coverage count. Unmasked host FP
exceptions also use the original, retaining its partial-write order if a trap
occurs.

## Vector accumulation and synchronized channels

`src/native/vector_ops.h` exposes editable vector operations independent of guest
addresses, PPC registers, or the renderer. `src/vector_ops_hooks.cpp` binds seven
additional game entries to these operations:

| Entry | Verified behavior |
| --- | --- |
| `0x8208ECF8` | Add the vector at `+64`, multiplied by the double scalar in `f1`, to the accumulator at `+564` |
| `0x8209D858` | Same operation using the vector at `+32` |
| `0x8209D8A0` | Same operation using the vector at `+48` |
| `0x82336D90` | Set a three-component value at `+4` and its cached copy at `+60` |
| `0x82336DD0` | Set a four-component value at `+16` and its cached copy at `+72` |
| `0x82336E48` | Set a three-component value at `+32` and its cached copy at `+88` |
| `0x82336EB0` | Set a three-component value at `+44` and its cached copy at `+100` |

`AccumulateScaledVector` separates the float32-rounded product from the addition
and retains the caller's double scalar precision. `SetMirroredVector` updates
both copies; the guest adapter publishes the cache before the current value,
matching the original. `math_types.h` shares the Vec3/Vec4 types with other native
modules. Callers can supply new vectors/scalars or change the native operation
without editing translated code. For example:

```cpp
auto adjusted = n3::native::AccumulateScaledVector(current, direction, amount);
n3::native::SetMirroredVector(channel, adjusted);
```

This is code-level control over the verified arithmetic and storage. Which
objects/channels represent player movement, orientation, animation or other
state still requires caller tracing. No player movement multiplier or gameplay
retiming is inferred from field offsets alone.

The adapters retain the translated path for exceptional/subnormal inputs,
unmasked FP exceptions, wrapping address ranges and overlapping channel inputs.
They share a reviewed FP-control guard with the shape hooks. Current/cached
updates are not a new synchronization primitive and must remain on the game's
existing owner thread.

## Countdown, scalar arithmetic and bit fields

Five more entries use typed native operations through
`src/engine_primitives_hooks.cpp`:

| Entry | Native interface | Verified behavior |
| --- | --- | --- |
| `0x820801B0` | `AdvanceFrameCountdown` | Update active ID at `+208`, remaining frames at `+224`, and progress at `+216`, using total frames at `+220` |
| `0x824A0C50` | `AddScalar` | Add double operands, round to float32, and flush a subnormal result to signed zero |
| `0x824E7AD0` | `SubtractScalar` | Narrow the second operand to float32 before sign inversion/addition, then flush a subnormal result |
| `0x8246D5F8` | `ReadBitWindow` | Extract an LSB-first field from a little-endian four-byte window |
| `0x82324CD0` | `TryAccumulateVectorRatio` | Add a vector from `r5`, scaled by the float32-rounded ratio `f1 / f2`, to the three components at `+344` |

The countdown is a frame counter with an inactive ID of `0xFFFFFFFF`. It
decrements with unsigned wraparound, tests the result as signed, and keeps the
last progress when expiring. Progress deliberately uses the *previous* remaining
frame count divided by total frames, with both signed integers rounded to
float32 before division. Negative and zero durations retain the original
arithmetic. No conversion to elapsed time or higher-FPS animation fix is made.
The surrounding object's gameplay purpose still needs caller tracing.

Scalar results report whether a subnormal was flushed, allowing the adapter to
preserve the original condition flags. Subtraction cannot be simplified to
`float(first - second)`: the early rounding of the second operand is observable.
NaN, infinity and subnormal input registers retain the original implementation.
Native arithmetic requires the caller's rounding mode and disabled scalar
flush; the adapter provides that transition and retains unmasked trap paths.

The bit reader's native interface accepts a zero-based bit offset within the
first byte and a width of 1 through 32 that fits the four-byte window. The guest
entry's position is one-based. Unsupported widths, crossing windows and wrapping
addresses use the retained PPC shift behavior. This helper reads four bytes;
it is not a bounded parser for arbitrary untrusted buffers.

Ratio accumulation retains float32 ratio/product/result rounding and the
original reversed addition operands for Z. Unsupported inputs, zero denominators,
exceptional ratios and overlapping input/object ranges retain the translation.
The adapter restores FP controls before fallback and writes no partial native
result. Together these interfaces expose explicit frame state, scalar operands,
bit fields and vector inputs for future native callers without guest registers.
They are not yet a gameplay scripting or mod configuration interface.

## Transformed box geometry

`src/native/box_geometry.h` exposes an `AffineTransform3` (three row-major basis
rows plus translation) and `TransformedBox` with explicit half-extents. Two more
entries use this model through `src/box_geometry_hooks.cpp`:

| Entry | Native interface | Verified guest inputs/output |
| --- | --- | --- |
| `0x823602C0` | `TransformedBoxBounds` | Basis at `+32`, translation at `+68`, half-extents at `+292`; six min/max components to `r4` |
| `0x823604B8` | `TryTransformBoxSample` | Same box plus signed integer coordinates in `r4/r5/r6`; three transformed components to `r7` |

Bounds project each half-extent onto a basis row, take the absolute value of each
float32-rounded product, and add Z, then Y, then X. The returned bounds are centered
on the explicit translation. Negative extents retain the original arithmetic;
the transform is not assumed orthonormal, so scale and shear are supported.

The sample routine accepts all signed 32-bit coordinates, including the usual
eight `-1/+1` corner choices. Each integer rounds to float32 before multiplication
by the half-extent. For each output component, the Z product rounds first; the Y
and X terms use explicit double FMAs narrowed to float32, followed by a rounded
translation addition. Substituting float FMA or reassociating the dot product can
change bits. For example, native callers can edit `box.half_extents` or
`box.transform` and recompute bounds/corners without guest registers or addresses.
This is a geometry interface, not an identified player hitbox editor.

The adapters retain the original for exceptional/subnormal source values,
unmasked FP exceptions, wrapping ranges, input/output aliases and overlaps with
the original caller-stack scratch. Unsupported scaled sample coordinates also
fall back without publishing a partial result; saved FP controls are restored
first. Native arithmetic requires caller rounding and disabled scalar flush.
Box state and output remain owned by the game's existing calling thread.

## Oriented capsule bounds and box sphere radius

`src/native/shape_projection.h` adds an `OrientedCapsule` with editable center,
axis, radius and half-height, plus `CapsuleProjection` containing each endpoint's
bounds and their merged bounds. `BoxSphereRadius` accepts explicit box half-extents.
`src/shape_projection_hooks.cpp` binds two additional engine entries:

| Entry | Native interface | Verified guest inputs/output |
| --- | --- | --- |
| `0x82366808` | `ProjectCapsuleBounds` | Axis at `+36/+48/+60`, center at `+68`, radius at `+288`, half-height at `+292`; six min/max components to `r4` |
| `0x823603B0` | `BoxSphereRadius` | Center at `+68`, half-extents at `+292`; center and stored radius to `r4`, double square-root result in `f1` |

Capsule projection rounds axis times half-height to float32, then forms rounded
negative/positive endpoints and radius-expanded bounds. Merging updates only on
strict comparisons, retaining the negative endpoint's bits on ties, including
opposite signed zeros. The axis is not normalized and dimensions are not clamped;
non-unit axes and negative radii/heights retain the original arithmetic. Endpoint
bounds are exposed for native callers and geometry inspection. The adapter also
preserves the original `f1` value and final `cr6` comparison.

The box radius uses a float32-rounded Y square, then explicit double X and Z FMAs
each narrowed to float32, followed by a double square root. Its stored radius
rounds once more to float32, while `f1` retains the double result. A generic
`hypot` or rescaled length would change the original overflow/underflow behavior:
large finite extents can produce an infinite radius, and tiny normal extents can
produce zero. This extraction preserves those cases rather than claiming more
conservative bounds.

Both adapters retain the original for exceptional/subnormal sources, unmasked
traps, wrapping ranges and output/source aliases. Box-sphere source/output overlap
with the original caller stack frame also falls back. Native arithmetic requires
caller rounding, disabled scalar flush and masked traps. State remains on the
game's existing owner thread. These interfaces do not identify player hitboxes or
introduce user-facing geometry edits.

## Fixed-block delay and mixing

`src/native/delay_block.h` exposes `DelayBlockState`: three tap delays/gains, two
previous outputs and a write cursor. `TryProcessDelayBlock` accepts explicit
history, 256 input samples and two 257-sample output buffers. Two entries use
this model through `src/delay_block_hooks.cpp`:

| Entry | History length | Verified state layout |
| --- | --- | --- |
| `0x8253BED8` | 512 float samples | Tap delay/gain at `+0/+4`, `+12/+16`, `+24/+28`; previous outputs at `+8/+32`, cursor at `+36`, history at `+44` |
| `0x8253C240` | 2048 float samples | Same fields, with the larger history mask |

Both kernels read all three history taps before writing the current input. The
mixed output is a double FMA of the first tap/gain and the float32-rounded second
tap/gain product, narrowed to float32. The auxiliary output is the rounded third
tap/gain product. Delays wrap modulo history length; delay zero reads old history
at the write cursor, not the current input. Each output begins with the cached
previous result, followed by 256 new results. The last results become the new
cached values and the cursor advances by 256 samples with wraparound.

Native callers can edit tap delays/gains and process successive blocks without
guest registers or addresses. The verified callers use these fixed-size blocks;
the surrounding effect identity, perceptual behavior and routing still need
tracing. This does not introduce an audio-effect menu or change output gains.

The supported native cursor is block-aligned and leaves a complete contiguous
block within history. The original writes history contiguously, so unsupported
cursors retain that behavior through fallback rather than being silently wrapped
sample by sample. Overlapping state/history/input/output buffers, exceptional or
subnormal source values and unmasked FP traps also retain the original. Rejected
native calls mutate no state or buffers. Finite sources can still produce
overflow/underflow results, preserving the original arithmetic.

The guest adapter preserves untouched fields, output-pointer advancement, cached
results in `f1/f2`, cursor in `r7`, final condition flags and nonvolatile state.
It rejects wrapping guest ranges and overlap with the original 48-byte stack
scratch. A private per-thread workspace avoids large history snapshots on small
callback stacks; processing performs no callbacks and publishes no partial native
result. Existing owner-thread and valid-storage requirements remain in force.
Native arithmetic uses caller rounding, disabled scalar flush and masked traps.

### Two independent taps

Entry `0x8253C758` uses `DualTapDelayState` and `TryProcessDualTapDelay` in the same
module. Its two delays/gains produce separate outputs without mixing them. The
guest layout is delay/gain/previous at `+0/+4/+8` and `+12/+16/+20`, cursor at
`+24`, and 1024 float history samples at `+32`. Each call reads 256 inputs and
writes two 257-sample outputs prefixed by their previous values. Both taps read
old history before the current input is stored, including delay zero.

Supported cursors are 0, 256, 512 and 768; other cursors retain the original.
Delays wrap modulo 1024, while the history write is one contiguous block. Native
callers can edit the gains and delays independently. Source classification,
disjoint-storage checks and FP requirements match the three-tap model. Finite
source products may overflow or underflow just as in the translation; they do
not feed subsequent arithmetic within this kernel.

The adapter checks wrapping guest ranges and the original 32-byte caller scratch,
preserves `f1/f2`, returns both final products in `f0/f13`, and advances all three
buffer pointers by 1024 bytes. `r7` holds the unmasked cursor plus 256, while `r9`
and the stored cursor contain the modulo-1024 result. These distinct results are
compared against the retained translation. Effect roles and listening validation
remain unestablished; this adds an editable engine interface, not an audio menu.

## Feedback-delay processing

`src/native/feedback_delay.h` adds `FeedbackDelayState` with an explicit delay,
output gain, feedback gain, previous output and cursor. `TryProcessFeedbackDelay`
implements entries `0x8253BFA8` (128 history samples), `0x8253C310` (256), and
`0x8253C480` (512) through `src/feedback_delay_hooks.cpp`. The verified guest fields are
delay at `+0`, output/feedback gains at `+4/+8`, previous
output at `+12`, cursor at `+16` and history starting at `+24`. `r4` points to a
257-float in-place buffer; its first 256 values are input samples.

For each sample the model reads the delayed history, computes a float32-rounded
double FMA of feedback gain, delayed value and input, and stores that result back
into history. A second rounded double FMA of output gain, feedback result and
delayed value produces the new output. The output buffer begins with the old
cached output, followed by 256 new results; the final result becomes the next
cache. Delays wrap modulo the history size, including delay zero's old-history
read. The 128-sample entry makes two history passes per block: the second half
reads the updated first-half history. The 512-sample entry writes one 256-sample
half per call, alternating cursors 0 and 256. It preserves the other half and
advances the cursor modulo 512. Native callers can edit both gains and delay
without registers or guest addresses.

The supported cursor is zero for the 128/256 variants and either 0 or 256 for
the 512 variant. The originals write contiguous blocks without per-sample write
wrapping; other cursors retain the original path. Source subnormals,
NaNs/infinities, overlapping storage, wrapping guest ranges, original stack
overlaps and unmasked traps also fall back. The source buffer's output-only last
element is not interpreted as an input value. Generated subnormals are preserved.

Feedback can become nonfinite after several samples. The native model stages
history/output and commits only after the entire block has finite trial results;
rejection changes no caller state or buffers. The adapter restores saved FP
controls/status before invoking the retained translation. Directed-rounding
overflow that remains finite is supported and retains its saturated value.
Two bounded local staging arrays use at most about 3 KiB; the adapter's guest snapshots
use private per-thread storage. Processing invokes no callbacks and remains on
the existing owner thread. Caller rounding, disabled scalar flush and masked
traps are required by the native model. Effect routing and listening validation
are still pending; no gain or timing option is added to the game.

The shorter kernel leaves original input samples 249 and 248 in `f1` and `f2`
and sets carry from the unsigned delay comparison with 2. Its adapter reproduces
these results as well as the common 1,024-byte input-pointer advance and final
condition flags. The 256/512 entries preserve their original `f1/f2` and carry
behavior. All three return the resulting cursor in `r5` and store it in state.
Original translations remain available for fallback.

### Separate output and final sample

Entry `0x8253C5F0` shares the 512-sample history and arithmetic through
`TryProcessFeedbackDelaySeparate`. Its guest buffers have an unusual verified
contract: `r4` points to 256 unchanged input samples plus a writable final slot,
while `r5` points to a separate 256-sample output. That output receives the old
cached prefix and the first 255 new results. The last new result goes into
`input[256]` and becomes the cached output. The adapter preserves this layout
instead of extending the separate output buffer. Existing callers pass distinct
stack buffers and feed the separate output into subsequent processing.

The portable API represents that contract as const input, output and a separate
final-output reference; the reference may immediately follow input. State,
history, input, output and final-output storage must be pairwise disjoint. The
calculation stages its history and results, so late rejection changes none of
those regions. The adapter includes the input tail in range/alias checks, checks
the original 40-byte caller scratch, advances `r4` by 1024 and returns the wrapped
cursor in `r5`. `f1/f2`, carry and nonvolatile state are preserved. Native snapshots
use per-thread storage, and the shared core requires the existing FP contract.

## Table-derived limits and bounded updates

`src/native/bounded_value.h` separates channel selection, limit calculation,
value adjustment and modifier replacement from guest tables. Seven entries use
it through `src/bounded_value_hooks.cpp`; an eighth related-table entry uses
`src/state_relation_hooks.cpp`. The surrounding class, channel meanings
and gameplay units remain unidentified; these names describe the verified work.

| Entry | Operation | Table descriptor offset | Percentage field |
| --- | --- | --- | --- |
| `0x8209DBF0` | Limit with unsigned additive offset | `+88` | `+728` |
| `0x8209D718` | Add signed delta, then lower/upper comparisons | `+88` | `+728` |
| `0x8209DCF0` | Parallel table value, no additive offset | `+8` | `+736` |
| `0x8209DDE8` | Parallel table value, no additive offset | `+40` | `+740` |
| `0x820A13B0` | Replace modifier, then upper-only comparison | `+88` | `+728` |
| `0x8209D688` | Add integer percentage of limit to bounded value | `+88` | `+728` |
| `0x820B4DC8` | Conditional percentage addition to parallel value | `+8` | `+736` |
| `0x8209DEE0` | Table value with related-object category selection | `+216` | `+784` |

Descriptors are begin/end pointer pairs under the shared root plus category
times 16. Parallel getters return zero-extended truncated bits directly.

The limit entry chooses a channel from `+676`. For kind 1000 at `+300`, it first
adds `+780` with 32-bit wrap and caps signed results at least 9 to channel 8.
Negative wrapped results are not clamped upward. The adapter selects a signed
word from a 48-byte table record using row `+304` and category byte `+969`.
It supports whole, forward table ranges and channels 0 through 11; unknown
geometry, indices and channels retain the original path, including its traps.

`ValueLimitParameters` exposes the selected signed base, signed percentage
adjustment (`+728`), unsigned additive offset (`+732`), percentage unit and
baseline. Original constants are 0.01f and 1. Integer sources round to float32;
the percentage/baseline stage uses a float32-rounded double FMA, followed by a
float32-rounded product with the base. The product truncates toward zero with
the original positive saturation. Both the truncated bits and additive offset
are zero-extended before a 64-bit addition. Negative products below INT_MIN,
exceptional/subnormal source constants and nonfinite trials retain the original
conversion path. Rejected trials leave native outputs unchanged.

The adjustment entry updates float field `+664` by a signed integer delta from
`r4`, rounded to float32 before addition and rounded again afterward. It applies
the original lower comparison (zero in the game) before the signed low-32-bit
limit rounded to float32. A negative upper limit can therefore replace a
lower-clamped result. This deliberately preserves the two comparisons rather
than assuming ordered bounds. `BoundedValueUpdate` exposes intermediate and
clamp results for native callers; source exceptions and nonfinite trials reject
without changing state or update details.

`ValueLimitState` exposes limit parameters and the current value together.
`TrySetValueLimitModifier` replaces the signed percentage when mode's low byte
is nonzero, or the unsigned additive offset otherwise. It recomputes the limit
and compares the unchanged current value with the rounded signed low word of
the result. Only an upper comparison occurs: negative values and negative zero
survive when below or equal to the limit. Rejected trials leave both state and
details unchanged. The adapter rejects modifier writes that overlap lookup
pointers, descriptors, selected table cells or constants before following those
sources, preserving the original write-before-read behavior through fallback.

The adapters preserve the full 64-bit additive limit return in `r3`, final
condition/carry behavior, `f0/f1/f2/f3/f4`, nonvolatile registers and LR semantics.
Getter record/index/base registers and the modifier's final `f13` comparison
source are retained. All read regions are checked against original caller
scratch before traversal: 16 bytes for getters and a conservative 128 bytes for
the wrappers, including their nested callee. A wrapper prologue can replace a
root/descriptor pointer, so following its old bits before rejecting is unsafe.
The adapters restore FP controls
and status before unsupported-case fallback. The models require caller rounding,
disabled scalar flush and masked traps. No gameplay retiming or new stat menu is
introduced; concrete class roles still need matched-scene tracing.

`TryComputePercentageDelta` explicitly rounds both signed integer sources to
float32, then separately rounds percentage times unit and fraction times base.
`TryAdjustValueByPercentage` computes the first limit, derives a signed integer
delta from its low word, recalculates the limit, then applies the existing
lower/upper update. Its adapter excludes 256 bytes of nested scratch; no persistent
state changes occur between the limit reads on this supported path.
`TryAddConditionalPercentage` uses either nonzero flag byte to enable the extra
percentage, returning the unchanged base otherwise. Its adapter still computes
the parallel base first, reads the flags in original short-circuit order and
excludes 128 bytes of scratch plus the larger 1380-byte object range.
Zero-extended base and increment bits add in 64 bits, preserving carry.

Unsupported outer percentage calls retain their complete nested translations
through a scoped thread-local guard. A native leaf getter omits scratch writes;
mixing it with a retained outer caller could change later aliased flags or
percentage fields. The guard keeps those writes and original read order together,
and is released when the retained chain returns. The independent oracle switch
exists only in the percentage differential test. Both entries preserve `f1`–`f4`,
return/carry/condition state, the tested incidental registers and LR semantics.

Entry `0x8209DEE0` checks the packed handle from `+340/+344` before selecting its
table category. A matching key whose pointed object has kind 6 or 1000 selects
category 2; otherwise category byte `+969` remains in use. Its own channel uses
the existing kind/channel rule, and the row remains `+304`. The begin/end pair is
at root plus category times 16 plus 216, and signed percentage `+784` replaces
the earlier percentage fields. The same rounded factor/product and truncation
produce a zero-extended 32-bit result without an additive offset.
`SelectRelatedTableCategory` exposes that decision independently of guest memory.
The adapter excludes 240 bytes of nested scratch before following lookup sources,
retains final record/index/base registers, `f0/f13`, `f1`–`f4`, nonvolatile state,
LR and condition/carry behavior, and restores FP controls before rejection.

## Handle records and state payload installation

Four connected entries expose verified record operations without assigning a
gameplay role to the surrounding objects:

| Entry | Native interface | Guest adapter |
| --- | --- | --- |
| `0x82081138` | `TryLookupHandleRecord` | `src/handle_table_hooks.cpp` |
| `0x82080780` | Packed-handle key/index extraction and key validation | `src/handle_table_hooks.cpp` |
| `0x8209D358` | `StatePayload` and `TryCopyStatePayload` | `src/state_payload_hooks.cpp` |
| `0x8209D280` | `TryInstallStatePayload` | `src/state_relation_hooks.cpp` |

The handle table contains 12-byte records with key, object and auxiliary words.
The native API accepts a bounded span. The guest adapter checks a nonempty,
forward, whole-record begin/end pair and the selected index before reading it.
A packed handle's first word supplies the key; its low 16 bits are sign-extended
before the original unsigned bounds check. Key validation compares the full
first word and does not dereference the record's object word.
The validating wrapper's original writes include a 112-byte frame below SP and
16 bytes of argument homes at entry SP plus 16; sources must avoid both ranges.
Unsupported geometry, wrapping, negative/out-of-range indices and source/output
aliases retain the originals, including their invalid-input paths. Scoped guards
retain the complete nested lookup when an outer adapter rejects.

`StatePayload` names groups by offsets in the verified 100-byte record. Integer
words retain all bits; its eight float fields support normal values and signed
zeros. Native copies preserve those values without arithmetic. Exceptional or
subnormal transfers, unmasked FP traps and overlapping guest records retain the
original sequential loads and stores. Guest fields remain big-endian; native
callers edit typed state without guest addresses or registers.

The installer first copies this record to object `+336`. A nonnull optional
vector enables word `+412` and replaces floats `+420/+424/+428`. For signed own
kind at least 6, a matching handle whose related object has kind 1000 and variant
other than `0xFFFFFFFF` multiplies words `+356` and `+360`, storing the low word
back to `+356`. `PayloadInstallUpdate` exposes the full signed 64-bit product.
Source fields, optional vector and relation data are explicit native inputs;
rejection publishes neither state nor result details.

The installer preserves the original branch-dependent return registers, including
the payload pointer on its early branch, handle success or related variant on
later branches, and the full product in `r9` when multiplication occurs. Payload
float registers and optional-vector overrides retain their original values;
`f1`–`f4`, nonvolatile registers, LR and condition/carry behavior remain intact.
Both outer adapters exclude all 240 bytes of nested stack writes, including the
inner validator's argument homes. A payload write that could replace a descriptor,
record or later related-object read retains the original chain. Optional-vector
and copy aliases also retain original read/write order through fallback.

These interfaces prepare connected callers for further conversion. Broader
progression and callback-driven state updates still need explicit ownership,
callback and side-effect contracts; no gameplay role, speedup or new user-facing
editing feature follows from the field offsets alone.

## Direction normalization and conditional accumulation

Two entries now share typed squared-length math without guest addresses or
registers in the native API:

| Entry | Native operation | Guest adapter |
| --- | --- | --- |
| `0x823B3C00` | `TryNormalizeDirection` | `src/direction_normalization_hooks.cpp` |
| `0x8209D8E8` | `TryAccumulateDirection` | `src/direction_accumulation_hooks.cpp` |

`src/native/direction_math.h` exposes component squares and the exact reduction
tree used by the Windows translation: `(+0 + z*z) + (y*y + x*x)`, with each
product and addition rounded separately to float32. Subnormal vector inputs
become signed zero. Positive squared-length overflow is supported; mathematically
tiny nonzero stages and rounded subnormal stages retain the original translation.
Accepted results are independent of the host's input/output flush settings.

Normalization compares the squared length with the supplied threshold. A greater
or equal threshold produces four positive zeros without inspecting the raw
fourth component. Otherwise it uses a separately rounded square root, reciprocal,
Newton correction products, subtraction, sign-bit negation and final multiply.
The fourth component does not contribute to length but is multiplied on the
active path. `DirectionNormalization` exposes every stage. Finite normal/zero
active stages are supported; unsupported tiny, nonfinite or overflowing stages
reject without publishing results. The default guest threshold is `FLT_MIN`.

The adapter reconstructs the original aligned vector loads and byte permutation,
including the fourth lane's wraparound for unaligned inputs. It retains rounded-down
scalar output addresses, all vector-register results, the scalar threshold result,
condition fields and final enabled vector flush mode. It reproduces the 16-byte
scratch and output-pointer home at entry SP plus 20, excluding dependencies on
those writes before taking snapshots. Safe source/output overlaps remain native.
Strict FP environment access keeps threshold conversions on the original side
of the flush transitions. Both host and guest traps must be masked.

`src/native/direction_accumulation.h` exposes current state, default/override
directions, an explicit double amount, lower bound and squared override length.
The override is chosen when its length comparison is greater or unordered;
otherwise the default is used. Each selected component multiplies the amount
and rounds to float32 before a separate addition to current state. Branch-specific
addition operand order is retained. The unselected direction is not inspected.
Finite generated scalar subnormals remain valid with scalar flush disabled.
Unsupported inputs or nonfinite trial results change neither state nor details.

Its guest adapter reads default direction `+64`, current vector `+564` and override
direction `+576`, and writes only current XYZ plus the original 16-byte dot scratch.
It preserves the actual vector-phase rounding when host and guest controls
diverge, then unconditionally restores the guest scalar controls with flush off.
Final scalar/vector registers, pointer upper halves and condition fields match
the original branch. Unsafe scratch aliases, unmasked traps and unsupported
math restore both saved FP words before the retained call. Neither native path
claims identical transient sticky FP exception status.

Normalization has 240 static direct call sites across 147 translated callers.
The accumulation entry has indirect address references but no generated direct
calls; its runtime use has not been observed. The direction-basis caller
`0x8209D9B0`, which invokes normalization three times, now uses the typed phases
described below.
These contracts do not identify an animation/combat role or change game timing.

## Direction basis from signed axes

Entry `0x8209D9B0` now uses `src/native/direction_basis.h` and `.cpp`, with the
guest boundary in `src/direction_basis_hooks.cpp`. Its signed integer pair rounds
to float32 and forms `{horizontal, lower, vertical}`. The vector normalizes and
its new squared length is compared with lower. The inactive branch leaves output
untouched, including arbitrary old bits. A null selected basis writes
`{lower, lower, unit}`. Otherwise the selected record's X/Z values form a second
normalized vector with Y replaced by lower. The native model forms `up cross
basis`, weights that right vector by normalized horizontal and the basis by
normalized vertical, adds the rounded products, and normalizes the result.

Cross products, subtraction and sign-bit negation round separately. Scalar
products round before additions, preserving the different Y operand order and
generated subnormals. The model exposes each stage. Input preparation,
selected-basis composition and final normalization have separate transactional
interfaces, with a convenience operation for ordinary native callers. Guest
pointer reads are deferred until the input branch is active. Integer conversions
can observe incoming host rounding before subsequent vector stages install
guest rounding; the adapter preserves both phases.

Guest selection uses the full original slot arithmetic with a wrapped 32-bit
`slot * 12` address offset. No speculative end bound is invented. Selected fields
are at record `+64/+68/+72`; the middle value is overwritten before normalization.
The adapter writes object `+576/+580/+584`. It reproduces the complete original
stack writes and argument homes, branch-specific returns, all scalar/vector
register results and final disabled scalar flush mode. Raw fourth lanes at frame
`+140` and `+124` remain explicit inputs. Before final normalization, a local byte
overlay reconstructs the raw vector load after staged unaligned scalar stores;
the normalized XYZ stores still round their addresses down to four bytes.

Aliases that could change later constants, selected pointers, saved registers or
stack sources retain the ordered translation. A final output overlapping the
normalization threshold also retains the original post-write threshold read.
Unknown math domains restore both saved FP words before fallback. The native
interface does not identify the selected record's gameplay ownership or timing.

All three direction adapters use `src/guest_memory_address.h`. This matches the
pinned translation's physical-memory host bias of `+0x1000` at guest addresses
`0xE0000000` and above on Windows and Apple ARM64. Address arithmetic and alias
checks use translated host offsets. Ranges crossing that bias boundary retain
the original separate-access sequence. The helper validates arithmetic rather
than establishing that arbitrary guest memory is mapped.

## Capped accumulation and optional accounting

`src/native/capped_accumulator.h` exposes parameters, current integer value,
optional total/count state and calculation details for entry `0x8209D7A8`.
Signed delta and percentage adjustment round separately to float32. A rounded
double FMA creates the factor from percentage, unit and baseline; the product
rounds again before truncation with positive saturation. The resulting bits add
to the old value with 32-bit wrap before a signed upper-cap comparison. The
guest adapter uses cap 999999. It deliberately applies no lower clamp.

The adapter reads percentage `+760`, changes value `+680` and examines owner
pointer `+824`. A nonzero byte at owner `+696` enables global total/count updates
at offsets `+4712` and `+4708` under pointer `0x82B60080`. Both counter sources
are read before either counter write. Low words publish to state while the
64-bit zero-extended sums remain in the original return registers. Disabled
accounting preserves incoming return registers as the original does.

The adapter excludes original 16-byte scratch and rejects a value write that
would alter subsequent owner/global/counter reads before following those sources.
Counter writes to already-consumed sources retain the original order and remain
supported. Trials publish nothing on rejection and restore FP state before
fallback. All original GPR/FPR outputs, LR, condition/carry and control behavior
are checked. Surrounding gameplay roles and units remain unassigned.

## Deterministic chance rolls

`src/native/chance_roll.h` exposes an explicit `RandomSequenceState`, editable
multiplier/increment parameters, normal/alternate signed thresholds and a
`ChanceDecision`. Entry `0x8209E230` uses it through `src/chance_roll_hooks.cpp`.
Six translated call sites use this helper; that establishes static reach only.

The default sequence advances by `seed = seed * 134775813 + 1` with 32-bit wrap,
then samples `seed % 100`. It advances exactly once even when the threshold
guarantees acceptance or rejection. The modulo bias and sequence are preserved.
An enabled alternate threshold is used only when it is positive; otherwise the
normal threshold is selected. Signed thresholds are not clamped to 0 through 100.
Callers can replay an independent sequence or edit these native parameters
without guest registers. This does not add a player-facing chance editor or
identify every caller's gameplay role.

For executable 0.0.0.3, the adapter reads the normal/alternate thresholds at
object offsets `+764/+768` and the enable byte at owner `+812`. It updates the
existing shared seed at `0x825D9D74` on the game's existing owner thread; no new
cross-thread synchronization is introduced. It preserves both 64-bit argument
homes at SP `+32/+40`, their write-before-read aliases, the integer return and all
register/condition/FP state. Mapped ranges reject boundary/wrap and home/source
aliases before reading dependent values. Rejected cases retain the original.
The adapter reads only the selected threshold, so an unused threshold can remain
on an inaccessible page. It does not replace the other inlined shared-seed users.

## Kind flags and conditional state queries

`src/native/state_queries.h` exposes `KindFlags`, a selected-bit/boolean decision,
two-word `StateIdentity`, the category gate and a byte-preserving override.
`src/state_queries_hooks.cpp` replaces fourteen entries. Eleven share the same
small kind-table operation; these are entry-point counts, not subsystem counts.
The bit meanings remain numeric until surrounding callers establish names.

| Entry | Verified operation |
| --- | --- |
| `0x8209E338` | Kind flag `0x1` |
| `0x8209E368` | Kind flag `0x2` |
| `0x8209E398` | Kind flag `0x4` |
| `0x8209E470` | Kind flag `0x20` |
| `0x8209E4A0` | Kind flag `0x80000` |
| `0x8209E4D0` | Kind flag `0x100000` |
| `0x8209E500` | Kind flag `0x40000` |
| `0x8209E530` | Kind flag `0x20000` |
| `0x8209E560` | Kind flag `0x400000` |
| `0x8209E688` | Kind flag `0x10000` |
| `0x8209E6B8` | Kind flag `0x800000` |
| `0x8209E3C8` | Flag `0x8` only after both argument and related identity mismatch |
| `0x8209E6E8` | Flag `0x10` unless the selected record's category is 1024 |
| `0x8209E590` | Preserve byte `+716`, or return 1 for a nonzero request and zero guard `+160` |

The kind field is at object `+496`; its word offset wraps as `kind * 4` before
adding table base `0x825D9FA8`. This retains existing addressing rather than
inventing a class-count bound. The adapter validates each derived word and maps
physical addresses. The portable API accepts explicit flag words and editable
masks, owning no guest memory or global state.

The identity query compares object `+164/+168` with the packed argument and,
when needed, the related three-word record at argument value `+844`. It keeps
both 64-bit argument homes and the third record word's store at SP `-8`.
Home/source and later-read/scratch aliases retain the original before any native
publication or unsafe dependent read. An argument match skips related and table
memory; a related match skips the table. Category queries follow object `+316`,
owner `+444` and the `+192` row offset, reading category `+4` in 32-byte records.
Category 1024 skips the kind field and table. Byte queries use only the low eight
request bits and retain stored values through 255, without converting them to a
boolean. Unused guard/stored bytes remain unread. No FP state is changed.

## Verification

`native_frame_clock` runs in the portable component build on Windows, Linux and
Apple Silicon. It checks units, integer truncation, exact original step bits,
rate changes, zero-frequency behavior, and rejection without partial mutation.

`native_chance_roll` checks 20,000 threshold combinations, edited sequence
parameters, signed/unsigned wrap, guaranteed outcomes and a 100,000-roll replay.
`chance_roll_equivalence` compares the actual retained entry in 4,096 calls:
3,072 native and 1,024 retained, plus 1,024 chained replay calls and sixteen
inaccessible unused-threshold cases. It checks every committed fixture byte,
all GPR/FPR/VMX registers, LR/CTR/XER/condition fields and exact guest/host FP state.
No memory or scratch is normalized. Cases cover high object/owner/homes addresses,
all alignments, host offsets above 4 GiB, wrap/boundaries, default/alternate/seed
overlaps, argument-home aliases, signed threshold extremes and preserved unbiased
canaries. Integer work is tested under all rounding/flush/exception-mask modes
and divergent host/guest flush controls.

`native_state_queries` checks all flag bits, combined/zero/edited masks, both
identity words, exact category gating and 2,304 byte-selection combinations.
`state_queries_equivalence` compares all fourteen retained entries in 28,672
calls: 26,464 native and 2,208 retained. A further eighty calls make unused kind,
table, guard or stored-byte pages inaccessible; a matching argument can also
contain an unmapped related address. Every committed fixture byte, GPR/FPR/VMX,
condition field, LR/CTR/XER and exact host/guest FP state matches without scratch
normalization. Tests cover physical object/owner/record/table/homes, unaligned
words, host offsets above 4 GiB, wrapped row/kind indices, high register halves,
boundary fallback and source/home/scratch aliases. All rounding/flush/exception
modes and divergent host/guest flush controls are exercised.

`frame_rate_policy` compares the replacement with the actual retained translated
initializer for 18 rate/frequency combinations. It compares the entire 48-byte
clock object, including padding and flags, normalizing only the nondeterministic
timestamp; the replacement timestamp must lie between two surrounding samples
of the same game clock. Cases include a frequency wider than the import's return
type. The test also checks calling convention, indirect hook registration, live
switches, suspended clocks, unrecognized rates, and global-clock preservation.

`native_shape_bounds` checks geometric outputs, signed zeros, negative dimensions,
and exceptional-value classification without ReXGlue or game data.
`shape_bounds_equivalence` executes 12,800 comparisons with the five actual
translated entries across four rounding modes and both starting flush modes.
It compares the entire fixture buffer, covering finite and arbitrary float bits,
overflow, subnormals, infinities, NaN payloads, unaligned output and alias fallback.
It also checks guest calling convention, FP controls and indirect registration.
These are synthetic bounds checks, not full collision/mission validation or a
performance measurement.

`native_vector_ops` checks explicit vector edits, signed zeros, scalar precision
and synchronized three/four-component values without ReXGlue. The runtime suite
`vector_ops_equivalence` compares all seven entries with the retained translations
in 14,336 cases, across four rounding modes and both starting flush modes. It
checks whole-buffer writes, unaligned objects/inputs, alias fallback, float and
double edge patterns, indirect-call registration, preserved inputs and nonvolatile
state. The existing shape comparisons also run after sharing the FP guard.

`native_engine_primitives` checks countdown transitions, wraparound, signed
progress, zero durations, scalar operand narrowing, signed-zero result flushing,
bit order/width validation and explicit ratio vector edits without the runtime.
`engine_primitives_equivalence` compares the five actual translated entries in
20,560 cases across all four rounding modes and both starting flush modes.
It covers double/float edge patterns, all bit offsets and widths through 63,
counter boundaries, alias fallback, unaligned fields, condition/carry flags,
return values, representative nonvolatile state and indirect registration.
Exact arithmetic cases also exercise unmasked exceptions without triggering a
trap. All fixture bytes must match except the caller's 16-byte volatile stack
scratch used only by the original scalar/countdown arithmetic; unmasked fallback
cases compare that scratch too. FP rounding, flush and exception controls match.
These synthetic tests do not establish every caller's gameplay behavior.

`native_box_geometry` checks identity corners, translation, scale/shear, negative
extents, sum order, coordinate rounding and rejection without output mutation.
`box_geometry_equivalence` compares the two actual translations in 16,416 cases
across four rounding modes and both starting flush modes. It checks arbitrary
and edge float patterns, large signed integer coordinates, unaligned fields,
object/output and stack aliases, unmasked exact arithmetic, all nonvolatile
GPR/FPRs, condition/carry flags, FP controls and indirect-call registration.
Ordinary cases explicitly assert the native path is used. Whole-buffer checks
normalize only dead caller stack scratch (24 bytes for bounds, 64 for samples)
in non-overlapping masked cases; alias and unmasked cases compare every byte.
These memory-output routines do not reproduce dead volatile FP/GPR temporaries.
No new gameplay coverage, hitbox-role identification or speedup is established.

`native_shape_projection` checks editable capsule geometry, endpoint merging,
negative dimensions, signed-zero ties, source classification, radius precision
and original square overflow/underflow. `shape_projection_equivalence` compares
the two actual translations in 16,416 cases across all four rounding modes and
both starting flush modes. Checks include arbitrary/edge float bits, explicit
signed-zero ties, unaligned fields, source/output and stack aliases, unmasked
exact arithmetic, `f1` bits, all nonvolatile GPR/FPRs, condition/carry flags, FP
controls and indirect registration. Ordinary fixtures assert native-path use.
Capsule checks compare every fixture byte; box-sphere checks normalize only its
dead 96-byte caller stack frame in non-overlapping masked cases. No further
mission coverage or performance improvement follows from these synthetic checks.

`native_delay_block` checks tap edits, modulo delays, old-history reads, output
prefix/continuity, cursor wrap, unchanged history outside the block and rejection
without mutation. `delay_block_equivalence` compares both translations in 5,024
block cases across all rounding/starting flush modes. Eight-block sequences pass
through wraparound for both history lengths. Whole-buffer checks cover state,
history, input and both outputs, including arbitrary tap delays, unaligned
buffers, finite extremes, exceptional values, unsupported cursors and aliases.
Native cases explicitly prove hook use and normalize only untouched 48-byte
caller scratch; fallback cases compare every byte. Checks include `f1/f2`, pointer
advancement, cursor, all nonvolatile GPR/FPRs, condition/carry flags, exception
controls and indirect registration. These are kernel comparisons, not listening
tests or a performance measurement.

The same suites also cover the independent two-tap entry: portable fixtures check
its distinct gains, output prefixes, four-block cursor wrap, untouched history,
output-only tails and rejection without mutation. `delay_block_equivalence` now
compares all three entries in 7,536 block cases. Its two-tap cases verify the
32-byte scratch boundary, preserved `f1/f2`, final product registers, both cursor
forms, aliases, source exceptions, unmasked exact arithmetic and registration.

`native_feedback_delay` checks gain/delay edits, eight-block feedback continuity,
modulo delays, old-history reads, impulse decay through generated subnormals,
the unread output tail and rejection without partial publication, including late
overflow after the shorter history has wrapped. `feedback_delay_equivalence`
compares all four retained entries in 10,048 block
cases across all four rounding modes and both starting flush modes. It covers
eight-block chains, alternating 512-sample history halves and cursor wrap,
positive/negative overflow and finite saturation, generated
subnormals, source exceptions, unsupported cursors, unaligned/overlapping buffers,
stack aliases and unmasked exact arithmetic. Whole-buffer checks normalize only
unchanged native caller scratch (32 bytes in-place, 40 separate-output); fallback
cases compare every byte.
They also check native-path use, pointer/cursor results, each entry's `f1/f2`, all
nonvolatile GPR/FPRs, condition/carry flags, FP controls and indirect registration.
These are kernel comparisons, not perceptual or performance measurements.

The separate-output cases additionally compare the entire split output and input
tail, explicitly preserve the first 256 input values, and cover aliases involving
either buffer, state, history and the original 40-byte scratch. Portable fixtures
include output canaries, gain edits, split-output continuity, both history halves,
generated subnormals and rollback after a late failure. They also reject aliasing
the final-output reference with state, history, input or output. FP comparisons
cover rounding, flush and exception controls; they do not require every transient
volatile register or every sticky exception-status bit to match.

These replacements do not fix accelerated animation at higher FPS. Animation, combat and
scripted-event update paths still require matched-scene tracing and comparisons
before replacing or retiming them. Keep those changes separate from extraction
of an already-understood clock primitive.

`native_bounded_value` checks channel wrapping/capping, percentage and baseline
edits, modifier mode selection, truncation and positive saturation, 64-bit offset
carry, upper-only versus lower/upper comparisons, signed zeros, rejection without
mutation and integer rounding in all four modes.
`bounded_value_equivalence` compares five retained entries in 11,920 cases using
sparse synthetic guest memory for the original table and constant addresses.
It covers table rows/categories, channels outside the native subset, signed
integer extremes, exceptional float sources, aliases with state or stack,
unaligned fields, original constants and altered values, plus unmasked exact
arithmetic. Whole-fixture bytes match after normalizing only untouched native
scratch; fallback cases compare those bytes too. Ordinary fixtures assert native
path use; 8,338 cases use it overall. Checks include return/condition/carry state,
`f0/f1/f2/f3/f4`, getter record/base registers, modifier `f13`, all
nonvolatile GPR/FPRs, indirect registration and FP controls. A switch compiled
only into the test target forces the retained nested limit callee when running
the retained wrappers, preserving an independent oracle. Modifier aliases cover
full and partial overlaps with constants, selected cells and begin/end pointers.
Prologue aliases include initially uncommitted root/descriptor pointer values
that become valid through the original saved-LR write. Rejections must precede
any traversal of those old values. A further 4,960 executions disable the switch
and compare production composition; 480 explicitly exercise a retained outer
caller with a native nested limit. Only
the unused 16-byte nested scratch is normalized in those mixed cases. These
tests do not establish the surrounding gameplay role or every sticky FP status bit.

`percentage_value_equivalence` compares both percentage entries with independent
retained nested callees in 8,864 cases: 5,111 native and 3,753 complete retained
chains. Native cases normalize only their untouched full nested scratch; retained
cases compare every byte and GPR/FPR. Comparisons cover all rounding/starting
flush modes, signed conversion boundaries, altered constants, carry, both enable
flags, current-value extremes, unaligned records, prologue/source aliases and
exact unmasked arithmetic. Flags and percentage fields deliberately overlap
getter scratch in cases where a mixed retained/native chain changes results.
Sixteen follow-up probes establish that the scoped retained-chain override does
not leak into later native calls. Portable fixtures include a double-rounding
counterexample, negative delta/carry, all clamps, inactive unused sources and
late transactional rejection.

`native_capped_accumulator` checks editable percentages and cap, signed wrap,
negative increments, positive saturation, enabled/disabled accounting, 64-bit
carries, integer rounding and rejected-trial rollback. `capped_accumulator_equivalence`
compares the actual translation in 2,320 cases, including 1,296 native paths.
It covers null/disabled/enabled owners, source/stack/write aliases, already-read
source aliases, pointer wrapping, exceptional sources, late conversion failure,
directed overflow and exact unmasked cases. All GPR/FPR results and whole fixture
bytes match, normalizing only the untouched 16-byte scratch on native paths.
Indirect registration and condition/carry/FP controls also match. These are
synthetic state checks, not matched-scene gameplay or performance validation.

The new `native_handle_table`, `native_state_payload` and `native_payload_install`
fixtures exercise bounded lookup/key rules, editable payload fields, optional
vectors, signed products, relation/category gates, signed zeros and rejection
without publication. `handle_table_equivalence`, `state_payload_equivalence` and
`state_relation_equivalence` are the corresponding retained-translation checks.
Handle comparisons cover 4,608 calls over all rounding/flush/exception-mask
combinations, including 1,456 native packed validations and 848 retained wrapper
chains. They compare all scalar registers and condition fields, unaligned
records, output/source overlaps, key/index boundaries, malformed retained
layouts, the full frame and separate argument homes. Read-only queries reject
unknown bounds without mutating output; uncommitted old pointers test guards
before dependent reads. Integer handle code preserves FP controls and status.

Payload comparisons cover 2,320 cases, including 1,544 native copies, all field
groups, all eight scalar-source lanes, directed rounding, signed zeros, arbitrary
integer bits, unaligned fields, adjacency and both overlap directions. They
compare every fixture byte and scalar register. Outer relation comparisons cover
5,408 cases, including 3,640 native calls, explicit wide positive/negative
products, sentinel skips and category gates. They test copy/vector/related/table
aliases, prologue-overwritten pointers, unmasked exact calls, pointer upper halves,
return/condition/carry results and FP controls. Native installer results compare
all scalar registers; native table-value results compare their contracted
GPRs, `f0/f13`, preserved `f1`–`f4` and nonvolatile registers. Only untouched
240-byte scratch is normalized for native outer calls; retained chains compare
every byte and scalar register. Retained scopes must release before later native
calls. Neither scalar-transferring native path claims every sticky FP status bit.

`native_direction_math` checks the reduction tree, every normalization stage,
threshold edits, signed zeros/DAZ, directed square-root rounding, unused fourth
components, overflow and transactional rejection under all rounding/host flush
combinations. `native_direction_accumulation` checks editable direction/state,
both selections, double-product/float-add boundaries, generated subnormals and
rollback.

`direction_normalization_equivalence` compares 4,640 calls (3,400 native and
1,240 retained). `direction_accumulation_equivalence` compares 3,072 calls
(1,440 native). Both check every fixture byte, including native scratch and
argument-home writes, all 32 GPRs/FPRs, all 128 VMX registers, all condition fields,
LR/CTR/XER, preserved state, indirect registration and FP controls. Fixtures cover
all rounding/starting flush modes, unaligned sources/outputs, safe overlaps,
scratch aliases, exceptional values, underflow/overflow, unmasked exact calls and
explicit host/guest control divergence. Sticky exception flags are outside the
comparison; no scratch is normalized away for these two entries.

The direction fixtures additionally compare high physical source/output/stack
addresses, every source alignment, physical aliases, upper pages and shadow-boundary
fallback. Independent test address mapping and unchanged unbiased-memory canaries
prevent the implementation's address helper from serving as its own oracle.

`native_direction_basis` checks the phased interface, deferred unused operands,
signed axes and basis orientation, edited constants, each cross/weighted stage,
independently rounded integer inputs, scalar subnormals and final DAZ, altered
fourth lanes and early/late transactional rejection. `direction_basis_equivalence`
compares 4,672 calls (3,728 native and 944 retained), plus 384 retained outer calls
using the production normalizer. A switch compiled only into this test forces
all nested normalizers retained in the independent oracle. Every fixture byte,
all GPR/FPR/VMX registers, condition fields and FP/control state are checked.
Coverage includes wrapping slots, overwritten prologue pointers, independent
host/guest rounding, high physical records and slots, shadow canaries, arbitrary
initial output bits, unaligned final stores and wrapped raw fourth lanes. Its
physical cases include 168 native and 88 retained routes. No original scratch is
removed from these comparisons. Sticky FP status remains outside the contract.

Physical-shadow fixtures cover the three direction adapters and thirteen
connected state entries. Handle tables, payload transfer/installation, bounded
and related table values, percentages and capped accounting now map every word
and byte access. Full table/payload/object/scratch spans reject wrapping and
shadow-boundary crossings before following dependent pointers. Positive handle
argument homes and below-SP frames are checked separately. Aliases compare mapped
host ranges; retained-chain scopes preserve the original write-before-read order.

The connected state suites add 3,840 physical cases: 2,712 native and 1,128
retained. These include high object/root/owner/descriptor/record addresses,
unaligned and top-page data, packed keys, independent category/enable-byte reads,
optional vectors, signed wide products, counter carry, physical scratch aliases,
post-prologue pointer replacement and boundary/wrap fallback. Test setup uses an
independent address mapping; unbiased output/counter canaries and whole-region
comparisons detect writes to the wrong host location. New test-only handle and
accounting flags prove native selection without inferring it from shared helpers.
Untouched native scratch is normalized under the existing per-entry contracts;
retained calls compare it too. Contracted return/register results remain checked;
the expanded handle, payload, relation and accounting fixtures also seed and
compare preserved VMX registers and every condition field.

The other twenty-seven memory-backed typed entries now use the same mapped
address policy: five shape bounds, four box/projection operations, seven vector
updates, three memory primitives, seven audio kernels and the clock initializer.
Their earlier virtual-address loops remain unchanged. Separate sparse fixtures
add 14,536 comparisons: 8,680 native and 5,856 retained. These include host offsets
above 4 GiB, unaligned and exact-tail spans, individually high objects/buffers/SP,
boundary/wrap fallback, physical overlaps and unbiased-memory canaries. Those 43
memory-backed typed entries have physical fixtures; the chance adapter adds a
forty-fourth. The fourteen state-query entries bring this to fifty-eight.
Two scalar-only entries do not access memory.
This is coverage of the existing typed subset, not a full
game conversion or proof for every possible guest layout.

| Additional physical suite | Calls | Native | Retained |
| --- | ---: | ---: | ---: |
| Clock initialization | 4,608 | 2,448 | 2,160 |
| Shape bounds | 3,200 | 2,000 | 1,200 |
| Vector operations | 1,792 | 1,280 | 512 |
| Memory primitives | 768 | 520 | 248 |
| Transformed boxes | 768 | 424 | 344 |
| Shape projections | 768 | 448 | 320 |
| Delay blocks | 1,128 | 672 | 456 |
| Feedback blocks | 1,504 | 888 | 616 |

The clock adds 51 cached live-rate changes with suspended enable flags preserved.
Only its nondeterministic timestamp is normalized on retained calls; native calls
also normalize the unchanged 208-byte nested scratch. Geometry/audio normalize
only proven untouched native scratch under their existing contracts. Retained
geometry/audio/primitive calls compare every byte. Expanded tests seed preserved
VMX and every condition field alongside the contracted scalar/FP results.
Geometry keeps guest-flush-off/host-flush-on control divergence on the retained
path. Countdown progress rejects scratch aliases before publishing its update;
inactive and expired branches do not require unused stack storage. Clock, box
sample and box-sphere results now zero-extend restored LR exactly as the original
32-bit saved-LR load does. Portable math APIs and typed-entry counts are unchanged.

Both Windows configurations pass forty-four suites. A 24-second isolated
Direct3D Release startup reaches menu installation and frame pacing without
logged errors; Windows EXE/plugin privacy scans pass. These are synthetic and
startup checks, with no additional gameplay or performance claim.

An intermittent older direction-basis mismatch remains an open validation issue.
Subsequent builds, 120 process replays and per-processor pinned runs passed; these
do not establish its cause or a fix. First-byte diagnostics now accompany that
suite. See `docs/STATUS.md` for the observed failure and limits.

## Character animation: static trace and probe candidates

The static analysis in this section investigates the pinned generated
translation, **not** a native replacement. The separate runtime-probe status
below distinguishes live observations from these static paths. Addresses are
guest addresses; source references below are under `generated\default`. An
**Observed** statement describes instructions or bounded structural counts;
**Inferred** connects compatible observed paths; **Candidate** identifies a
testable interpretation; **Unknown** marks an unproven edge or meaning.
Generated function names remain address-based.

### Package, resource, and actor identity

- **Observed:** `sub_8223F6F0` calls `sub_820EB110` at `0x8223F9E0`
  (`n3_recomp.49.cpp:12302`, `n3_recomp.85.cpp:2512`). The latter formats
  `d:\data\PackedResources\%s_Char_Res.pak` at `0x8204723C` and calls
  `sub_82272EC0` at `0x820EB6BC`. It also formats `_Char_Tex.pak`
  (`0x82047264`), `_Res2_Res.pak` (`0x8204728C`), and `_Res2_Tex.pak`
  (`0x820472B4`) and calls the same entry at `0x820EB6E0`, `0x820EB708`,
  and `0x820EB72C`. The character and Res2 resource handles are passed to
  `sub_82272F58` at `0x820EB7B4` and `0x820EB7C4`, after the metadata
  loading call below. Earlier, at `0x820EB428`, it calls
  `sub_820DF800` with `SkinList.dat`: `sub_820DF800`
  (`n3_recomp.73.cpp:2445`) operates on 208-byte records, copies the name at
  `+16`, removes its extension, appends `.ba` (`0x82047140`), calls
  `sub_820EDD90` at `0x820E0228`, and stores the result at record `+12`.
  The ordering does **not** prove that this earlier call reads the subsequently
  opened character package.
- **Observed:** `sub_820EDD90` (`n3_recomp.19.cpp:2729`) tracks resource
  handles/refcounts and calls `sub_8224E6F0` (`n3_recomp.83.cpp:11949`).
  The latter searches manager entries, compares basenames and increments a
  cached resource's `+4`, or resolves a name through `sub_82272470`, obtains
  stream bytes through `sub_82273000`, allocates a 304-byte BA object, calls
  `sub_82298E78`, copies the name to `+28`, and releases the input allocation
  through `sub_82249030`. **Unknown:** a particular basename's winning
  archive/member, cache lifetime, and duplicate-name resolution.
- **Observed:** after package setup, `sub_820EB110` calls `sub_820ED8F0` at
  `0x820EB774`, which calls `sub_820F3618` at `0x820ED900`
  (`n3_recomp.65.cpp:2587`, `n3_recomp.68.cpp:2682`). On that path metadata
  `+260` supplies a BA name to `sub_820EDD90` at `0x820F3DCC`; its return is
  stored at stack `+256`. Names at metadata `+344` and `+408` are formatted
  with `as\%s` (`0x82040828`) and sent to `sub_8210C2C0` at `0x820F3DF4`
  and `sub_8210D168` at `0x820F3E84`, respectively; their output indices are
  written through stack `+260` and `+264`.
- **Observed:** the 92-byte setup record begins at stack `+208`; therefore
  those three fields are setup `+48`, `+52`, and `+56`. At `0x820F437C`,
  `sub_820F3618` passes that record to `sub_820F7620`
  (`n3_recomp.69.cpp:2941`). Its insertion paths reach `sub_820FABE0`
  (`n3_recomp.55.cpp:3225`), which explicitly copies all three fields into
  the 92-byte vector element. `sub_820E9B60` (`n3_recomp.32.cpp:2377`)
  installs owner `0x82B59050` at global pointer `0x82B60080`;
  `sub_820F53F8` (`n3_recomp.37.cpp:2845`) reads that owner's vector at
  `+2220/+2224`, searches 92-byte records using fields `+4` and `+88`, and
  returns a record or follows its fallback. `sub_82132588`
  (`n3_recomp.16.cpp:4417`) calls it at `0x82132668`, forwards the returned
  pointer in `r4`, and calls the actor's virtual `+0x8C` at `0x821326A0`.
  Actor vtable `0x82040170` has `+0x8C = sub_82093BE8`; vtable
  `0x82041570` has `+0x8C = sub_820AF768`, which calls `sub_82093BE8` at
  `0x820AF798` (`n3_recomp.38.cpp:1036`). **Inferred:** when the initialized
  owner and either of those vtables are in use, this connects the metadata
  outputs to the actor setup. **Unknown:** the actual selected record and
  winning package members for a given actor; other derived vtables may differ.
- **Observed:** `sub_82093BE8` (`n3_recomp.4.cpp:281`) passes setup `+48` to
  `sub_8224D1E8` at `0x82093C80` and stores its result in actor `+16`. Setup
  `+52` indexes global vector `0x82B4814C`; setup `+56` indexes
  `0x82B4815C`; each entry's `+4` is stored at actor `+312` and `+316`,
  respectively. Bounds failures trap. `sub_8224D1E8`
  (`n3_recomp.5.cpp:11998`) allocates an 868-byte instance, installs the BA
  handle at `+216` and BA object pointer at `+220`, and calls
  `sub_822669A0` (`n3_recomp.47.cpp:12794`), which iterates bound objects and
  invokes virtual `+28` with the binding argument. The handle, object, setup
  pointer, and input stream do not have interchangeable lifetimes.

### BA nodes, state rows, and selection

- **Observed:** `sub_82298E78` (`n3_recomp.34.cpp:13201`) reads a 24-byte BA
  header using stream vtable `0x82051140`, slot `+8 = sub_82265930`, checks
  its third word against 12, puts clip count at BA `+8` and bone count at
  `+12`, allocates frame counts at `+24`, and builds the node pointer array
  at `+20`. It calls `sub_822D55E0` per node and subsequently
  `sub_822D5AF0` and `sub_8229C100`. `sub_822D55E0`
  (`n3_recomp.14.cpp:14917`) reads two 255-byte names into a 1,040-byte node
  (`+21` and `+276`) and calls `sub_822D5820`
  (`n3_recomp.25.cpp:15291`). That routine stores a clip count at node
  `+616`, allocates per-clip arrays at `+884/+888`, constructs 112-byte tracks,
  and calls `sub_822D41F0` at `0x822D5ACC`. The latter
  (`n3_recomp.64.cpp:15221`) reads counts, two-byte key arrays and converted
  channel storage. The track table at `0x8205293C` contains `0x822D40D0`,
  `0x822D49D8`, `0x822D5468`, and `0x822D65C0`; `sub_822D49D8` is
  destructor-like, not the evaluation routine below.
- **Observed:** `sub_8210D168` (`n3_recomp.42.cpp:3543`) caches a separate
  state object and calls `sub_8210CB78` (`n3_recomp.84.cpp:3609`), which
  checks the first word for 100, associated with `Invalid Unit Info Data
  Version` at `0x82048258`, reads the row count into object `+440`, and
  allocates 32-byte rows at `+444`. `sub_8210BC98`
  (`n3_recomp.48.cpp:3284`) reads row fields in `+8/+12/+16/+20/+24/+28/+4`
  order and skips 58 bytes. The 86-byte file-row stride follows from these
  reads, not from the 32-byte runtime stride.
- **Observed:** the diagnostic at `0x82040298` contains `UnitID`, `AniAttr`,
  `AniType`, and `AniIndex`. `sub_82097868` (`n3_recomp.66.cpp:352`) calls
  `sub_8210CFE8` at `0x820978D8`; the latter
  (`n3_recomp.59.cpp:3212`) compares runtime row `+8` with argument `r4`
  (type), `+4` with `r6` (attribute), and `+12` with `r5` (index). Index
  `-1` gathers matching type/attribute row indices and chooses using a
  pseudorandom state, or tries index 0 if none exist. Otherwise it searches an
  exact triple, then returns the first matching type with requested index or
  zero, irrespective of attribute. A later attribute-only assignment is
  skipped when its accumulator is `-1`, its initial value; do not assume that
  fallback is reachable. These are **runtime** type/index values, not AniTool
  signal IDs.
- **Observed:** on success, `sub_82097868` calls `sub_82097958` at
  `0x82097940`. This direct-row installation entry
  (`n3_recomp.9.cpp:352`) copies row `+8/+4/+12` into actor
  `+496/+500/+504`, reads `instance+220 -> BA+24[row]` into actor `+508`,
  sets row `+192`, clears frame-like floats `+196/+200`, stores argument `r6`
  at `+512`, and conditionally captures previous row/time at `+208/+212` and
  transition values at `+220/+224`. Argument `r5` affects reapplying the same
  row; `r7` can cause immediate `sub_82097D00` dispatch. **Unknown:** the
  full semantic meaning of each transition field. Direct callers must supply
  a valid index; this entry is not a universal bounds check.

### Step, transition, evaluation, and matrix output

- **Observed:** actor vtable `0x82040170` maps `+8` to `sub_820913D0`,
  `+40` to `sub_8209D430`, `+44` to `sub_82080068` (returns float actor
  `+204`), and `+56` to `sub_82094F98`. `sub_820913D0`
  (`n3_recomp.27.cpp:227`) calls `sub_820948B8`
  (`n3_recomp.51.cpp:288`), which calls `sub_82080158` at `0x82094B5C`
  then `sub_82097D00` at `0x82094B64` on the observed path.
  `sub_82080158` (`n3_recomp.5.cpp:3`) copies actor float `+196` to `+200`,
  calls virtual `+44`, adds returned `f1` to `+196`, then calls
  `sub_82080390`. Constructor `sub_82092D28` (`n3_recomp.14.cpp:249`)
  initializes `+204` from `0x8205B614 = 1.0f`; `sub_820A3C78`
  (`n3_recomp.17.cpp:598`) can change it. One frame-like unit per controller
  invocation is the observed default, **not** a source-FPS measurement.
- **Observed:** `sub_82080390` (`n3_recomp.10.cpp:3`) compares current time
  with selected frame count minus one. Only when current time exceeds that
  limit, a nonzero actor `+228` is decremented and the virtual step is
  subtracted and clamped to zero; that value is also copied to `+200`.
  Otherwise on that exceeded-limit path it calls virtual `+40`. For the
  table above, `sub_8209D430`
  (`n3_recomp.48.cpp:472`) decrements `+512`, inspects `+660`, row `+16`,
  and runtime type values 9–11. Depending on branches it subtracts/clamps
  time, reselects through `sub_8210CFE8`/`sub_82097958`, or reinstalls the
  current row. These are **Candidate** loop, completion, and transition
  paths; they do not prove all clips loop or complete alike.
- **Observed:** `sub_820954B0` (`n3_recomp.74.cpp:289`) and
  `sub_82080218` (`n3_recomp.7.cpp:3`) use `fctiwz` on current `+196`,
  convert the integer back to float, and call `sub_82252BD8`
  (`n3_recomp.17.cpp:11843`) with manager `r3`, instance handle `r4`, row
  index `r5`, and frame `f1`. If previous row `+208 != -1`, the paths also
  pass previous time `+212` and blend-related `+216` to `sub_82252C38`.
  `sub_82252BD8` resolves the instance, resets queue fields, stores row at
  instance `+232`, frame at `+252`, and queue count at `+228`. **Unknown:**
  whether every caller truncates; do not generalize this observed path.
- **Observed:** `sub_8229E6B0` (`n3_recomp.73.cpp:14867`) consumes queue
  entries. For selector zero it walks `instance+220 -> BA+20`, stores the row
  at each node `+544` and frame at `+548`; a nonzero selector calls
  `sub_822D5D68`. Instance vtable `0x82051F88`, installed by
  `sub_8229CF30` (`n3_recomp.2.cpp:14116`), maps `+0x20` to
  `sub_822A1840`, `+0x64` to `sub_8229E898`, `+0x68` to
  `sub_8229EE40`, and `+0x90` to `sub_8229F860`.
  `sub_8229E898` (`n3_recomp.84.cpp:14578`) calls `sub_8229E6B0` then
  `sub_82298FF0` at `0x8229EA94`, with BA in `r3` and instance in `r4`;
  the `+0x20` and `+0x68` targets also call `sub_82298FF0`, the latter
  passing null `r4`.
- **Observed:** `sub_82298FF0` (`n3_recomp.16.cpp:14509`) iterates BA
  nodes, uses `node+888[clip]`, track `+16` count and `+32` 16-bit keys,
  performs comparisons/interpolation, calls `sub_8229CA98` and
  `sub_8229C5C0`, and computes node matrices. If instance `r4` was non-null,
  its call at `0x8229AD60` invokes instance virtual `+64` with the node's
  `+960` matrix and node index. For vtable `0x82051F88`, this resolves to
  `sub_82249628` (`n3_recomp.69.cpp:11979`), which copies 16 floats into
  the instance matrix array. BA nodes are within a potentially shared cached
  resource: **Unknown:** concurrency, snapshot timing, matrix convention, and
  whether this is every render path.
- **Candidate:** `sub_8229F860` (`n3_recomp.71.cpp:13555`), instance virtual
  `+0x90`, calls `sub_8229B348` at `0x8229FF9C` and `sub_8229B7D0` at
  `0x8229FFC8` with a BA, index, frame and output pointers. The separate
  `sub_822A2CA8` (`n3_recomp.50.cpp:14355`) calls `sub_8229B7D0` at
  `0x822A30D0` using instance fields `+220/+232/+252/+384`; its indirect
  table/context still needs confirmation. These are additional sampling
  candidates, not proof of the universal render route.
- **Inferred:** the companion add-on's strict read-only BA profile identifies
  the header word at file `+0x14` as mode 2 and its clip and bone counts at
  `+0x0C/+0x10`. The paths above connect that accepted profile to candidate
  mode-2 evaluation, but do not reconstruct every interpolation rule.
  **Unknown:** source animation FPS and the controller's invocation count per
  simulation clock tick. The existing `0x82248D38` clock initializer's
  recognized 30/40/60 Hz and clock `+8` seconds per simulation step are
  separate facts, not BA FPS. Script strings `SET_ANI_SPEED`
  (`0x8204DF84`), `SET_ANI_FRAME_COUNT` (`0x8204DF94`), and `SET_ANI_FRAME`
  (`0x8204DFA8`) are compared in `sub_821D11B0`
  (`n3_recomp.24.cpp`); those comparisons populate script-object fields and
  do not alone prove writes to actor `+204` or source FPS.

### Signal-like records and root-derived displacement

- **Observed:** `sub_8210C2C0` (`n3_recomp.0.cpp:3521`) caches a named
  44-byte object in vector `0x82B4814C` and calls `sub_8210BF78`
  (`n3_recomp.23.cpp:3466`). The latter reads two header words, stores the
  second at object `+4`, advances 512 bytes, allocates 12-byte entries at
  `+8`, and calls `sub_8210C728` per entry. It does not establish a version
  check on the first word. `sub_8210C728` (`n3_recomp.52.cpp:3648`) reads a
  record count into entry `+4`, allocates 20-byte runtime records at `+8`,
  uses stream slot `+4 = sub_822658D0` to seek through a type/offset table,
  and fills record `+0/+4/+8/+12/+16`: a frame-like integer, kind, bounded
  integer, payload-word count, and pointer to allocated four-byte words,
  respectively. It filters records with signed `+0 < 0` or `+8` outside
  `[0,16)`. Individual payload meanings remain **Unknown**.
- **Observed:** `sub_82097D00` (`n3_recomp.60.cpp:335`) indexes 12-byte
  entries at `actor+312 -> +8` using selected row `actor+192`, then calls
  actor virtual `+164` for each record at `0x82097D64`; it stops if the
  selected row changes. For vtable `0x82040170`, this resolves to
  `sub_820927C0` (`n3_recomp.65.cpp:254`), which special-cases kind 24
  and otherwise calls `sub_82097D90` (`n3_recomp.11.cpp:282`). The latter
  branches on record kinds 1–37. Several cases test record `+0` in the
  half-open interval `[actor+196, actor+196 + virtual(+44))` before using
  payload `+16`. **Candidate:** event/signal dispatch and timing windows;
  not proof that every kind is an event or uses that window. **Unknown:**
  per-kind payload semantics, event ordering across transitions, and whether
  specific AniTool records correspond to these runtime values. AniTool's
  signal schema IDs, its animation vocabulary, runtime state type IDs, and
  runtime record kinds are separate namespaces.
- **Observed:** `sub_8229C100` (`n3_recomp.51.cpp:13943`) searches node name
  `Bip01` (`0x8204096C`), falls back to the root, and precomputes per-clip
  samples in a BA `+288` vector structure using track keys and
  interpolation. `sub_8229ADA0` (`n3_recomp.12.cpp:14447`) compares two
  descriptor clip indices and times with BA counts, later checks vector
  indices, truncates times, subtracts two three-component samples, and writes
  via descriptor `+16`. The early frame-count lookup does not prove a
  lower-bound check for negative indices.
  `sub_82097B10` (`n3_recomp.6.cpp:483`) builds that descriptor from actor
  row `+192` and current/previous floats `+196/+200`, calls `sub_8229ADA0`
  at `0x82097BA0`, conditionally combines the result with actor basis-like
  vectors `+32/+48/+64` using flags `+840`, and adds it to actor `+592` and
  `+564`. Actor virtual `+56`, `sub_82094F98` (`n3_recomp.7.cpp:301`),
  calls it at `0x82094FBC` and also adds `+628/+636` to `+564/+572`.
  **Candidate:** root-derived actor displacement. **Unknown:** axes, scale,
  coordinate convention, and whether every clip drives gameplay motion.

### Bounded private-corpus correlations

**Observed:** three read-only fixture pairs below have mode word 2, AS first
word 101, INFO version 100, and equal BA clip / AS entry / INFO row counts.
BA members are in each mission's `_char_res.pak`; AS and INFO members are in
its separate `_res2_res.pak`. The nonempty count and retained-record count
come from the bounded AS parser matching the reads and filters above; payload
word **values** were not recorded. `9–11` counts INFO rows whose runtime type
field is one of the values inspected by `sub_8209D430`; the second number is
how many same-index AS groups contain retained records.

| Mission | BA | AS / INFO | Bones | BA / AS / INFO count | Nonempty AS groups | Retained records | Rows type 9–11 / with AS records |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| `ph_in` | `C_LP_KF1.BA` | `C_LP_KF.AS`, `C_LP_KF.INFO` | 75 | 162 / 162 / 162 | 149 | 2,029 | 11 / 11 |
| `ph_ty` | `C_LP_MF.BA` | `C_LP_MF.AS`, `C_LP_MF.INFO` | 91 | 97 / 97 / 97 | 77 | 485 | 11 / 10 |
| `ph_my` | `C_LP_WM.BA` | `C_LP_WM.AS`, `C_LP_WM.INFO` | 94 | 117 / 117 / 117 | 101 | 1,761 | 8 / 8 |

**Candidate:** same-index correspondence is supported by the observed
actor-to-BA and actor-to-AS pointer paths and these aggregates, but matching
names/counts do not establish which archive member the resolver actually
selected. The AS member can have additional trailing structures; these counts
do not decode them. Neither the add-on's stem fallback nor equal counts prove
game lookup behavior.

**Observed:** `tools\animation_static_trace.py` performs read-only generated
call/xref searches, in-memory XEX decoding, and aggregate BA/AS/INFO checks;
its `xrefs` are bounded straight-line candidates, not complete control-flow
analysis. Verify significant sites against generated `ctx.lr` and actual
vtable words. For example, from the recomp root:

```powershell
python -B tools\animation_static_trace.py correlate --char-pak private\game\data\PackedResources\ph_in_char_res.pak --data-pak private\game\data\PackedResources\ph_in_res2_res.pak --ba-member C_LP_KF1.BA --signal-member C_LP_KF.AS --info-member C_LP_KF.INFO
python -B -m unittest -v tools.animation_static_trace_test
```

The helper does not write decoded images or fixture payloads; its tests use
synthetic bytes. Its in-memory XEX path requires the pinned basic-compressed
executable and local SDK source archive; other compression is rejected.

### Static candidate instrumentation design

The following are **Candidate** entry/exit probes. Inputs are guest ABI
observations for the cited paths, not permission to change game behavior.
Capture only a whitelisted actor/resource identity, bounded counters and
aggregate results; do not log retail payload words or private-derived files.

| Guest entry / indirect site | Observed inputs and output/side effects to preserve | Question and memory lifetime |
| --- | --- | --- |
| `0x82093BE8`, via virtual `+0x8C` | `r3` actor, `r4` setup, `r5`–`r8`, `f1/f2`; original constructs actor bindings | Does setup `+48/+52/+56` resolve to the intended BA/AS/INFO members? Setup may be borrowed/vector-backed; manager objects are cached/refcounted. Snapshot validated IDs only during the call. |
| `0x82097958` | `r3` actor, `r4` row, `r5` reapply flag, `r6` stored control, `r7` dispatch flag; original changes row/time and can dispatch | Is the same bounded row selected in INFO, BA and AS, including immediate dispatch and transition? Validate all three counts before reading. |
| `0x82080158` / `0x82080390` and virtual `+40/+44` | `r3` actor; `+44` returns step in `f1`; original advances/clamps/reselects | How many invocations and what step occur per known simulation-clock tick at 30 and 60 Hz? Preserve the virtual calls and record pre/post values without assuming FPS. |
| `0x82252BD8` and `0x82252C38` | Manager `r3`, instance handle `r4`, row `r5`, frame `f1`; previous/blend entry has additional arguments | Does each observed current/previous value reach the correct queue slot, including truncation and blending? Resolve the handle only while its manager entry is live; verify the latter ABI before touching it. |
| `0x8229E6B0` / `0x82298FF0` / `0x8229AD60` | `r3` instance at queue consumer; evaluator takes BA `r3`, nullable instance `r4`; output call takes instance `r3`, matrix `r4`, node index `r5` | Is the selected track used and is the output finite/stable? Matrices and nodes may be shared or overwritten; copy no pointer for later use, sample only bounded counts/checksums at the original call boundary. |
| `0x82097D00` / virtual `+164` / `0x820927C0` | `r3` actor; virtual call additionally receives record `r4`; original may change row | Do counts and frame-window boundaries correspond to the same selected row? Records and payloads are borrowed; observe kind/count only, not words, and stop if dispatch changes row. |
| `0x8229ADA0` / `0x82094F98` | BA `r3`, descriptor `r4` with clip indices `+0/+4`, times `+8/+12`, output pointer `+16`; `0x82094F98` takes actor `r3` | Does the bounded before/after delta reach actor accumulators? Descriptor/output may be stack-backed, and node/precomputed samples shared; validate spans and observe only during the call. |

**Candidate procedure:** first establish one actor's package/member, vector
record, BA handle, and AS/INFO indices at initialization, without assuming
the filename correlation. Then separately sample at most 256 controller
invocations and 64 record dispatches per run for that actor, at known 30 and
60 Hz clock settings, stopping earlier after two observed transitions or
completion. Compare invocation counts, steps, row changes, and dispatch-window
aggregates; a duration/FPS conclusion requires independent source evidence.
If the limits miss the desired transition, report that as a missing observation
instead of enlarging the capture silently.

**Required preservation and stops:** keep original call count/order, arguments,
return values, memory side effects and exceptional behavior unchanged; save
and restore any logger-clobbered GPRs, FPRs, VMX registers, LR, CTR, CR, XER
and FPSCR without undoing the original function's results. Do not retain guest
stack pointers, dereference stale caches, make extra guest calls, allocate in
the hooked path, or inspect unbounded payloads. Stop on a changed executable or
vtable, invalid/nonfinite time or count, failed span/handle check, reentrancy
or concurrent shared-BA mutation, unexpected call ordering, altered behavior,
or any privacy risk. These stops end capture, not the original guest call.
The static study itself did not perform a probe, Blender run, game run, timing
fix, writer gate, or receipt/stager integration; see the separately labeled
runtime experiment below.

### Current bounded trace-v3, signal, and attachment evidence

**Observed, implementation:** the opt-in trace-v3/route-v4 probes add
archive-content/member identities and lifetime generations, nested timed
event IDs, bounded quaternion-helper samples, signal source/selection/
dispatch/effect observations, and an attachment resolver inventory. Original
guest calls and bounded loss accounting remain required. Host performance
counter time is not simulation time; nesting is not effect causality. Raw
traces, payload words, matrices, private paths and game assets remain private;
only reviewed hashes, counts and aggregate residuals may be recorded.

**Observed, 30/40/60 resource runs:** each selected the same 75-bone/two-clip
resource. Resolver-observed decompressed archive SHA-256
`005d18eb412b3f74eeab5f57b23b76ecb0d98e8d04f78b1e0b164506e73ef240`,
generation 4, slot 3, member index 5 and member SHA-256
`5013c53b8444eb666a9dd239acd00fd5e844f9d3eb6f38036d43e35277b308a5`
matched a scanned compressed archive candidate SHA-256
`385d3a1acfc2a0a7429e68a0e61daacf9380967a8063f93b7cb0b48e44fc9655`.
This establishes observed content, not a unique runtime mount path or actor.
Each retained 64 queue, 64 evaluator and 128 quaternion samples; no
controller sample or actor was bound.

| Target | Trace SHA-256 | Queue / evaluator full | Events started / abandoned | Quaternion seen / parent / per-evaluation / total full |
| ---: | --- | ---: | ---: | ---: |
| 30 | `fa2c3461f1e755fb02062ea7875785a92be4f5444a44eb0e441c48016eaf2cfa` | 213 / 209 | 678 / 422 | 8,690 / 1,672 / 6,506 / 384 |
| 40 | `819e0385d651bb9c5359ec2ff63e77fbc311c467837efa8064d4532eccb2da5b` | 236 / 232 | 724 / 468 | 9,447 / 1,856 / 7,079 / 384 |
| 60 | `a962dd6467ba06ae0a484f579e39dec56c62b19e9903ae09de6753c7e6eb8594` | 446 / 442 | 1,144 / 888 | 16,380 / 3,536 / 12,332 / 384 |

All three stopped `identity_changed`, with 11 invalid observations each;
their loss and stop status make them ineligible for conformance. The
Original actor attempt saw 588 unsupported-vtable setups, 587 with the
known getter, but accepted none. Quaternion-helper raw-lerp candidate
residuals were maximum `3.2209939269001175e-5` and RMS
`6.867796401602378e-6` over the same 128 retained samples in each run;
they are **preview-only comparisons**, not a proved interpolation rule.
There was no fractional evaluator-frame input, negative-dot or unequal
duplicate discriminator, simulation clock, completion/wrap/transition event,
or synchronized actor/root/child transform. The root report's seven model
residuals are `null`, not zero. Exact route hashes, competing residuals,
event counts and next experiments are in the companion
`docs/RUNTIME-ANIMATION.md` and `docs/ROOT-MOTION.md`.

**Observed, reader parity:** historical v3 and v4 routes without
`binary_provenance` are accepted as `unverified_legacy_route` and
`unverified_historical_v4_route`, respectively. Both readers accept and
validate present v4 provenance; the recomp compares recorded hashes with the
inspected binaries, while the companion reports
`recorded_not_independently_verified` without host paths. A matching hash is
not independent proof of loaded runtime binaries. Signal/quaternion probe
losses and actor-generation mismatches gate correlation eligibility in both
readers. Do not edit historical routes or claim runtime conformance: fresh
actor-bound capture, live ABI/identity evidence and diagnosis of
`identity_changed` remain necessary.

**Observed, signal:** the pure add-on AS-101 and INFO-100 readers retain
bounded records, source offsets/hashes and opaque bytes, with synthetic
malformed/bounds/preservation tests; no timeline markers follow. Original
and 30-target probes posted zero input pairs because foreground ownership
failed. Both saw one BA load and zero AS/INFO loads, selections, dispatches,
effects or structural chains, with zero recorded losses. Their capture
SHA-256 values are
`929467ce173dc5fd65400e33d1693879e3fd2e5aefa056323375726a00b445a1` and
`f343a64a0ccbb84ec79188fc028315231691ffa19ae0d7c0ff3f605a91c65cce`;
sanitized reports are
`e52406dddb7898de3ce4a9ba11c7dbdb0dd2677f85c91c71b1ccb234ea9d19ed` and
`2239e6e89f4eb0754ee5f396e3f254c156265daf69d098a14581f56d2fdfb09b`.
The observed BA is member 205 of decompressed archive content SHA-256
`998476909ae77902c582f5f7001aaccaa355a2dcaf08f42ee51dbc70c5cb465b`,
member SHA-256 `5133b115846a1395f6e26a6f3a78c24ac43f490048fbc325074f86ad04f6763f`;
this does not bind actor, clip or effect. A 523-archive scan parsed 521,
rejected two and parsed 85 AS plus 85 INFO payloads, not an exhaustive
uniqueness proof. Caller-supplied binary hashes are not runtime attestation.
Next, own the foreground and compare a controlled signal-triggering action
against a no-action baseline on two independently identified characters,
including resolver-matched BA/AS/INFO, row, clip, dispatch, independent
effect, lifetime and a separately calibrated time base.

**Observed, attachments:** the occurrence inventory v2 retains indexed
members, bones/palettes, descriptors, effects and ambiguity, while the
Blender diagnostic remains detached and unparented. Candidate and attempted
alternate-control probes each saw 151 reads, verified 20 and lost 64
descriptor plus 67 model observations to legacy capacities; the attempted
second-character probe verified all 151 reads with no capacity loss. Only the
candidate posted one input pair; controls had no foreground. None established
an actor, equipped item, socket, attachment lifecycle or synchronized
transform, so all residuals are unmeasured. The second-character run matched one
local candidate for each read among 521 parsed of 522 archives, not global
uniqueness. Capture/report hashes and exact table occurrences are in the
companion `docs/ATTACHMENT-EVIDENCE.md`. Next verify actor/item consumption,
an observed empty or different-item control, lifetime and synchronized
bone/attachment transforms on two independently identified cases.

### Historical opt-in v2 runtime probe

**Observed, historical implementation:** five retained-call wrappers in
`src\animation_trace_hooks.cpp` sample only the following concrete guest
entries. They do not implement every candidate above:

| Guest entry | Observed ABI assumption and recorded structural information |
| --- | --- |
| `0x82093BE8` | `r3` actor, `r4` setup record. Snapshot setup BA handle and AS/INFO vector indices before the call; afterwards bind a validated actor, manager, instance, BA, signal and INFO identity, including bounded counts and an ASCII-case-folded BA basename fingerprint. |
| `0x82080158` | `r3` selected actor. Read clip row and finite current/previous/step floats at actor `+192/+196/+200/+204` around the original; record before/after row/time, step and guest LR. |
| `0x82252BD8` | `r3` manager, `r4` instance handle, `r5` clip row and `f1` frame. Record the finite frame and LR only for the selected validated handle. |
| `0x82298FF0` | `r3` BA, `r4` instance. For the selected BA/instance, sample current queue count/clip/time and count pose-output calls during that original evaluation. |
| `0x82249628` | `r3` instance, `r4` matrix span, `r5` bone index. Count a valid 64-byte mapped span only within the selected evaluator and at guest LR `0x8229AD64`, the return from the indirect call at `0x8229AD60`; never read or serialize matrix contents. This does **not** test matrix finiteness. |

The matching static identities are manager global `0x825E12F0`, AS/INFO
vectors `0x82B4814C`/`0x82B4815C`, supported actor vtables
`0x82040170`/`0x82041570`, instance vtable `0x82051F88`, BA vtable
`0x82051F14`, and step getter `0x82080068`. Hook registration is checked
against the generated indirect dispatch table. The translated original is
called exactly once even when filtered, stopped, or disabled; the probe does
not modify `PPCContext`, allocate in the hook, make extra guest calls or keep
guest stack pointers. Observation guards restore the host FP environment,
MXCSR, `errno` and Windows last-error state; ordinary compiler ABI rules
preserve host nonvolatile registers. Synthetic tests exercise guest context,
floating-point/thread state, nesting and call counts, but do not prove every
gameplay path or exception behavior.

Capture is disabled unless `N3_ANIM_TRACE=1`. The default
`N3_ANIM_TRACE_SCOPE=actor` uses `N3_ANIM_TRACE_ACTOR=first` or
`0x<guest address>` to select one actor. Explicit `N3_ANIM_TRACE_SCOPE=resource`
instead selects the first validated manager/instance/BA at the queue entry;
it rejects an explicit actor address rather than ignoring it. In this scope,
the actor, AS and INFO identities are explicitly unbound, not inferred from
names or timing, and there are no controller samples. Both scopes accept
`N3_ANIM_TRACE_CLIP=all` (default) or `0`–`4095` to filter recorded clips.
Resource binding validates the manager global, bounded handle/table entries,
instance and BA vtables and handles, clip/bone bounds, and the bounded
basename fingerprint before publishing its instance identity. Fixed arrays hold at most 256
controller, 64 queue and 64 evaluation samples, with a 96 KiB serialization
limit. Counts distinguish filter misses, invalid values/spans, full buffers,
lock drops, reentrancy, concurrent activity, work in flight and stops. A failed
checked guest range, mapping, object/handle identity or finite-value check
prevents unsafe reads; capture stops on invalid identity/mapping, reentrancy,
concurrent selected-actor/shared-BA evaluation, or two observed clip
transitions. Checks use validated 32-bit spans and the physical-shadow
mapping, `VirtualQuery`, and bounded `ReadProcessMemory` copies. This is
best-effort observation, not an atomic guest snapshot: address reuse and
mutation between checks cannot be ruled out.

The deterministic v2 trace and aggregate JSON omit host paths, member names, retail bytes, decoded chunks,
signal words and matrix contents. One bounded `CREATE_NEW` file is written and flushed when an accepted window
close is requested, with an idempotent `N3App::OnShutdown` fallback. The SDK
normally calls `std::_Exit` from its window-closing callback before
`OnShutdown`, so the earlier close-request callback is necessary. A hard kill,
crash, or programmatic `RequestClose` that bypasses close-request listeners
cannot guarantee the flush. `tools\animation_trace_manifest.py` validates bounds, identities,
counters and schema before producing a sorted aggregate with executable,
source and candidate-asset hashes. A matching BA basename fingerprint is
**Candidate** evidence only, not proof of the resolver's winning archive.
Both raw captures and route/log files belong under the ignored
`private\traces\runtime-instrumentation\` directory. Do not commit them.

For a new v3 run, use the current runner from the recomp root with a verified
local extraction and a new `RunId`; the v2 capture described below remains
historical. Each `RunId` must
be new; user/cache roots are isolated, the route requests a window close, and
its deadline kills only the process it launched. The optional
`-ActivateWindow` asks Windows to foreground only that process's window;
keyboard events are posted only while its process owns the foreground.
Foreground ownership and posted events do not prove the title consumed them.

```powershell
pwsh -NoProfile -File tools\build.ps1 -Configuration RelWithDebInfo -Jobs 4
python -B -m unittest -q tools.animation_trace_manifest_test
pwsh -NoProfile -File tools\animation_trace_run.ps1 -RunId example-30 -Seconds 120 -FrameRate 30 -Actor first -Clip all
```

If the host has no usable playback device, the locally archived SDL source
can be built with its standard **silent dummy sink** in a separate ignored
diagnostic build without modifying the installed SDK or the standard build:

```powershell
pwsh -NoProfile -File tools\build_trace_audio.ps1 -Jobs 4
pwsh -NoProfile -File tools\animation_trace_run.ps1 -RunId example-dummy-30 -Seconds 120 -FrameRate 30 -Scope resource -Clip all -ActivateWindow -QuaternionProbe -AudioBackend dummy -Executable private\traces\runtime-instrumentation\local-sdl-dummy\game-build\n3.exe
```

The alternate build verifies the locally cached pinned SDL archive and SDK
source bundle, uses the locked compiler and SDK, does not download anything,
and refuses to overwrite an existing diagnostic build. The host executable
alone is insufficient: the SDK's `rexruntimerd.dll` contains its own static
SDL, so the helper also rebuilds that runtime from the pinned SDK sources with
the private SDL library and stages it only beside the private executable. It
checks the actual executable and GPU-plugin imports against the rebuilt DLL.
The rebuilt DLL's complete export set is not byte- or export-identical to
the installed SDK DLL; it is a diagnostic configuration, not a supported SDK
replacement. Dummy audio is not evidence of audible playback, normal audio
timing, or gameplay equivalence.

The manifest tool requires the matching private route JSON and capture, and
rejects routes without a window/input-idle observation, or with a forced stop,
unsuccessful exit, or mismatched parameters. It
records the actual backend and hashes of the host executable, runtime/GPU
libraries, SDL source/library, SDK source bundle and candidate packages; its
aggregate is created once beneath `private` and cannot overwrite a prior
result. Invoke `python -B tools\animation_trace_manifest.py --help` for the
required paths. Run a corresponding `-Disabled` route with the same
executable/backend when comparing basic startup and shutdown.

For the example dummy route above, validate and hash its bounded candidate
character archives without writing member names or bytes:

```powershell
python -B tools\animation_trace_manifest.py `
  --trace private\traces\runtime-instrumentation\example-dummy-30\user\animation-trace-v3.json `
  --route private\traces\runtime-instrumentation\example-dummy-30\route.json `
  --executable private\traces\runtime-instrumentation\local-sdl-dummy\game-build\n3.exe `
  --game-root private\game --character-archive-dir private\game\data\PackedResources `
  --output private\traces\runtime-instrumentation\example-dummy-30\aggregate-v3.json `
  --frame-rate 30 --seconds 120 --audio-backend dummy `
  --audio-source-archive .tools\source-archives\libsdl-org-SDL-147a8ee32dbf9ac02f3794964490687b6bbda1bc.tar.gz `
  --audio-linked-library private\traces\runtime-instrumentation\local-sdl-dummy\sdl-install\lib\SDL3-static.lib `
  --audio-sdk-source-bundle out\release\ReXGlue-bd833a2-corresponding-source.zip
```

#### Bounded local capture, 30 FPS target

**Observed, local runtime:** the following exact diagnostic route was run with
isolated user/cache roots and a 120-second deadline:

```powershell
pwsh -NoProfile -File tools\animation_trace_run.ps1 -RunId trace-resource-30-d -Seconds 120 -FrameRate 30 -Scope resource -Clip all -ActivateWindow -AudioBackend dummy -Executable private\traces\runtime-instrumentation\local-sdl-dummy\game-build\n3.exe
```

PID `15172` owned a responsive window, was observed in the foreground, and
exited normally after 113.475 seconds; 21 Enter/Space pairs were posted,
without proof of consumption. No forced stop was needed. The v3 route and v2
trace were validated into the ignored
`private\traces\runtime-instrumentation\trace-resource-30-d\aggregate-v2.json`
(SHA-256 `9812d435178f029eb9179f2ff0e12314a8c20ee46a92b646e9ee95e2e5e46302`).
The diagnostic host SHA-256 was
`0ac0580eafeb68cc4ae355231cac8e8c8b479529a86c941373cd2cab64027807`;
the pinned XEX SHA-256 was
`0fe8973b6ff45d3f8bd03a51a8c0d8cdf278b3d43e793497777e075f4e94a804`.

The selected **resource**, not an identified actor, had manager
`0x82B48938`, instance handle `13`/address `0x40B74890`, BA handle
`1`/address `0x40BA7720`, two clips and 75 bones. Its basename fingerprint
was `0x9ded20c7cf964a29` (length 16). The trace stored 64 queue and 64
evaluator samples, all clip `0`; there were no setup or controller calls.
Queue LRs were `0x82179FBC` (one sample) and `0x8217AD4C` (63); evaluator
LR was `0x8229EA98` (64). Of 2,181 queue calls and 4,354 evaluator calls,
the bounded arrays dropped 2,117 and 2,113 respectively; 2,177 other
evaluator calls were filtered. The 64 retained evaluations contain 4,800
validated pose-output calls, versus 163,275 observed overall. Invalid values,
invalid outputs, lock drops, reentrancy, concurrent activity and in-flight
calls at flush were all zero.

**Candidate:** 21 members in the bounded set of 36 character archives matched
that basename fingerprint. All 21 yielded the same member SHA-256
`5013c53b8444eb666a9dd239acd00fd5e844f9d3eb6f38036d43e35277b308a5`
(94,850 bytes). This is not proof of the resolver's winning archive or of
an actor/package/AS/INFO association. The aggregate records all archive
hashes, candidate indices, source identities, clip/return histograms, buffer
counters and build inputs without member names or bytes.

**Observed, rejected development attempts:** an actor-scoped run saw 2,180
queue and 4,352 evaluator calls but no setup call or selected actor; it had no
retained samples. An earlier resource run stored five queue samples, then
flagged 75 pose outputs because the initial guard used call-site
`0x8229AD60` instead of LR `0x8229AD64`; generated code and the subsequent
capture above establish the corrected return identity. Two other attempts
produced no calls; their input consumption and foreground ownership were not
verified. These attempts are not
validated gameplay or timing evidence.

## Bounded signal/clip correlation

This independent, read-only study inventories the private corpus and follows
generated code without copying member names, decoded records, payload words,
or retail bytes into the repository. `tools\signal_clip_research.py` emits
only bounded structural counts, offsets, hashes, numeric identities and
aggregate candidate fingerprints. Its structural profile is not a writer or a
claim that every possible input has the observed layout.

### BA trailing extents

**Observed, private corpus:** all 522 packages were readable: 36 character,
36 resource2, 36 resource3, one initial and 413 other packages. Character
packages contain 685 BA occurrences representing 67 unique payloads. The
bounded mode-2 extent walker found trailing data in 11 unique payloads,
occurring 57 times. The companion add-on's strict reader independently rejects
each of those 11 with its trailing-data classification. This confirms only
the boundary and rejection, not a trailing-data format or semantics.

The table gives zero-based member-relative offsets, tail lengths, occurrence
counts, complete member SHA-256 identities, and SHA-256 of the opaque tail.
No word inside a tail is interpreted. The multiset fingerprint of the
confirmed entries is
`d402cff68a44ec9e9deef7fa4272d70a1d462feb0d79dee69c25ab05bd53993a`.

| Offset | Length | Occurrences | Member SHA-256 | Tail SHA-256 |
| ---: | ---: | ---: | --- | --- |
| 492860 | 288 | 3 | `02a7bcf62a4125ee5954d965ff4a0e7f6089d9696286120b56ab9a7c4ca738d0` | `679733ec9726af15f5df6184c97457fa73f9bca02cde746870dff2597d6cf109` |
| 494104 | 1052 | 1 | `4574c1abc5a19edda29b84bc01342cdfc92a59a1d9b7e1f748c0fd9d999287c6` | `69e78cb39a4c623ec1251f0be0d203c9c67b3087faa2b347869d8e8f40b76533` |
| 1434104 | 920 | 7 | `687e210b9d1767b73fb0ae61c0c750e78c807ab1a03e251b34ce4915d3743bfe` | `abb822772cab788cf9cd0743953a066e38c8f64b9bc27a430569ba21352b6b9c` |
| 527104 | 512184 | 3 | `9a94309feedbb576ac1435b5b7c0b8ae37ea857fe8943f0e78a2aaafd61cbbaa` | `efa7f59ef523ed481fe9f079d7a0f90f58b67ce5c7568a34724a0b1e933f0d33` |
| 480128 | 7600 | 3 | `a346732c287df695dafa764e242af6d515f0c0d88a90a892c4fdee7ff0fac520` | `b0dcb65aea054361e66aee97d9626083c595f147671a3581b3bccb82761c728d` |
| 886012 | 7404 | 29 | `b011c8cd2acdcb94ef0210654ad8498be9d1870682b826009f61f59e4732cd4a` | `c54644db93bf52f4d63a238b0f7fd690037c4060339deefd585fe35b45d3720c` |
| 480344 | 132984 | 2 | `b0a6a7b35b8e2d1953ace6f32e05eb6b7e7ea5e9c66154055999c998069cf54b` | `d6ee866c5fe6aaaad7e7a43ebdfc6385f765afbb23d56b7c9627caf0e1735563` |
| 486268 | 20 | 3 | `b93a302d5f61bfb7bf021adbdd04b52fb92650d1fd1a9b3ef92bbd368e1137ba` | `2a5c8f010bcac5d3dc04d53648059d71ea33cc9b71d2fb6275a2d89385b13fb3` |
| 496592 | 153316 | 2 | `debb52f01ceffeef519d5cf4e02eb10f6cd6b9dc5ec56b2a3af49ea0c73e96d8` | `e3db30b85878378ff8bc6f6eb03c9af949709f5582139732c578c084bcda2bc6` |
| 569394 | 158520 | 2 | `e0b6738e6192ea281afd8548525d8f3b4aeccf78de05f00059f2bad421be89e0` | `11d41701ce5926c553cfb5fb1976b27136c200e800f58149518c76894d892c51` |
| 500000 | 138764 | 2 | `fc374860582558b85d578e4374cb44fca931a1f5a27048ff91d65a444f67c277` | `27aff700db9c008a5d7e76e1c0934760114787afd7798a6d827edeee6ccf0776` |

### Bounded AS and INFO records

**Observed, generated code and private corpus:** the characterized AS profile
starts with big-endian word 101 and a group count, followed by 512 skipped
bytes. Each group has a count and, for nonempty groups, pairs of kind and
absolute member offset. At each offset the characterized record has a signed
time-like word, a signed bounded word, a word count, that many uninterpreted
four-byte words, and 16 further uninterpreted bytes. The loader retains
records with nonnegative time and bounded word 0–15. The bounded walker
requires ordered, contiguous records; the guest follows offsets, so
contiguity is a corpus observation, not a universal format guarantee.
`0x8210BF78` and `0x8210C728` are the relevant generated loaders.

There are 85 unique AS payloads with 4,300 groups: 3,553 nonempty and 747
empty. All 18,477 declared records are retained, with time-like values
0–17,289; all bounded-word values 0–15 occur. Payloads span 0–29 unknown
words in 15 distinct lengths. Across different members, the minimum retained
record start is 532 and the maximum checked record end is 169,112; these are
member-relative bounds, not a single combined file. No group uses the
recognized `0x10000` empty sentinel. Across these payloads, the groups are
followed by 5,140 opaque 64-byte blocks and two opaque count-prefixed arrays
containing 248 and 358 words respectively.
The generic dispatcher `0x82097D90` handles the numbered range 1–37;
50 corpus records have kinds outside that range: 0 (6), 38 (14), 39 (27)
and 95 (3). Actor-specific dispatch may handle additional kinds, so this is
not proof that those records cannot have effects.

**Observed, separate vocabulary:** `animtype.h` has 33 numeric definitions
and 31 distinct values, including all 27 runtime animation types 0–26 plus
attribute/sentinel values. `signaltype.h` has 42 kind IDs 0–41.
`signalid.txt` has 42 blocks resolving to those 42 symbols and declaring
255 parameter slots; its standalone block numbers are *counts*, not IDs.
`animid.txt` has five distinct authoring IDs, -1 through 3. These are
different namespaces; no animation type is assigned from an AniTool ID.
As a structural test only, all 18,474 AS records whose numeric kind has a
unique signal-schema definition have a payload-word count equal to that
same-number definition's declared slot count; the other three are kind 95,
outside the schema. This is strong layout correlation, not proof of
parameter values, effect semantics, or a particular live clip association.

**Observed, INFO:** the 85 unique INFO-100 payloads contain 4,300 bounded
86-byte rows. Attributes have counts 0: 2,952, 256: 1,018, 512: 213 and
1,024: 117; row indices are zero 1,661 times and positive 2,639 times.
Every payload has a suffix of 4–1,872 bytes. The first signed suffix word is
used by the generated loader at `0x8210CE0C–0x8210CF10` as a count of
auxiliary entries; across the 85 files those counts total 222. The remaining
suffix is not parsed or assigned signal/attachment semantics here.

### Static selection, candidates, and missing runtime edge

**Observed, generated code:** `sub_82103640` copies the three CHARDATA
animation, AS and parts fields to offsets +260/+344/+408 of 984-byte rows at
`0x821039C0`, `0x82103AB8` and `0x82103B10`. The pointer assigned at
`0x8258889C` connects that table to `sub_820F3618`, whose calls at
`0x820F3DCC`, `0x820F3DF4` and `0x820F3E84` pass the respective fields to
the BA, AS and INFO loaders. This is a static metadata-to-loader path, not
proof of the winning archive/member at runtime.

`sub_8210CB78` counts INFO runtime types in a four-by-27 table.
`sub_8210CFE8` selects by runtime type, index and attribute: index -1
chooses pseudorandomly among matching type/attribute rows or tries zero;
an explicit index tries the exact triple, then the first matching type and
requested index or zero. The apparent later attribute-only fallback is not
reached from its initialized accumulator. `sub_82097958` can instead install
a direct row without typed selection, and `0x8209D644` can reinstall the
current row. On the observed actor path, the installed `actor+192` row
indexes INFO and BA, and `sub_82097D00` indexes the AS group with the same
row before virtual dispatch. This wiring is conditional on the actual actor
bindings and does not identify their package members.

For example, the actor-specific kind-24 branch at
`0x820927F0–0x82092850` compares record time against the half-open interval
`[actor+196, actor+196 + virtual step)`. On the observed transform path,
`0x82080248–0x82080280` truncates the same actor time and forwards it with
the row to the transform queue. This supports a shared frame-like numeric
basis for these paths only; it does not establish source FPS, universal
interpolation, or an observed effect.

**Candidate, not resolver proof:** matching CHARDATA basenames within paired
character/resource2 package families yields 640 occurrences for 86 table
rows and 86 distinct BA/AS/INFO payload triples with equal clip/group/row
counts. These use 57 distinct BA, 85 AS and 85 INFO payloads. The multiset
fingerprints for candidate identities and triples are respectively
`46467236e133cfd5465f0ed98cf36fb521542b96d4b324ed08b04328fbff071d` and
`4a5161f361d29c034b4325c0d5e6ade9592357289f3b2abd43bce3ad46e4d4a0`.
Across unique triples, same-index comparison counts 18,618 AS records:
18,528 below the BA frame count, three equal and 87 above. Triples may reuse
an AS payload, so this is not the unique-AS record total. The 90 exceptions
reject an unconditional in-range assertion for all heuristic pairings; they
do not identify which candidate a runtime actually uses.

**Observed, independent resource search:** CHARDATA has 100 rows/33 columns
and ITEMTABLE has 200 rows/30 columns; neither has a column name containing
signal, clip or event. The package scan includes 664 `.aib` occurrences
(95 distinct), 350 `.ai_funcb` occurrences (19 distinct), and 1,966 generic
`.bin` occurrences (288 distinct); loose resources add 7 `.aib`, 19
`.ai_funcb` and 36 `.n3sb` files. Case-insensitive byte-substring scans of
these resources found no `signal`, `notify`, or `event` strings. Generic
`.bin` resources are not assumed to be scripts. These are lexical checks,
not parsers or evidence that binary scripts cannot encode such behavior.

**Observed, existing runtime only:** the validated resource-scoped trace
SHA-256 `7a0a80d6575bcf83f581f4d0c8c0b9e1093d93013607118307e62232adf92edd`
has no actor, AS or INFO binding, zero setup/controller calls, and 64 queue
plus 64 evaluator samples, all clip 0. Its validated route SHA-256 is
`580acdd23358a6977461c285169cd18c394ca5d266db927b1aa661d80e4ba41e`;
it targets 30 Hz, posts 21 input pairs within a 120-second limit, and exits
normally. Posting inputs does not prove consumption. No new runtime capture
or effect observation was performed in this study.

**Unknown and next discriminating experiment:** the exact missing edge is a
bounded association between resolver-selected package/member hashes and a
live actor's BA/AS/INFO bindings, selected row, record dispatch and an
independently observed effect, repeated for at least two characters. Existing
hooks do not capture dispatch effects. A future explicitly authorized probe
must preserve original calls, stay within the existing local-route and capture
limits, and first establish those identities before comparing time windows
and effects. A missed actor or effect remains missing evidence, not a reason
to assign markers or names. Preserve `Clip_###`, unsupported BA tails, and no
notify markers; no source FPS or attachment relationship follows from this
study.

### Reproduction

Run the analyzer against the owned extraction, the add-on checkout and the
existing bounded trace; placeholders below are inputs, not committed host
paths. It makes no writes and reports generic, path-free errors. Omit
`--trace` only when intentionally excluding the runtime summary; omit
`--addon-root` only when strict add-on tail confirmation is not needed.
The optional trace check uses the separately provided
`tools\animation_trace_manifest.py` validator; the synthetic analyzer tests
do not require that instrumentation helper.

```powershell
python -B tools\signal_clip_research.py --game-root '<owned-game-root>' --addon-root '<addon-checkout>' --all-packages --trace '<existing-trace-json>'
python -B -m unittest -q tools.signal_clip_research_test
python -B -c "import hashlib,subprocess,sys; b=subprocess.run(sys.argv[1:],stdout=subprocess.PIPE,check=True).stdout; print(len(b),hashlib.sha256(b).hexdigest())" `
  python -B tools\signal_clip_research.py --game-root '<owned-game-root>' --addon-root '<addon-checkout>' --all-packages --trace '<existing-trace-json>'
```

Two Windows runs produced 8,531 identical stdout bytes, SHA-256
`bc6d91dab16063a1a826ad001a318c2019377077750f4d5d1935bc97782590a7`,
for the specified corpus, strict confirmation and trace. The report includes
no private-derived output file.

### Companion evidence and acceptance boundary

The companion `0.14.1` source checkout records the detailed
`docs/RUNTIME-ANIMATION.md`, `docs/ROOT-MOTION.md`, and
`docs/ATTACHMENT-EVIDENCE.md` and a completed/partial/blocked matrix in
`docs/ROADMAP.md`. The strict source inventory classifies 49 accepted BA
payloads, 11 unsupported tails, and seven unsupported inverse-bind profiles.
Its six parser-eligible deformation pairs and 44 name-based attachment
candidates are not runtime-bound characters or equipped relationships.

In the earlier v2 30-target resource capture above, the 64 queue and 64 evaluator
samples are independently bounded, with 2,117 and 2,113 respective
capacity drops; 163,275 pose-output spans were counted without capturing
their matrix values. Actor/AS/INFO identities remain unbound. Correlate
resolver-selected members, actor, controller time, root/child transforms,
selected row, record dispatch and an independently observed effect across
at least two identified characters before assigning evaluator rules,
root-motion behavior, attachment bindings, semantic clips, or notify markers.
No native writer or Blender receipt consumer follows from the static trace.

## Adding the next module

Identify a bounded engine routine and its inputs, outputs, units, side effects,
ownership and thread. Keep the original translated entry available. Write the
portable model first, then a narrow guest-memory adapter. Compare its results
against the original on supported data, preserve unknown cases, and validate
the affected gameplay route before claiming compatibility or a speedup.
