# AI and navigation architecture

This document describes the supported USA/Europe `0.0.0.3` executable. It
separates established behavior from modernization proposals so that future AI
work can preserve authored missions and guest-visible data structures.

No runtime AI or pathfinding behavior has been replaced. The checked-in work is
a bounded offline NAV parser, compatibility model, reference solver, funnel
implementation, and synthetic test suite. Generated translations, executable
images, and owned game data remain local and are not repository inputs.

## Evidence and reproduction

The labels in the [documentation index](README.md) apply throughout:

- **Verified** parser, topology, routing, and funnel properties have synthetic
  coverage in `tools\n3_nav_test.py`.
- **Observed** corpus totals and route measurements come from the supported
  owned stage archives. They can be reproduced locally, but the report and game
  data are not committed.
- **Observed** runtime structures and control flow were traced in the supported
  guest executable and its generated translation.
- **Inferred** names describe behavior supported by structure or call sites
  where a complete runtime experiment is still missing.
- **Planned** items are compatibility gates, not current features.

Run the public synthetic checks:

```powershell
python -m unittest tools.n3_nav_test
```

Inspect one owned stage archive:

```powershell
python tools\n3_nav.py inspect `
  private\game\data\PackedResources\vz_my_res1_res.pak
```

Reproduce the deterministic corpus sample without placing derived data in the
repository:

```powershell
python tools\n3_nav.py analyze `
  private\game\data\PackedResources `
  --samples 40 `
  --seed 0x4E335241 `
  --output private\n3-nav-analysis.json
```

Directory discovery intentionally reads direct `.NAV` files and the 36
`*_res1_res.pak` stage-spatial archives. A direct `.pak` argument may be used
for an archive with another name.

## Layered AI system

N3 does not have one monolithic AI routine. Authored data and runtime code form
five cooperating layers:

| Layer | Primary resources | Established responsibility |
| --- | --- | --- |
| Mission/event | compiled `.bstrg` | Trigger mission events; assign troop AI definitions, strategic paths, areas, props, and `AIGuide0..15` values |
| Troop decision | compiled `.n3sb` | Evaluate conditions and issue engagement, defense, movement, path, follow, and stop-like commands |
| Unit behavior | `.aib`, `.ai_funcb` | Select combat actions, search for units, run callbacks, update variables, and coordinate animation |
| Combat/data | `.as`, `.info`, SOX | Supply attacks, unit classes, capabilities, dimensions, movement values, and other statistics |
| World/navigation | `.BSMAP`, `.NAV` | Supply authored strategic paths and objects, plus the free-movement triangle graph |

The practical flow is:

1. A mission trigger assigns or changes a troop program and its authored
   context.
2. The troop evaluator selects a high-level order.
3. A troop-state handler moves a formation anchor directly, along an authored
   BSMAP path, or through a NAV route.
4. Formation members receive per-unit slot targets around that anchor.
5. Unit AI chooses combat and animation behavior, while capability-gated
   neighbor processing and NAV boundary clipping constrain local movement.

This separation matters for modernization. Replacing global route search does
not replace mission scripting, troop decisions, formation policy, combat
selection, local collision response, or animation.

## Authored AI corpus

The read-only gameplay-data index observed:

- 664 `.aib` instances representing 95 unique unit-AI resources;
- 350 `.ai_funcb` instances representing 19 reusable modules;
- 637 attack-script instances representing 85 names;
- 637 unit-info instances representing 85 names;
- direct `<UNIT>_DEFAULT.AIB` matches for 78 of 86 named NPC rows;
- 36 compiled troop-AI `.n3sb` programs; and
- 36 stage NAV/BSMAP pairs.

The repeated function names and standalone AI-function resources support a
composition model: unit programs call shared behavior modules rather than
inheriting one universal script. Resource names and string recovery do not, by
themselves, establish a complete binary grammar or safe writable format.

## Troop decision evaluator

The compiled troop evaluator at guest `0x8215B248` runs only when enabled and
when the global tick is divisible by 60. One pass walks authored `AIDef`
entries, evaluates their conditions, and tries their actions until an action
reports success. If no action succeeds, it invokes the state-reset helper and
enters `TROOPSTATE_NON`.

The owned corpus contains 68,678 decoded tokens and 1,178 `AIDef` blocks.
Commands are negative type-5 scalar values, not strings. The runtime dispatcher
at guest `0x8215B408` has 23 cases.

Important command semantics are:

| Command | Owned-corpus uses | Established runtime behavior |
| --- | ---: | --- |
| `Engage` | 2,970 | Calls a virtual troop method. The base implementation enters `MOVE_ATTACK`; specialized troop classes override the same slot. |
| `EngageMercifully` | 3,165 | Calls the corresponding merciful virtual behavior. |
| `EngageStanding` | 96 | Enters `HOLD`. |
| `EngageStandingMercifully` | 10 | Uses the merciful virtual slot; it is not merely the `HOLD_MERCIFULLY` setter. |
| `Disengage` | 37 | Selects retreat/disengagement behavior. |
| `Defense` | 2 | Selects defense behavior. |
| `MoveOnPath` | 362 | Follows an authored path. |
| `MoveOnPathLoop` | 30 | Follows an authored path as a loop. |
| `MoveOnPathRandom` | 1 | Selects the random-path variant. |
| `MoveOnFullPath` | 1 | Selects the full-path variant. |
| `SetTargetID` | 85 | Stores the matched target as a side effect, then returns false so a later action can consume it. |
| `Stop` | 2,116 | Returns success without changing the current troop state. |
| `Follow` | 589 | Selects follow behavior. |
| `EngageGuardianToTarget` | 61 | Selects guardian engagement around a target. |
| `EngageArea` | 10 | Selects area-constrained engagement. |
| `EngageMercifullyArea` | 12 | Selects the merciful area variant. |

`Stop` is therefore a script-level "accept this definition without issuing a
new order," not a direct movement stop. Because it reports success, later
definitions are not considered during that pass and the previous order remains
active.

Unsupported dispatcher cases return false. They do not hide later definitions,
and a pass containing no successful action still falls back to
`TROOPSTATE_NON`. Declared commands not observed in the owned programs include
`EngageSmart`, `DefenseProp`, `UseAbility`, `MoveOnPathWithAvoidEnemy`,
`AttackEnemyNearSomebody`, `AttackWall`, and `DisengageOnAttacked`. Absence from
this corpus is not proof that another build or unused mission cannot reference
them.

The condition dispatcher at guest `0x8215B710` has seven established cases:

1. troop HP comparison;
2. melee-engaged state;
3. general engaged state;
4. friendly-troop count;
5. enemy-troop count;
6. troop existence; and
7. identity comparison.

Several conditions copy a matched identifier into the evaluator's small work
buffers so a later command in the same definition can use it.

## Derived troop engagement policy

The command dispatcher does not select one universal engagement algorithm. The
troop-category factory at guest `0x82130BF0` selects a vtable whose `+0x1C`
slot implements `Engage` and whose `+0x20` slot implements
`EngageMercifully`.

The base `Engage` method at guest `0x8213A928` rejects a null target and, unless
forced, rejects melee-ready and melee-attack states. It avoids inserting a
duplicate target, moves the troop anchor toward target fields `+192/+200`,
stores the target tuple, and reports success. An optional command flag enables
a `2.0` movement-speed multiplier on the troop members. The base merciful
method at guest `0x8213AB10` maintains its target and counter-attraction data
and enters `MOVE_MERCIFULLY`.

The owned character data and selected virtual methods establish these
category-specific policies:

| Troop category | Owned examples | Established `Engage` behavior |
| ---: | --- | --- |
| 2 | most heroes and melee units | Base `MOVE_ATTACK` behavior |
| 3 | archers | Shared ranged helper |
| 4 | `C_DS_CAT` | Shared ranged helper with its existing-target override flag forced off |
| 5 | flying `C_DS_DG` | Enter `RANGE_ATTACK` when the range predicate accepts; otherwise move toward the target |
| 7 | moving tower `C_DS_SEI` | Base engagement slots; other state-update slots are specialized |
| 8 | special infantry | Base engagement slots |
| 10 | archer `C_LS_EM1` | Shared ranged helper |
| 11 | specialized `GT`/`CT` families | Return false without issuing an `Engage` order |

The shared ranged helper at guest `0x8213E350` enters `RANGE_ATTACK` state 7
when its target/range checks accept. Otherwise it establishes movement toward
the target. Ranged and flying merciful overrides first run the base merciful
behavior, then opportunistically switch to their ranged path. The catapult
retains the base merciful slot.

Factory branches also exist for categories 0, 1, and 9, but no owned character
row selects them. Category 6 follows the factory's failure branch. Two more
vtable variants are constructed outside this category factory: the internal
world-object class-4 path initializes troop state 6 and retains the base
engagement slots, while the class-12 path initializes `HOLD` state 12 and its
generic `Engage` slot returns false. Human-readable identities for those two
internal object classes are not yet established.

Returning false is behaviorally significant: the compiled evaluator may
continue looking for a successful action instead of treating the unsupported
engagement as an accepted order. This is one reason a route-search replacement
must not flatten siege, flying, ranged, and special troops into one movement
policy.

## Troop movement and formation members

Troop routing primarily moves a formation anchor. The route follower then
combines that anchor with each member's formation-slot offset.

### Formation breadcrumb queue

Each unit has a five-entry circular X/Z queue:

| Unit offset | Meaning |
| --- | --- |
| `+1000` | circular index |
| `+1004` | current count |
| `+1008..+1047` | five X/Z entries |

Every 30 global ticks, the troop route follower offers the unit's current
absolute formation-slot target to this queue. Redundant targets are suppressed
and the count is capped at five. Every three ticks, the troop-state update
removes the oldest entry when the unit comes within 500 planar units. Direct
movement changes clear the queue.

No other translated consumer of this storage was found. The queue is therefore
best described as formation breadcrumb or progress bookkeeping. It is not
established as the source of the unit's steering vector and should not be
presented as flocking.

### Movement-speed scaling

Separate unit fields control a state-specific movement multiplier:

| Unit offset | Meaning |
| --- | --- |
| `+984` | multiplier enabled |
| `+976` | multiplier |
| `+972` | resulting low-level movement magnitude |

These fields participate in selected engagement and follow states. They are not
part of the five-entry breadcrumb queue.

### Capability-gated neighbor processing

The unit capability table uses bit `0x8` for `UNIT_FLOCKABLE`. The predicate at
guest `0x8209E3C8` rejects self and linked-self identities, then admits neighbor
handling only for units with that bit. The same base-unit vtable routes accepted
neighbor handling through the callback at guest `0x8209FC70`.

For each accepted candidate, that callback computes:

```text
goalX  = candidate[+192] + self[+832]
goalZ  = candidate[+200] + self[+836]
errorX = goalX - self[+80]
errorZ = goalZ - self[+88]
```

The self fields `+832/+836` are formation-slot offsets. The callback then uses
two delayed recovery gates:

| Gate | Established trigger | Delay |
| --- | --- | ---: |
| Internal unit types 2, 3, and 14 | Self moved less than 100 units per axis from cached `+956/+960`, and squared target error exceeds 250,000 | 3 ticks, or 8 when byte `+985` is clear |
| General | Target error exceeds candidate radius `+188` (falling back to `+180`) plus 4,000 | 5 ticks |

When a timer expires, virtual slot `+0xD4` receives `goalX/goalZ`, and field
`+32` of the optional object at self `+924` is set to 1. On the base unit
vtable, that slot resolves to guest `0x820946F0`: it converts the requested
point to a movement displacement in `+564..+572`, invokes the next movement
hook, and clears the five-entry breadcrumb queue. When neither recovery gate
applies, both timers reset to `-1` and the current position is cached in
`+956/+960`.

The arithmetic always pulls toward the candidate anchor plus the unit's own
formation offset. It does not accumulate a repulsion, alignment average, or
boids-style steering force. The established role of this callback is delayed
formation cohesion/recovery. The producer of every candidate field and any
separate short-range collision or separation response remain to be traced, so
formation recovery and local avoidance must still be modernized as independent
systems.

## Serialized NAV format

All 36 supported NAV files use one bounded big-endian layout:

1. 16 reserved zero bytes;
2. `u32` triangle count;
3. one 40-byte record per triangle:
   - three `float3` vertices;
   - one `u32` attribute;
4. one 12-byte signed adjacency record per triangle;
5. `u32` dynamic-range count; and
6. `(u32 start, u32 count)` for each dynamic range.

Runtime edge numbering is:

- edge 0: vertex 0 to vertex 1;
- edge 1: vertex 1 to vertex 2; and
- edge 2: vertex 2 to vertex 0.

The checked-in parser rejects nonzero reserved bytes, truncation, trailing data,
non-finite vertices, unsafe counts, and out-of-range adjacency indices. It
reports exact shared-edge reciprocity, duplicate/self adjacency, invalid or
overlapping dynamic ranges, static triangles inside dynamic ranges, and
uncovered nonzero-attribute triangles.

The supported corpus contains:

- 36 NAV files;
- 26,815 triangles;
- 531 nonzero-attribute dynamic triangles;
- 112 dynamic-range records; and
- 111 valid ranges that cover all 531 dynamic triangles exactly once.

`VZ_MY.NAV` also contains one invalid seventh range `(1708, 17)` despite having
only 889 triangles. The parser preserves and reports this stale-looking record
without making the six valid groups unusable. Whether mission code ever
requests dynamic group index 6 remains unproven.

## Runtime NAV graph

Each serialized triangle becomes a 252-byte runtime object:

| Offset | Established content |
| --- | --- |
| `+0` | serialized attribute reduced to a Boolean |
| `+8..+32` | normalized plane data and reference point |
| `+36..+68` | three vertices |
| `+72..+80` | centroid |
| `+84..+164` | three planar edge tests |
| `+168`, `+172`, `+176` | neighbor pointers |
| `+180` | search generation |
| `+184` | accumulated `g` cost |
| `+188` | heuristic |
| `+192` | open/closed state |
| `+196` | edge leading toward the destination |
| `+200..+232` | three portal midpoints |
| `+236` | portal 0-to-1 distance |
| `+240` | portal 1-to-2 distance |
| `+244` | portal 2-to-0 distance |
| `+248` | active/traversable byte |

The constructor at guest `0x821E4520` establishes the edge numbering,
centroids, portal midpoints, and transition distances. Point lookup uses the
precomputed X/Z edge tests and projects accepted points onto the triangle
plane.

## Original route search

The search centered at guest `0x821E5A20` works backward from the destination
triangle to the source triangle:

1. Initialize the destination with `g = 0`, `h = 0`, and artificial downstream
   edge 0.
2. Pop the lowest `g + h` triangle from a binary min-heap.
3. For each active neighbor, add an in-triangle portal-midpoint transition
   distance.
4. Store the reciprocal edge that leads back toward the destination.
5. Never reopen a closed triangle.
6. Stop when the source triangle is popped.
7. Starting at the source, follow stored edges and emit each crossed portal
   midpoint until reaching the destination.

The heuristic is 3D Chebyshev distance from a triangle centroid to the source
position. Search state is collapsed to one record per triangle even though the
cost to leave a triangle depends on both ingress and exit portals. Endpoint
costs are not part of `g`. These choices make the search fast and compact, but
they do not define a shortest-path algorithm for the emitted waypoint metric.

The offline compatibility model preserves float32 state, the backward search,
one record per triangle, the no-reopen rule, endpoint-cost omission, and stable
insertion ordering. Exact equal-key behavior in every translated heap case is
not yet claimed to be bit-for-bit identical.

### Transition-distance indexing defect

The runtime chooses one of the three stored distances using:

```text
index = abs(downstream_edge - candidate_edge)
distance = [d(0,1), d(1,2), d(2,0)][index]
```

Consequently:

- the 0-to-1 pair incorrectly uses `d(1,2)`;
- the 1-to-2 pair happens to use `d(1,2)`;
- the 0-to-2 pair happens to use `d(2,0)`; and
- equal edge indices use `d(0,1)`, including the destination's artificial edge
  0 case.

The tool's corrected compatibility mode changes only distinct portal-pair
selection. It deliberately retains the observed equal-edge behavior so that
the impact of the pair-index defect can be measured separately from endpoint,
state-model, heuristic, and closed-node changes.

### Deterministic route measurements

The checked-in analyzer sampled 40 deterministic centroid pairs from the
largest initially active component of every NAV file, using seed `0x4E335241`.
The reference is Dijkstra over `(triangle, ingress portal)` states with both
endpoint costs included.

| Measurement | Result over 1,440 routes |
| --- | ---: |
| Original corridor longer than reference | 500 routes (34.7%) |
| Mean original/reference ratio | 1.01314 |
| Original/reference 95th percentile | 1.06975 |
| Worst original/reference ratio | 1.36300 |
| Corrected-transition corridor longer than reference | 233 routes (16.2%) |
| Mean corrected/reference ratio | 1.00176 |
| Corrected/reference 95th percentile | 1.01210 |
| Worst corrected/reference ratio | 1.15892 |

Correcting the transition lookup removes most mean error but does not repair
the collapsed state model, endpoint omission, heuristic behavior, or no-reopen
rule.

## Route ABI and following

The guest route object holds the NAV graph, source and destination points and
triangles, a linked-list route container, and a waypoint count. A successful
route contains:

1. the source point;
2. one midpoint for every crossed portal; and
3. the destination point.

The follower consumes waypoint X and Z rather than stored route Y. X/Z
string-pulling is therefore the relevant first-order smoothing model. A native
replacement must still construct or adapt the expected guest-owned linked list
without violating allocator, iterator, or PPC-visible state invariants.

The caller at guest `0x8213F7E8` usually reuses a route while the goal remains
within 500 planar units of its cached position. Most callers do not force a
rebuild.

## Funnel smoothing

The analyzer orients each shared edge as a left/right portal in X/Z and applies
the simple-stupid-funnel algorithm to the original corridor. For the same
1,440 point-agent routes:

| Measurement | Result |
| --- | ---: |
| Planar length invariant failures | 0 |
| More than 1% shorter | 1,437 routes (99.8%) |
| Mean midpoint/funnel length ratio | 1.17529 |
| Median ratio | 1.16125 |
| 95th percentile ratio | 1.33104 |
| Maximum ratio | 1.99496 |
| Mean waypoint count | 43.29 to 8.15 |
| Mean waypoint-count reduction | 81.2% |

These are offline long-range centroid samples, not mission traffic. The
zero-radius result models a point agent. The tool can shrink each portal by a
requested radius and rejects portals narrower than the diameter, but this is
only a bounded first-order clearance model. It does not yet prove clearance at
arbitrary obstacle corners, account for formation width, or establish a safe
in-game actor radius.

## Dynamic topology and stale routes

Deactivation at guest `0x820E9A70` removes reciprocal adjacency for a range and
clears each node's active byte. Activation at guest `0x820F0B58` restores exact
shared-edge links and sets the byte. Six valid `VZ_MY` groups correlate with
`Ice_Gate` and `Gate1` through `Gate5`.

Only NAV construction, range deactivation, and range activation were found
writing the active byte. Neither mutation increments a topology generation,
clears route lists, nor notifies troops.

This creates a statically established stale-route sequence:

1. a troop obtains a corridor through an open dynamic group;
2. the group closes and removes live adjacency;
3. the troop retains its existing waypoint list because the goal did not move
   by 500 units;
4. live movement clipping prevents crossing the closed edge; and
5. the route remains active, so the troop can continue targeting an unreachable
   waypoint until another state change or sufficiently moved goal rebuilds it.

The clipping behavior and missing invalidation are established in code. A
troop visibly stalling at a closing gate has not yet been reproduced in
gameplay.

## Compatibility-first modernization

The safest boundary is the existing route-search call, not mission or troop AI.
Modernization should proceed through explicit modes:

1. **Original**: call the guest implementation and return its route unchanged.
2. **Shadow corrected**: run corrected transition lookup offline/native, record
   differences, but return the guest result.
3. **Shadow portal-state**: compare expanded-state Dijkstra with both endpoints,
   still returning the guest result.
4. **Opt-in corrected**: preserve the original corridor and waypoint ABI while
   changing only the pair lookup.
5. **Opt-in portal-state**: use the expanded state model while retaining
   authored NAV geometry and dynamic groups.
6. **Opt-in funnel**: string-pull with validated actor/formation clearance and
   a deterministic fallback to portal midpoints.
7. **Topology generation**: include a monotonic generation in the route cache
   key and force rebuild or safe stop when a corridor becomes invalid.
8. **Formation recovery and local avoidance**: preserve the reconstructed
   delayed `UNIT_FLOCKABLE` recovery contract, then locate and modernize any
   separate collision/separation response independently of global routing.

The first runtime wrapper should record bounded local metadata:

- request source/destination points and triangle IDs;
- active topology generation or deterministic active-group signature;
- selected mode and failure reason;
- expanded node/state count;
- corridor triangle and portal sequence;
- emitted waypoint count and length; and
- original-versus-shadow differences.

Logs must remain local and bounded. Instrumentation must not serialize game
assets or assume that constructing host nodes is equivalent to constructing
guest allocator-owned list nodes.

Regenerating a Recast/Detour mesh is a later option, not the first replacement.
It would need an explicit mapping for dynamic groups, special triangle
attributes, authored chokepoints, formation clearance, BSMAP paths, point
projection, off-mesh behavior, and mission assumptions. Preserving the existing
NAV graph first gives each algorithmic change a measurable compatibility
boundary.

## Required validation gates

Before any mode can become a default:

1. Keep malformed-input, topology, transition, exact-route, funnel, and
   clearance tests passing.
2. Reproduce supported-corpus totals and deterministic measurements.
3. Compare guest and native requests in shadow mode across representative
   missions, troop classes, route lengths, and dynamic-group states.
4. Test source/destination boundary cases, disconnected components, and failed
   point lookup.
5. Close and reopen a gate while a troop owns a corridor through it.
6. Validate small and large formations, siege/flying/specialized troops, combat
   transitions, and save/load.
7. Retain an immediate deterministic fallback to the original search.

Build success, process survival, lower offline path length, and fewer waypoints
do not establish gameplay correctness.

## Open questions

- What are the gameplay identities and unused behavior of factory troop
  categories 0, 1, and 9 and external world-object classes 4 and 12?
- What exact short-range collision or separation system operates alongside the
  reconstructed formation-recovery callback?
- Is invalid `VZ_MY` dynamic group index 6 ever referenced?
- How does a troop present in gameplay when its current corridor closes?
- Which actor and formation clearances are safe at every authored chokepoint?
- Does translated heap equal-key ordering change any corridor selected by the
  compatibility model?
- Which mission behaviors rely intentionally on midpoint routes or other
  non-shortest movement?
