# Development status

Updated 19 November 2026. The opening mission, following cutscene, and writing a
save were exercised on the earlier runtime. Loading saved progress also
succeeded on that tested opening route. The stable ReXGlue 0.11 migration has
bounded renderer validation but has not yet repeated that complete gameplay
route. Full-game coverage remains unvalidated.

## Current compatibility summary

- **Platform:** Windows 10/11 x64. Direct3D 12 is the default; Vulkan is an
  opt-in development backend.
- **Supported game:** USA/Europe executable `0.0.0.3`, identified in
  [game-build.json](game-build.json).
- **Validated route:** opening mission, following cutscene, and save/load on the
  tested opening path.
- **Known limitation:** full-game coverage is incomplete. The default 60 Hz
  host presentation target repeats frames from the established 30 FPS game
  clock; true 60 FPS simulation and unique rendering are not implemented.

## Verified

- XDVDFS game partition found at byte offset `0x0FD90000` in the supplied disc.
- Extracted 3,342 files / 5,770,038,003 bytes, with per-file SHA-256 hashes.
- Identified title `4D5307DB`, media `5D48689C`, executable version `0.0.0.3`.
- Strict ReXGlue analysis/codegen succeeds without `--force`.
- Generated 13,762 function assignments across 87 translated C++ source files.
- Windows x64 Release and RelWithDebInfo compile and link succeed with Clang 20.1.8.
- Runtime initializes Direct3D 12, input, audio, and XEX imports.
- Six JavaScript extractor tests and all 54 current native regression suites
  pass.
- A 30-second boot test survived until the harness stopped it, without the prior
  unregistered-function or floating-point failure.
- Windowed startup reaches the intro/title-screen presentation.
- Main menu and character selection reached, followed by the opening cutscene.
- Replay progresses past the previous opening-cutscene crash and reaches gameplay.
- Opening mission completed, the next cutscene played, and a save written.
- Saved progress loads successfully on the tested opening route.
- Desktop shortcut follows the stable launcher, using a 1280 x 720 window.
- The packaged Release binary initializes GPU, audio, input, and guest execution
  from a remembered game path and survives a 58-second isolated startup run.
  The harness stops that child; this check does not establish visual correctness.
- Native ISO import produces all 3,342 files with matching SHA-256 hashes against
  the original verified extraction. No game material is bundled with the release.
- Native setup now performs ISO copying on a worker while the UI continues
  processing messages and displays preparation, byte progress, and cancellation
  cleanup status. An interactive import produced all 3,342 files /
  5,770,038,003 bytes, saved the verified game path, and started the game without
  a Windows application-hang event. This single run does not validate every
  storage failure, cancellation timing, Windows version, or gameplay route.
- A native installed launcher exposes curated Play, Graphics, Language & Audio,
  Controller, and Keyboard & Mouse pages. It saves an installation-folder
  `n3.toml`; direct `n3.exe` startup was observed loading a distinctive 40 Hz
  value from that same file. Development profiles retain an explicit private
  config path.
- Physical-controller remapping now covers every digital game control, triggers,
  stick selection, and four axis inversions at the title's sole
  `XamInputGetState` wrapper. Native policy tests cover identity, disabled and
  duplicated sources, swaps, unknown button bits, and signed-axis limits.
  Actual play with a mapped physical controller remains unvalidated.
- Import cancellation cleans up its newly created output; existing destinations
  are rejected without alteration. Wrong revisions and malformed disc entries
  are rejected. Explicit and remembered game folders are revalidated.

## Corrections made during first boot

| Guest entry | Evidence | Treatment |
| --- | --- | --- |
| `0x8253F950` | Direct branch at `0x8254698C` in an object-adjustment thunk | Seed function discovery; generated body ends at `0x8253FA18` |
| `0x82588FF8` | Startup indirect-call trap | Seed discovery; generated body is a small tail-call initializer |
| `0x8253ED08` | Indirect-call trap during audio initialization | Seed discovery; preserve generated implementation |
| `0x8215B150` | Runtime indirect-call trap during the opening cutscene | Seed discovery; original function generated and registered; replay reaches gameplay |

The SDK's audio worker invokes guest callback `0x8253A590`. A first-chance fault
trace found `0xC000008F` with host MXCSR `0x8060` while executing the generated
`vcfsx` path in `sub_8254C600`. Host FP exception masks were clear. The local
callback wrapper initializes the host mask policy while preserving the guest's
rounding and flush bits, then calls the original generated callback. The next
30-second boot survived, and the windowed visual check reached intro/title.

Windows FP fault diagnostics write module offsets and a stack under the active
profile's `logs/floating-point-fault.txt`: `private/user/logs/` for the development
launcher or `%LOCALAPPDATA%\N3Recompiled\logs` for default release profiles.
Stack frames record module basenames rather than absolute installation paths.
`tools/symbolize-fault.ps1` resolves executable frames against the local build/PDB,
supports `-Executable` for another build, and accepts older reports with full
module paths. Diagnostics installation failure does not prevent startup.

The diagnostics regression raises a synthetic FP exception in an isolated
process, verifies report location and path omission, and confirms that the
exception continues to the next handler with its original context. This is
diagnostics coverage, not evidence of an additional gameplay fault.
The same probes pass on a thread with a 64 KiB stack. Large diagnostic scratch
buffers use serialized static storage so exception entry does not exhaust small
runtime thread stacks. The updated development build passes a 30-second startup
check using a separate profile/cache; the harness stops only its test child.

## Opening cutscene

The first cutscene run exhibited presentation glitches and terminated at an
unregistered indirect target, `0x8215B150`. The target is now included in strict
function discovery, emitted as an original-code translation, and present in both
generated function registration tables. The native rebuild and callback FP test
pass. Replay progresses past the previous failure point and reaches gameplay.
The opening route now extends through mission completion and the following
cutscene. This does not establish broader cutscene coverage or resolve every
previously observed presentation glitch.

## Alpha distribution

The first Windows x64 alpha adds native first-launch selection of an ISO or an
extracted `default.xex`, executable hash verification, optional one-time disc
import, and a remembered local game path. Direct EXE startup defaults to a
1280 x 720 window. Explicit runtime settings retain precedence. Packaged saves, remembered game data, imports, caches, and logs default to
`%LOCALAPPDATA%\N3Recompiled`; packaged settings use `n3.toml` in the writable
application folder. Development launcher profiles and their explicit config
files stay under `private/`.

The package uses an explicit file allowlist, includes runtime dependencies and
third-party notices, omits PDBs and local game/profile/log data, and checks binary
strings for build-machine identifiers. Corresponding SDK/dependency sources and
their pinned revision manifest accompany the release. One full interactive ISO
import completed with responsive progress and a verified output; importer and
path logic also have native automated coverage. Other storage failures and
cancellation timings remain bounded rather than exhaustively validated.

## One-click source setup

An existing source checkout now has a top-level `setup.cmd` entry point that
uses built-in Windows PowerShell 5.1 to display a responsive setup wizard.
The wizard selects the owned ISO, build type, parallelism, and shortcut
preference; requires explicit Microsoft development-tool license consent; and
shows stage progress plus command output. It installs checksum-pinned portable
PowerShell 7.7.0, Python 3.14.10, Node.js 22.23.5, 7-Zip 25.01, and MinGit
2.56.1 under `.tools`, verifies the on-disc `default.xex` before a large import,
then runs the existing pinned compiler bootstrap and native build. No
administrator access or global development-tool installation is required.

Setup-owned tool replacements and game extraction use staging paths. Existing
verified downloads, portable tools, `private\game`, and compiler outputs are
reused. The desktop shortcut still targets `tools\launch.ps1`, now with
`-Settings`; the native launcher forwards the source checkout's explicit game,
user, config, cache, and log paths to `n3.exe`.

The portable-tool install and reuse paths completed from Windows PowerShell
5.1, including MinGit 2.56.1. Portable Node verified the supported read-only
ISO and passed all six extractor tests. Portable Python imported both repository
and tooling modules. With global development-tool paths removed, the complete
headless setup path reused the verified extraction, bootstrapped the compiler
stack, built the runtime, and passed all 54 native suites. The actual wizard
controls completed the same incremental pipeline and opened the native
launcher. Offline setup planning passed 37 checks under Windows PowerShell 5.1
and portable PowerShell 7; development launcher planning passed 136 checks. The
wizard was rendered and inspected at the development system's current DPI.

The full wizard validation reused an existing verified `private\game`; it did
not repeat the new setup-owned 5.8 GB staging/rename path from an empty checkout.
The real ISO pre-verification, lower-level extractor, and earlier full imports
are covered separately. Interrupted network transfers, every storage failure,
enterprise download policy, other Windows builds, DPI/accessibility variants,
and clean-machine performance remain bounded rather than exhaustively tested.

## Installed settings launcher and controller remapping

The Windows package now builds `n3_launcher.exe` as its documented default
entry point. The native launcher exposes game-data reselection; window,
renderer, resolution, scaling, filtering and VSync controls; text/subtitle and
spoken-audio selection; audio gain and mute behavior; physical-controller
mapping; and all keyboard/mouse controller bindings. Save and launch failures
are reported. The configuration model parses and validates curated values,
checks keyboard/mouse names with the runtime input-source parser, updates nested
TOML atomically, and retains unrelated settings.

Packaged launcher and direct-game starts share `{app.root}/n3.toml`.
`tools\launch.ps1` now passes an explicit profile-local `--app.config_file`, so
source-development profiles remain isolated. The launcher saved a 1,919-byte
configuration through its actual Save button. Direct `n3.exe` then logged
`N3 display presentation target: 40 FPS` from a launcher-selected value before
the harness stopped that validation process. The value was restored to 60
afterward. The actual Play button started `n3.exe` and closed the launcher.
The current native build passes all 54 suites, the development-launcher
regression passes 136 checks, and all 7 release-package tests pass.

All five pages were rendered and captured from the running Win32 application
at the development system's current DPI; the visible controls fit the fixed
window. The Play page, shared path, Graphics, Language & Audio, Controller, and
Keyboard & Mouse surfaces were inspected. This is one Windows/DPI observation,
not broad accessibility, localization, monitor-scaling, or hardware coverage.

The physical pad adapter replaces translated wrapper `sub_8252E5F0`, calls the
original `XamInputGetState` import, and remaps only successful 16-byte guest
states. Defaults are identity mappings and unknown button bits are retained.
Policy coverage includes button swaps, disabled and duplicated inputs, trigger
and stick swaps, and saturating inversion of `-32768`. The current attached
`0x1532/0x0208` device had no SDL gamepad mapping, so no real mapped-controller
gameplay pass was possible. Rumble routing, input latency, multiple users, and
a complete gameplay route remain unvalidated.

The F4 advanced overlay and the installed launcher write the same packaged
configuration. The overlay's `hid.keybind_*` values describe keyboard/mouse
emulation, while `n3.controller.*` describes physical remapping. The launcher
is the curated interface and F4 remains the advanced runtime editor.

## Graphics menu and presentation-rate control

The development build adds Graphics below Tutorial on the main menu and a
separate native page derived from the Options layout. The page contains 30,
40, and 60 Hz presentation choices plus 1x / 2x / 4x / 8x / 16x anisotropic
filtering. New installations default to a 60 Hz host presentation target.
Settings apply without a restart and persist through the existing local profile
configuration. Original Options retains its audio, camera, vibration, and
contrast controls.

Anisotropic filtering now uses only numeric choices. 1x explicitly disables
anisotropy; the other choices select their matching sampler limits. Old Game
default, legacy 1x-enum and unsupported overrides normalize to 1x on startup and
when opening Graphics. Existing 2x/4x/8x/16x overrides retain their values. The
RelWithDebInfo build passes all twenty-three suites. A fresh-profile 55-second
Direct3D graphics audit verifies all five actual sampler limits, all display and
render presets, and both VSync presentation policies. This is renderer evidence,
not a visual gameplay or texture-quality comparison. Alpha 7 packages these numeric choices; Alpha 6 retains its previous labels.

The page also separates display/output size (720p, 1080p, 1440p, 4K) from internal
rendering (720p/1x, 1440p/2x, 4K/3x). Display changes resize a normal window on the
UI thread, accounting for Windows display scaling. Maximized/fullscreen windows
use desktop output dimensions, and logical-pixel rounding may slightly change
the requested client dimensions. Explicit launch dimensions retain precedence.

The menu layout and text are generated locally from the player's Menu/Text
files into a profile cache, mounted read only through runtime VFS directory
links. The source game folder is not modified. No derived menu assets or game
text are tracked or included in release packages. Installation failure removes
its new VFS links/device and retains the original menus. Added labels currently
use English across the supported menu-language tables.

| Entry | Treatment |
| --- | --- |
| `0x8218CDC8` | Route the main-menu Graphics button through the native Options transition |
| `0x82272470` | Select the separate Graphics layout for that transition |
| `0x821A8030` | Configure all four native selectors on every Graphics entry, including cached layout reuse |
| `0x821A8370` | Focus the first Graphics control after the entry transition completes |
| `0x821A8B30` | Apply Graphics selector changes without changing audio/camera settings |
| `0x82248D38` | Initialize recognized clock objects with the established 30 FPS game target and matching step |
| `0x8223FE70` | Preserve the 30 FPS game clock when the host presentation target changes |
| `0x823AA3B0` | Preserve the title's requested presentation interval |
| `0x823AA520` | Pace title frame production at 30 FPS; optional timing trace |

The selected `n3.frame_rate` now controls ReXGlue's independent host presenter.
The title's frame clock and simulation step remain at the established 30 FPS
policy; enable/suspend flags, presentation interval, and global guest clock keep
their existing behavior. With a 60 Hz target, ReXGlue can present the latest
completed title image again between game frames. The older `n3_60fps` flag is
retained as a hidden compatibility alias.

Anisotropic choices map to the SDK's hot-reloadable `anisotropic_override` enum,
not literal sample counts: 16x is enum 5. D3D12 evaluates the override while
building sampler parameters on draws and refreshes descriptors when those
parameters change. The override affects eligible mipmapped linear-filtered
textures; it does not force filtering onto every texture.

The native regressions execute the actual translated clock initializer and
switch the host target repeatedly among 30/40/60 without restarting. They prove
that the guest FPS, float step, period, suspended-clock state, and global clocks
remain unchanged while the graphics presentation limit follows the selection.
They also cover shared-registry updates, rejected rates, and strong hook
registration. Layout tests cover source/metadata preservation, malformed input,
truncation, and duplicate extension rejection. The supported local title/options
transformations also pass against the private game files.

The main-menu Graphics entry opens its separate native page. The original two controls
respond to navigation after focus is assigned at transition completion and
hidden controls are disabled. The final layout keeps selected labels on one
line. Live switching to 40 and 60 Hz presentation works, and 16x filtering
persists as SDK enum 5 in the local profile. These are tested menu/settings
outcomes, not true higher-rate simulation or full-game rendering validation.

Re-entering Graphics previously bypassed selector initialization when the native
layout cache skipped a fresh file load. Initialization now follows the explicit
Graphics transition, independent of the loader. The four sidebar labels align
with their banners, and a short noninteractive notification confirms local saves.

The pinned SDK serializer wrote raw Windows paths inside TOML basic strings,
making some generated profiles unreadable on restart. Graphics now writes typed
TOML with escaping and replaces the completed file atomically. Startup repairs
the identifiable legacy flat format when invalid; other malformed files are
left alone. The new regression checks string round trips through the SDK loader,
legacy recovery, malformed-file preservation, and resetting values to defaults.

## Live render resolution

The project builds its own Xenos plugin from the pinned SDK sources. At the end
of a completed swap it waits for GPU work, allocates replacement render targets,
texture caches and scale-dependent shader pipelines, reloads active shader
microcode, and updates EDRAM descriptors. Guest memory, GPU shared memory,
registers, the command ring and the presenter remain alive. Allocation or device
limit failures retain the previous resources and setting. This path is intended
for the main-menu Graphics page, whose next frame redraws render-target contents.

An isolated run switched from 1x to 3x (3840 x 2160) without restarting, logged the
applied scale, and continued presenting until the harness stopped its own child.
The subsequent interactive check confirmed live 720p/1440p/4K changes, retained
values after leaving with B and reopening Graphics, and the saved-settings
notification. Subsequent gameplay and broader rendering coverage remain pending.
The first published alpha
continues to use the original SDK plugin and does not include these controls.

Alpha 2 packages the four-row Graphics page, live render extension, cached-menu
re-entry correction and profile persistence fixes. Both build configurations pass
seven native suites, and the supported private menu transformations pass. A
separate Release run loaded a saved 40 FPS profile and switched from 3x to 1x
rendering without restarting, continuing until its own harness deadline.
The extracted alpha 2 Windows ZIP passes all packaged-file hash checks, reuses a
remembered local game folder, installs Graphics, and applies live 2x rendering.
It continues presenting until the isolated harness stops its child at 24 seconds;
this packaged startup check does not extend gameplay compatibility claims.

## Graphics audit and host VSync (development)

The native Graphics page now includes VSync On/Off below render resolution.
The pinned SDK's `vsync` flag controls guest vblank scheduling, while its original
Windows presenter always uses immediate presentation. The project presenter
controls DXGI directly with a separate saved `n3_vsync` setting. On uses interval 1,
a one-frame latency limit, a waitable swap chain polled before rendering, and
`DXGI_PRESENT_DO_NOT_WAIT`; Off uses interval 0 with tearing only when supported.
The shared callback types and runtime/provider remain unchanged. The initial
blocking interval-1 implementation slowed menus; the nonblocking path has been
checked interactively and restores responsiveness with VSync On.
See Microsoft's [frame latency guidance](https://learn.microsoft.com/en-us/windows/win32/api/dxgi1_3/nf-dxgi1_3-idxgiswapchain2-getframelatencywaitableobject).

Menu presentation now reads the requested FPS independently of gameplay-clock
initialization. Anisotropic Off disables anisotropy consistently, including
textures outside the forced-filter eligibility policy. Positive overrides retain
point/base-map behavior for ineligible textures. A GPU-thread probe uses isolated
fetch registers, the actual sampler-parameter implementation and real D3D12
sampler creation to check each override and eligibility case, without modifying
game registers or settings files.

Renderer audit traces show 1280x720, 1920x1080, 2560x1440 and 3840x2160 physical
window clients, and 1280x720/2560x1440/3840x2160 rendered swap sources. Exact sizing
corrects DPI rounding and restores a maximized window when selecting a preset;
oversized normal windows can extend beyond the display. Runtime-loaded plugin
staging now runs even when only GPU sources changed. Eight native suites pass.
The audit is an isolated developer probe; video cadence, descriptor verification
and successful resizing do not establish full-game graphics or animation timing.
The final Release audit completed all six sequences with every required backend
check passing through `tools/verify-graphics-audit.py`. Alpha 3 includes these
corrections and the nonblocking VSync menu control.

## Frame-rate validation limits

The current 60 Hz mode is deliberately a host presentation target, not a guest
simulation-rate override. ReXGlue repeats the latest completed title image at
the capped host cadence while N3 retains the established original-speed 30 FPS
game clock and existing presentation interval. This removes the known cause of
doubled gameplay speed, but it does not create 60 unique title frames or
establish smoother animation.

True higher-rate gameplay remains future work. The native step reaches the
engine worker through `0x8225FBE8`, `0x82316A78`, and `0x8230E560`; separate
paths also use integer frame counters and fixed increments. No unverified
animation multiplier or shared-constant patch has been applied. Matched
gameplay comparisons are still needed together with later-scene, scripted-event,
performance, presentation-cadence, and audio tests.

## Application icon

The application embeds an emerald-and-silver N3 icon with 16, 24, 32, 48, 64,
128 and 256 pixel variants. The window applies the embedded resource, and the
development shortcut uses the matching ICO. The full-resolution transparent
PNG contains pixel data only, without image metadata. Both build configurations
pass the eight native suites. Alpha 4 packages the icon inside n3.exe, so
Windows shortcuts made from the downloaded executable inherit it without a
separate image file. The development desktop shortcut has been refreshed.
Packaged icon resources load at all seven sizes; packaged file hashes and binary
privacy checks pass. Alpha 3 remains available unchanged.

## Portable native components

The disc parser/importer and menu asset transformations now build independently
with `N3_BUILD_GAME=OFF`, without ReXGlue or game data. Hashing and destination
checks use platform adapters; macOS uses CommonCrypto and Linux uses OpenSSL.
The Windows full build still passes eight suites, including added empty and
multi-block hash vectors and destination-link checks where privileges allow.
A workflow exercises the portable subset on Windows, Linux and Apple Silicon.
These components do not establish a Mac game build. See [porting roadmap](PORTING.md)
for the Vulkan/runtime work and native gameplay boundaries.

## Native frame-clock module

The game clock initializer at `0x82248D38` now uses a portable typed C++ module
for recognized rates, with a separate big-endian guest-memory adapter and the
original translated entry retained for unknown modes. The native model also
handles live rate/period updates without enabling suspended clocks. An 18-case
comparison against the translated initializer checks the full clock object,
original step bits, timebase sampling, frequency truncation and calling convention.
The portable suite checks invalid inputs without mutation. See
[native code boundaries](NATIVE-CODE.md). This change does not establish corrected
animation/combat timing or improved frame rates.

Release and RelWithDebInfo pass nine native suites. An isolated 26-second Release
startup uses Direct3D 12, exercises the native initializer at 60 FPS, and continues
presenting until the harness stops its own child. That check uses a fresh profile
and does not establish gameplay correctness or a timing fix. The Release binary
passes the existing build-machine identifier scan.

The active development source and launcher use Direct3D 12. The Vulkan prototype
is parked locally after a system-freeze report; no Vulkan change is released.

## Native shape-bounds batch

Five geometry helpers now use portable typed sphere, capsule and box bounds
operations with a separate guest-memory adapter. The original routines remain
available for nonfinite/subnormal input and overlapping source/output ranges.
The native library uses strict FP arithmetic with contraction disabled, retaining
the original signed-zero, negative-dimension and directed-rounding behavior.
The equivalence suite compares 12,800 synthetic cases against the translated
entries and checks whole-buffer writes, FP controls, calling convention and
indirect registration. The portable geometry suite needs no runtime or game data.
See [native interfaces and routine map](NATIVE-CODE.md). These checks do not
establish a performance gain or full collision/mission coverage.

Both Windows configurations pass eleven native suites. An isolated 24-second
Release startup presents through Direct3D 12 without logged errors until its own
harness deadline; this does not exercise every shape during gameplay. Executable
and GPU plugin privacy scans pass.

## Alpha 5 package

Alpha 5 packages the portable importer and native frame-clock/shape-bounds work
on Windows x64 with Direct3D 12. Both Windows configurations pass eleven suites;
the portable component CI passes on Windows, Linux and Apple Silicon. Packaged
file hashes, embedded icon resources and binary privacy scans are checked before
publication. An isolated packaged startup check uses a fresh local profile and
the supported game data; it does not establish further mission coverage.
Higher-FPS animation timing remains unresolved. Vulkan is not packaged.

## Native vectors and cached channels

Seven more engine entries now use typed C++ vector accumulation and synchronized
three/four-component setters. The adapter preserves double input-scalar precision,
float32 intermediate rounding, cache-first writes and fallback for exceptional
values, aliases and unmasked FP exceptions. Vector/control types have no dependency
on guest registers or the graphics API. The routine map and editable interfaces
are in [native module notes](NATIVE-CODE.md).

The new equivalence suite passes 14,336 cases against the retained translations;
the portable tests exercise explicit vector edits and synchronized values. These
interfaces provide code-level control over verified operations; identification
of gameplay roles and in-mission coverage remain pending. No animation-speed or
performance improvement is claimed. Direct3D 12 remains the active backend.

Both Windows configurations pass thirteen suites. A separate 24-second Release
startup presents through Direct3D 12 without logged errors until the harness
stops its own child; it does not identify or exercise every converted routine's
gameplay role. Executable and GPU plugin privacy scans pass.

## Native countdown, arithmetic and bit-field batch

Five further entries now expose typed C++ for a frame countdown, scalar addition
and subtraction with explicit signed-zero flushing, a little-endian bit-window
reader, and ratio-based vector accumulation. The countdown preserves the original
pre-decrement progress numerator, signed comparisons and unsigned wraparound.
Subtraction retains early float32 rounding of its second operand. Unsupported
FP inputs, unmasked traps, ambiguous bit windows and vector aliases retain the
original path. The guest adapters preserve condition/carry flags and keep
addresses outside the portable models. See [routine contracts](NATIVE-CODE.md).

The new equivalence suite passes 20,560 cases against the retained translations,
including all rounding/flush modes, counter boundaries, scalar edge patterns,
bit offsets/widths and unmasked-exception fallback with exact arithmetic.
Portable tests cover explicit state/input edits and rejection without mutation.
Both Windows configurations pass fifteen suites. An isolated 24-second Release
startup presents through Direct3D 12 at requested 60 FPS without logged errors
until the harness stops its own child. Binary privacy scans pass. These checks
do not identify every caller's gameplay role, establish further mission coverage,
or correct accelerated animation. This batch is included in Alpha 6.

## Alpha 6 package

Alpha 6 packages the vector/cached-channel and countdown/scalar/bit-field batches,
bringing the typed native replacements to eighteen. Both Windows configurations
pass fifteen suites, and six portable component suites pass CI on Windows,
Linux and Apple Silicon. The playable package remains Windows x64 with Direct3D
12. Package hashes, embedded icon resources, source correspondence and privacy
checks are verified, followed by an isolated packaged startup with a fresh local
profile. The package contains no game files or profiles and requires the player's
own supported disc data. These checks do not extend the previously tested
opening-route gameplay coverage or resolve higher-FPS animation timing.

## Native transformed-box geometry

Two further entries now use a portable affine-transform/box model: world-space
box bounds at `0x823602C0` and signed-coordinate corner/sample transformation at
`0x823604B8`. Basis rows, translation and half-extents are explicit editable C++
inputs, separate from guest registers and field offsets. The model preserves
Z/Y/X sum order, float32 intermediate rounding and explicit double FMAs; it also
supports scale/shear and retains negative-extent arithmetic. Exceptional sources,
unsupported scaled samples, aliases, stack overlaps and unmasked traps retain
the original path. See [native geometry contracts](NATIVE-CODE.md).

Both Windows configurations pass seventeen suites. The new equivalence suite
passes 16,416 comparisons against the two retained translations across all
rounding/flush modes, including integer boundaries, FP edge patterns, aliases,
all nonvolatile registers and explicit native-path checks. Portable tests cover
editable geometry and rejection without output mutation. An isolated 24-second
Release startup presents through Direct3D 12 at requested 60 FPS without logged
errors; the harness stops only its own child. Binary privacy scans pass. This
brings the development build to twenty typed native entry points. Alpha 6 remains
the published release with eighteen. No further gameplay coverage, player-hitbox
identification, performance gain or animation-timing fix is established.

## Native capsule projection and box sphere radius

Two more entries now use typed portable geometry: oriented capsule bounds at
`0x82366808` and the box enclosing-sphere calculation at `0x823603B0`. Capsule
center, axis, radius and half-height are explicit inputs; endpoint bounds and
their union are available to native callers. Strict endpoint comparisons preserve
signed-zero ties. The box radius retains float32 square/FMA stages, a double
square root and the original final float32 store, including overflow/underflow.
No generic length rewrite or axis normalization changes the original behavior.
Adapters retain exceptional/alias/unmasked paths and preserve `f1`/condition flags.
See [projection contracts](NATIVE-CODE.md).

Both Windows configurations pass nineteen suites. The new equivalence suite
passes 16,416 comparisons against the retained translations, across all rounding
and starting flush modes. It checks signed-zero ties, arbitrary/edge values,
aliases, all nonvolatile registers, FP result/control bits and native-path use.
Portable fixtures exercise editable dimensions and radius precision. An isolated
24-second Release startup presents through Direct3D 12 at requested 60 FPS without
logged errors until its harness stops its own child. Binary privacy scans pass.
The development build now has twenty-two typed native entry points; Alpha 6
remains the published release with eighteen. These checks do not establish
player-hitbox roles, further mission coverage, improved performance or corrected
higher-FPS animation timing.

## Native fixed-block delay/mixing kernels

Entries `0x8253BED8` and `0x8253C240` now use a typed native delay-block model with
512/2048-sample histories. Three tap delays/gains, cached outputs and cursor are
explicit editable C++ state. The model preserves the original 256-sample block,
257-sample outputs, read-before-write order, rounded tap products, double FMA and
cached-output prefix. Unsupported cursors, exceptional sources, aliases and
unmasked traps retain the translations. Per-thread workspace avoids placing
large history snapshots on callback stacks. See [delay contracts](NATIVE-CODE.md).

Both Windows configurations pass twenty-one suites. The equivalence suite passes
5,024 block comparisons against the retained translations across all rounding
and starting flush modes, including eight-block chains through cursor wraparound.
It checks whole-buffer history/state/output bytes, native-path use, unsupported
cases, all nonvolatile registers, output registers/pointers and FP controls.
Portable tests exercise delay/gain edits, continuity and rejection without
mutation. An isolated 24-second Release startup presents through Direct3D 12 at
requested 60 FPS without logged errors; its harness stops only its own child.
Binary privacy scans pass. This brings development to twenty-four typed native
entry points; Alpha 6 remains the published release with eighteen. Effect routing,
listening comparisons, performance and broader gameplay coverage remain unvalidated.
No animation-timing change is made.

## Native feedback-delay kernel

Entry `0x8253C310` now uses typed portable feedback-delay state: delay, two gains,
cached output and cursor. The model preserves rounded double FMAs, in-place
256-input/257-output behavior, feedback history and cached-output continuity.
It stages a full block before committing, so a nonfinite trial can fall back
without partial native writes. Generated subnormals and directed-rounding finite
saturation are preserved. Other cursors, unsupported source values, aliases and
unmasked traps retain the translation. See [feedback contracts](NATIVE-CODE.md).

Both Windows configurations pass twenty-three suites. The new equivalence suite
passes 2,512 block comparisons, including eight-block chains, impulse decay,
positive/negative overflow, rollback, aliases and all rounding/starting flush
modes. It checks whole-buffer state/history/output bytes, native-path use, guest
calling convention, nonvolatile registers and FP controls. Portable tests cover
editable feedback state and rejection without mutation. An isolated 24-second
Release startup presents through Direct3D 12 at requested 60 FPS without logged
errors; its harness stops only its own child. Binary privacy scans pass. The
development build now has twenty-five typed native entry points; Alpha 6 remains
the published release with eighteen. Listening comparisons, effect-role tracing,
performance and broader gameplay coverage remain unvalidated. No animation-speed
change is made.

## Next validation work

1. Measure the same gameplay scene under 30/40/60 host presentation targets and
   confirm that combat, cutscenes, and audio retain the established 30 FPS game
   timing across missions.
2. Repeat the opening route on the packaged Release build and other PCs.
3. Exercise later missions, characters, rendering effects, and large enemy counts.
4. Extend save/load coverage across later missions, repeated restarts, and profiles.
5. Compare scenes and timing against console or emulator reference captures.
6. Investigate additional indirect targets or translation problems from logs.

Other game revisions, title updates, platforms, and full-game playthroughs have
not been validated. Keep performance and visual claims tied to measured scenes.


## Native 128-sample feedback history

Entry `0x8253BFA8` now shares the typed feedback state and transactional native
core with the 256-sample kernel. It processes 256 inputs through two passes over
128 history samples, retaining the updated first-pass history for the second
pass. The adapter preserves its distinct final input loads in `f1/f2`, unsigned
carry result, pointer advance and cursor reset. Unsupported cursors, exceptional
sources, aliases, guest range wrapping and unmasked traps retain the translation.
A failed trial restores FP state before fallback and publishes no partial writes.

Both Windows configurations pass all twenty-three suites. Feedback equivalence
now covers both entries in 5,024 block cases across every rounding/starting flush
mode, including eight-block chains, modulo boundaries, input/history aliases,
late overflow after history wrap, generated subnormals, unmasked exact cases,
registers/flags and indirect registration. Portable fixtures exercise both history
sizes, gain/delay edits, read-before-write behavior and rejection without mutation.
A fresh-profile 24-second Direct3D Release startup reaches menu installation and
frame pacing with no logged errors; only the harness's child is stopped. EXE and
Direct3D plugin privacy scans pass in both configurations. These are kernel and
startup checks, not new listening/gameplay coverage or a speedup measurement.
Development now has twenty-six typed native entry points; published Alpha 6
still contains eighteen. Vulkan remains parked.


## Alpha 7 distribution

Alpha 7 packages twenty-six typed native engine entries, numeric anisotropic
filtering choices and the existing embedded N3 icon. It remains Windows x64 with
Direct3D 12. The native core passes ten portable suites on Windows, Linux and
Apple Silicon at conversion commit `40ed8d2`; both Windows game configurations
pass twenty-three suites. The numeric filtering audit verifies actual sampler
limits from 1x through 16x, display/render dimensions and VSync presentation.
See the release notes for packaging checks and unchanged gameplay limits.

## Native 512-sample feedback history

Entry `0x8253C480` now uses the typed feedback model with a 512-sample history.
Each call processes 256 inputs, writes one contiguous half, preserves the other
half, and alternates the cursor between 0 and 256. The original call sites chain
separate state objects over shared sample buffers; the native interface keeps
delay, gains, history and cached output explicit without changing that routing.
The adapter preserves pointer/cursor results, `f1/f2`, carry, condition flags and
nonvolatile registers. Unsupported cursors and exceptional/alias/unmasked cases
retain the original translation. Trial rejection publishes no partial writes.

Both Windows configurations pass twenty-three suites. Feedback equivalence now
compares all three history lengths in 7,536 block cases across every rounding and
starting flush mode. The 512-sample cases cover both initial halves, eight-block
chains, modulo-delay boundaries, untouched history, source exceptions, aliases,
late-overflow rollback from either half, finite saturation and unmasked exact
arithmetic. Portable fixtures also check cursor alternation, cached-output
continuity and preservation of the untouched half. A fresh-profile 24-second
Direct3D Release startup reaches menu installation and frame pacing without
logged errors; its harness stops only its own child. Both EXE and Direct3D plugin
privacy scans pass. This brings development to twenty-seven typed native entries;
Alpha 7 contains twenty-six. These checks do not establish listening quality,
new gameplay coverage, a speedup or corrected higher-FPS animation timing.

## Native independent two-tap processing

Entry `0x8253C758` now uses `DualTapDelayState`: two independent delay/gain pairs,
previous outputs and a cursor over 1024 history samples. The core processes 256
inputs per call, reads both delayed values before writing input history, and
preserves the untouched three quarters of that history. The guest adapter keeps
the two original cursor forms, buffer advances, product registers, `f1/f2`,
condition/carry flags and nonvolatile state. Unsupported inputs retain the
translation without publishing a rejected native result.

Both Windows configurations pass twenty-three suites. Delay equivalence now
compares three entries in 7,536 block cases across all rounding/starting flush
modes, including eight-block chains, source exceptions, finite extremes,
unaligned fields, input/output/state/stack aliases, unmasked exact cases and
indirect registration. Portable fixtures check separate gain edits, modulo
delays, four-block wrap, old-history reads, output prefixes, untouched history
and rejection without mutation. A fresh-profile 24-second Direct3D Release
startup reaches menu installation and frame pacing without logged errors. Both
EXE and Direct3D plugin privacy scans pass. These are synthetic/startup checks;
listening validation and broader gameplay coverage remain pending.

Development now has twenty-eight typed native engine entry points. The
[conversion plan](CONVERSION-PLAN.md) records coverage and work toward replacing
the remaining generated game routines; entry counts are not a completion
percentage. Alpha 7 remains the published build with twenty-six entries.

## Native separate-output feedback processing

Entry `0x8253C5F0` now uses the typed 512-sample feedback model with an explicit
separate output and final-output reference. It preserves the original split:
the separate 256-sample output contains a cached prefix and 255 new results;
the last new result is written to the input's extra slot and cached in state.
The 256 input samples stay unchanged. Cursors alternate between 0 and 256,
and unsupported inputs retain the original translation. Rejected trials publish
no history, state or output changes, and the adapter restores FP state before
fallback. Original stack scratch is 40 bytes, distinct from the in-place kernels.

Both Windows configurations pass twenty-three suites. Feedback equivalence now
covers four entries in 10,048 block cases, including split-buffer aliases,
unchanged inputs, both history halves, chained continuity, late overflow,
generated subnormals, unmasked exact arithmetic and calling convention checks.
Portable fixtures verify output canaries and the final-output reference's alias
rules. Test temporary files are isolated under the workspace. A fresh-profile
24-second Direct3D Release startup reaches menu installation and frame pacing
without logged errors; EXE and Direct3D plugin privacy scans pass. Independent
source review found no contract mismatch. Listening quality, broader gameplay,
performance and higher-FPS animation timing remain unvalidated.

Development has twenty-nine typed native entry points. The full readable-C++
conversion remains in progress; Alpha 7 still packages twenty-six entries.

## Native table-derived limit and bounded value

Entries `0x8209DBF0` and `0x8209D718` now use explicit channel selection,
`ValueLimitParameters` and `BoundedValueState`. The first selects a signed table
value, applies the original rounded percentage/baseline arithmetic and adds an
unsigned offset with 64-bit carry. The second changes float field `+664` by a
signed delta and applies lower then upper comparisons, preserving negative-bound
behavior. Their surrounding gameplay class and channel meanings are not claimed.
Unknown table/index layouts and exceptional arithmetic retain the translations.

Both Windows configurations pass twenty-five suites. A new equivalence suite
compares 4,128 cases against both retained routines, including the retained nested
callee in the adjustment oracle. It checks whole sparse-memory fixtures, aliases,
unaligned fields, all rounding/starting flush modes, integer extremes, source
exceptions, unmasked exact cases, return/condition/carry state, preserved registers
and indirect registration. Of these fixtures, 3,001 take the native path.
An additional 2,064 executions test production composition, including 96 cases
where a retained outer caller uses a native nested limit calculation.
Portable tests cover editable limit inputs, 64-bit carry, explicit bound order,
signed zeros and rejection without mutation. A fresh-profile 24-second Direct3D
Release startup reaches menu installation and frame pacing without logged errors;
both EXE and Direct3D plugin privacy scans pass. These checks do not establish
new gameplay coverage, a performance gain or corrected high-FPS animation timing.

Development now has thirty-one typed native entry points. Alpha 7 remains the
published release with twenty-six. Full readable-C++ conversion remains active.

## Native parallel table values and modifier updates

Three more typed entries now use the native limit model. Entries `0x8209DCF0`
and `0x8209DDE8` share the explicit channel selection and rounded percentage
calculation with the existing limit model. They read different 48-byte record
tables and use percentage fields `+736` and `+740`, respectively. Both return
the zero-extended truncated result directly, without the additive offset used
by `0x8209DBF0`.

Entry `0x820A13B0` uses `ValueLimitState` to replace the percentage field `+728`
when the mode's low byte is nonzero, or the offset field `+732` otherwise. It
recomputes the limit and applies only an upper comparison to float field `+664`.
No delta addition or lower clamp occurs. The model preserves signed zero,
negative limits and the full 64-bit return carry. A rejected native trial
publishes neither modifier nor value changes. Guest-memory aliases require
the original modifier-write-before-source-read order or the retained translation.
Surrounding gameplay classes and individual channel meanings remain unclaimed.

Both Windows configurations pass all twenty-five suites. Limit equivalence now
compares five entries in 10,640 fixtures, including 7,483 native paths. Another
4,448 executions check production composition, including 432 retained outer
callers with native nested calculations. Checks cover all rounding/starting
flush modes, mode upper bytes, integer/float extremes, partial/full source
aliases, unaligned fields, return carry, getter register results, preserved
`f3/f4`, modifier `f13`, condition flags and FP controls. New prologue-alias
fixtures use initially uncommitted root/descriptor targets that become valid
after the original saved-LR write. Guards reject before following stale pointers.
Portable fixtures cover editable modifier state, upper-only comparisons,
negative zero, directed rounding and rejection without partial publication.
A fresh-profile 24-second Direct3D Release startup reaches menu installation and
frame pacing without logged errors. Both EXE and Direct3D plugin privacy scans
pass. These checks do not establish new gameplay coverage, speed improvements
or corrected higher-FPS animation timing.
Development now includes thirty-four typed native entry points. Alpha 7 still
packages twenty-six entries. Full game-code conversion remains in progress.
Generated game translations already compile as C++; this work exposes readable
typed state and behavior while Python build/release tooling remains intact.

## Native percentage updates and capped accumulation

Entry `0x8209D688` now computes an integer percentage of the table-derived limit
and applies that delta to the bounded value at `+664`. Both signed integers
round to float32 before two separately rounded multiplies. The limit is computed
again before the lower/upper comparisons. Its eleven visible callers include
fixed percentages and signed record values; their broader gameplay units still
need matched-scene identification.

Entry `0x820B4DC8` uses the parallel table getter and optionally adds a percentage
when byte `+1336` or `+719` is nonzero, using signed percentage `+1376`. The base
and truncated increment bits are zero-extended before a 64-bit addition, retaining
carry even for negative increments. The inactive branch still calculates the
base while skipping unused percentage arithmetic. Original data contains function
pointers to this entry; its indirect use has not been observed at runtime.

The two hooks exclude all nested scratch (256 and 128 bytes respectively), keep
`f1` through `f4`, and restore controls before rejected trials. A retained outer
call keeps its entire original nested chain: scratch writes can change later
flags or percentage reads outside a leaf getter's object range. Tests compare
all bytes and all GPR/FPR results for these fallback calls without normalizing
scratch, then verify a later ordinary call still selects native code.

Entry `0x8209D7A8` now exposes scaled accumulation and optional accounting as typed
state. It adds the converted increment to field `+680` with 32-bit wrapping, then
caps its signed result at 999999 without a lower clamp. An enabled owner updates
the total/count at global object offsets `+4712` and `+4708`; stored words wrap
while register results preserve 64-bit carries. Aliases that would change a
later source retain the original; aliases with already-consumed sources remain
supported. No score, currency or experience role is assumed from this arithmetic.

Both Windows configurations pass all twenty-eight suites. Percentage equivalence
compares 8,352 cases (4,783 native, 3,569 complete retained chains), plus sixteen
post-fallback native probes. Accumulator equivalence compares 2,064 cases (1,152
native) and every GPR/FPR result. They cover all rounding/starting flush modes,
conversion boundaries, negative values, carry, flags, unaligned fields, source
and scratch aliases, exceptional trials and exact unmasked calls. Portable
fixtures include a two-rounding counterexample, editable percentage/cap inputs,
inactive unused sources, accounting wrap and rejection without publication.
The existing limit comparisons also pass after the shared truncation refactor.
A fresh-profile 24-second Direct3D Release startup reaches menu installation and
frame pacing without logged errors; both Windows EXEs and Direct3D plugins pass
binary privacy scans. These checks do not add gameplay coverage, establish a
speedup or correct higher-FPS animation timing.

Development now has thirty-seven typed native entries. Alpha 7 remains the
published build with twenty-six; the full game-code conversion is ongoing.

## Native handle and payload interfaces

Five connected entries now have typed implementations, bringing development to
forty-two distinct addresses verified against the source hooks. Alpha 7 remains
the published build with twenty-six entries, using Direct3D 12.

Entries `0x82081138` and `0x82080780` expose bounded 12-byte handle records,
packed-key/index extraction and full-word key matching. The index uses the key's
sign-extended low 16 bits before an unsigned bounds comparison. The guest
adapters retain unknown table geometry and invalid cases, and account for the
validator's original 112-byte frame plus its separate positive argument homes.

Entry `0x8209D358` copies a typed 100-byte payload with explicit integer and
float groups. Normal floats and signed zeros use native copies; exceptional
transfers, unmasked traps and overlapping guest fields retain the ordered
translation. Entry `0x8209D280` installs that payload at `+336`, optionally sets
the enable word at `+412` and vector at `+420`, and conditionally multiplies words
`+356/+360`. Multiplication requires signed own kind at least 6, a matching handle,
related kind 1000 and variant other than `0xFFFFFFFF`. The low product is stored;
the full signed product and branch-dependent return registers are retained.

Entry `0x8209DEE0` selects category 2 when a matching related object has kind 6
or 1000; otherwise it keeps category byte `+969`. It reads the 48-byte table at
descriptor offset `+216`, uses signed percentage `+784`, and returns truncated
bits without an additive offset. Both outer entries exclude all 240 bytes of
nested stack writes and preserve complete retained chains for source/write aliases.

Both Windows configurations pass thirty-four suites. Handle equivalence compares
3,584 calls over all rounding, flush and exception-mask combinations, including
1,024 native packed validations and 768 retained wrapper chains. Payload-copy
equivalence compares 2,064 cases (1,344 native). The two outer state operations
compare 4,896 cases (3,312 native), with explicit coverage of signed products
wider than 32 bits, sentinel skips, optional vectors, stale keys, category changes,
unaligned fields and ordered source/descriptor/record/stack aliases. All compare
whole fixtures; native-only normalization removes untouched original scratch.
Retained calls compare every byte and scalar register. The installer also checks
all native scalar register outputs; the related table calculation checks its
return and index/base registers, `f0/f13`, `f1` through `f4` and nonvolatile state.
Upper pointer halves, condition/carry flags, LR and FP controls are covered.
Read-only guard fixtures use uncommitted old pointers to require rejection before
traversal. Subsequent native calls verify retained scopes are released.

Portable fixtures exercise editable typed records, source/optional float
rejection, signed index/key boundaries, multiplier gates and transactional
publication. A fresh-profile 24-second Direct3D Release startup reaches menu
installation and frame pacing without logged errors. Both Windows EXEs and
Direct3D plugins pass binary privacy scans. No new gameplay coverage, performance
result or full-platform support is claimed. Broader progression and callback-driven state remains
translated until explicit ownership, side-effect and callback interfaces are
established. The full readable-C++ game-code goal remains active; Python
build/release tooling is unchanged and Vulkan remains parked.

## Native direction normalization and accumulation

Entry `0x823B3C00` now uses explicit squared-length and normalization stages in
`DirectionNormalization`. The native math retains the translated vector
reduction order, signed-zero input flushing, threshold decision, rounded square
root and reciprocal, separate Newton correction and final four-lane multiply.
The raw fourth lane does not contribute to length. Its unused exceptional values
are allowed on the zero branch. Unsupported tiny/nonfinite active arithmetic
retains the translation. There are 240 static call sites across 147 translated
callers; this is static reach rather than a gameplay execution measurement.

Entry `0x8209D8E8` exposes current state, default/override directions and amount.
It selects by the override's squared length, rounds each scaled component before
adding it, and preserves branch-specific operand order and scalar subnormals.
The guest fields remain `+64`, `+564` and `+576`. Data references suggest indirect
dispatch, but its execution has not been observed in a gameplay trace.

Both adapters reproduce original scratch writes and observable scalar/vector
register results, reject source dependencies on scratch, and preserve the vector
and scalar FP-control transitions. Normalization also writes the original
output-pointer argument home. Strict FP environment access prevents a threshold
conversion from moving past a flush-mode change. A square-root fixture was
corrected after an isolated comparison showed the CRT and translated SIMD root
agree in every rounding mode; no replacement math was needed for that check.

Both Windows configurations pass thirty-eight suites. Normalization equivalence
compares 4,384 calls (3,184 native); direction accumulation compares 2,816
(1,216 native). All fixture bytes match without scratch normalization, together
with all GPR/FPR/VMX registers, condition fields, LR/CTR/XER, indirect registration
and FP controls. Cases include every rounding/starting flush mode, unaligned
fields, safe output overlaps, scratch aliases, exceptional/tiny/overflow values,
unmasked exact calls and divergent host/guest controls. Portable fixtures exercise
editable state, exact math stages, directed rounding, host flush independence,
generated scalar subnormals and rejection without publication. Sticky exception
status is outside the scalar/vector comparison contract.

A fresh-profile 24-second Direct3D Release startup reaches menu installation and
frame pacing without logged errors. Both Windows EXEs and Direct3D plugins pass
binary privacy scans. These checks do not establish new gameplay coverage,
performance improvements or corrected higher-FPS animation timing.

Development now includes forty-four typed native entry points. Alpha 7 remains
the published build with twenty-six. The larger direction-basis caller
`0x8209D9B0` remains translated and is the next connected conversion boundary.
The full readable-C++ game-code conversion remains active; build/release tooling
is unchanged and Vulkan remains parked.

## Native direction basis and physical address mapping

Entry `0x8209D9B0` now composes typed signed-axis input, selected basis and output
state. It preserves the no-write, null/default and composed-basis branches.
The active branch normalizes the basis, derives a right vector with separately
rounded cross operations, weights the two directions and normalizes their sum.
The model exposes input preparation, deferred selected-record composition and
finalization separately. Explicit rounded input lets initial scalar conversions
use incoming host rounding while later vector math uses guest rounding.

The guest adapter preserves wrapped `slot * 12` addressing, all register results,
the full original scratch and argument-home writes, and raw fourth lanes. A local
overlay reconstructs the last vector load after unaligned scalar stores, before
the final normalized stores round their addresses down. Prologue/source aliases,
post-write threshold dependencies and unsupported math retain the original.

At that milestone, the three direction adapters used the then-pinned runtime's
physical-memory host bias at guest `0xE0000000` and above. All scalar/raw
accesses and alias checks used the mapped host offsets. Cross-boundary buffers
retained the original sequence.
An audit found forty older memory-backed typed entries still need this migration
and physical fixtures. Their current equivalence evidence covers virtual memory.
The next memory batch connects handle, payload, table and accounting adapters
before the geometry/vector/primitives, audio and cached-clock families.

Both Windows configurations pass forty suites. Basis equivalence compares
4,672 calls (3,728 native), plus 384 production nested-normalizer compositions.
Its independent oracle forces all three nested normalizers retained. Expanded
normalization equivalence covers 4,640 calls (3,400 native); accumulation covers
3,072 (1,440 native). All three suites compare whole fixtures including scratch
and argument homes, all scalar/vector registers and control state. Physical cases
use independent address setup and unbiased-memory canaries. Coverage includes
high inputs, records, targets, stacks, wrapped table cells, aliases and boundary
fallback. A physical home-alias fixture was corrected to keep the original's
reloaded pointer mapped; no implementation change was needed for that fixture.
Portable basis tests cover edited state/parameters, deferred operands, phase
rounding, sign-sensitive cross operations, scalar underflow and transactional
rejection. Transient sticky exception status remains outside these FP contracts.

A fresh-profile 24-second Direct3D Release startup reaches menu installation
and frame pacing without logged errors. Both Windows EXEs and Direct3D plugins
pass binary privacy scans. These checks establish no additional gameplay route,
speed improvement, corrected animation timing or full-game platform support.
Development now has forty-five typed native entry points; Alpha 7 still packages
twenty-six. The complete readable-C++ game-code conversion remains in progress.

## Alpha 8 publication

Published `v0.1.0-alpha.8` from source commit
`7f1d2c52e70beffa4bb73de81b02107e02830da3`, including all forty-five typed native
entry points. The public tag resolves to that commit. README download links,
packaged instructions and release notes now describe Alpha 8. Both Windows
configurations pass forty suites; all eighteen portable component suites pass on
Windows, Ubuntu and Apple Silicon in the
[matching CI run](https://github.com/WK2D/N3-Ninety-Nine-Nights-Recomp/actions/runs/39738204114).

The Windows package contains 76 allowlisted files. All member hashes, CRCs,
fixed ZIP metadata and the source-commit manifest were verified. Packaged runtime
binaries match the tested Release outputs. Every embedded icon image matches the
project ICO; the Windows resource compiler fills its unspecified plane count.
The extracted importer's usage entry point and a fresh-profile 24-second
Direct3D startup pass. The latter reaches menu installation and frame pacing
without logged errors and stops only its own child process.

The optional corresponding-source archive passes CRC checks and its six local
renderer/build-extension hashes match. Binary privacy checks pass; game data,
saves, profiles, paths, logs, PDBs and loose images are excluded from the Windows
package. All three uploaded asset SHA-256 digests match their local files, and
the public prerelease has exactly the Windows ZIP, optional source ZIP and
checksum list. Existing local saves/settings and the stable development launcher
remain in place. This release adds no new gameplay-validation or performance
claim; full conversion and the older adapters' physical-address audit remain open.

## Physical memory for connected native state

Thirteen existing C++ entries now use the shared physical-shadow address mapping:
seven bounded/table/percentage operations, capped accounting, two handle queries,
payload copy and the two outer relation operations. All direct word and byte
accesses use mapped host pointers, including category and enable flags. Complete
object/table/payload/frame ranges reject wrap and shadow-boundary crossings before
dependent reads. Mapped aliases preserve post-write/prologue dependencies through
the retained chains. Handle argument homes and below-SP scratch remain separate
ranges. The portable state/math interfaces and entry count are unchanged.

Both Windows configurations pass forty suites. Expanded comparisons cover
11,920 bounded-value cases (8,338 native), 8,864 percentage cases (5,111 native),
2,320 capped accumulation cases (1,296 native), 4,608 handle cases, 2,320 payload
cases (1,544 native) and 5,408 relation cases (3,640 native). Bounded-value
production composition adds 4,960 executions, including 480 retained outer
callers using a native nested calculation. The other retained-chain and
post-fallback checks continue to pass.

The new physical fixtures total 3,840 calls: 2,712 native and 1,128 retained.
Independent setup mapping, whole committed-region comparisons and unbiased
output/counter canaries cover high objects, roots, owners, descriptors, tables,
payloads, vectors, stack/homes and upper pages. Cases include unaligned fields,
counter carry, wide signed products, full boundary/wrap fallback and pointers
overwritten by the original prologue. A related-table fixture was corrected to
select the category that actually crosses the boundary; no adapter change was
needed for that fixture. Test-only flags prove handle/accounting native routing.
Existing per-entry register/FP contracts remain, with preserved VMX and condition
checks added to handle, payload, relation and accounting fixtures. Untouched
native scratch is normalized only where the earlier contract permits it;
retained calls compare every byte.

A fresh-profile 24-second Direct3D Release startup reaches menu installation and
frame pacing without logged errors; both Windows EXE/plugin privacy scans pass.
Physical-shadow coverage now includes sixteen of the forty-five typed entry
points. Twenty-seven older memory-backed entries remain to audit, alongside the
two scalar-only entries that have no guest-memory access. No new gameplay route,
performance improvement or corrected higher-FPS animation timing is established.

## Alpha 9 publication

Published `v0.1.0-alpha.9` from source commit
`0b80b4080dfafd2afa8456d8bec9f44411fdea9e`. The public tag resolves to that
commit. The Windows package includes all forty-five typed entries, with the
thirteen connected state adapters' physical-address fixes. Both Windows builds
pass forty suites; all eighteen portable suites pass on Windows, Ubuntu and
Apple Silicon in the
[matching CI run](https://github.com/WK2D/N3-Ninety-Nine-Nights-Recomp/actions/runs/39740315468).

All 76 allowlisted package members, archive CRCs, fixed metadata, manifest commit
and corresponding-source hashes pass verification. Packaged binaries match the
tested Release outputs, and every embedded icon image matches the project ICO.
The extracted importer entry point and fresh-profile 24-second Direct3D startup
pass; the startup reaches menu installation and frame pacing without logged
errors. Binary privacy checks pass, and the tracked PNG contains only image-data
chunks. Game data, profiles, logs, PDBs and loose images remain excluded.
The public prerelease has exactly the Windows ZIP, optional source ZIP and
checksum list, with all uploaded SHA-256 digests verified. The broader conversion
and remaining twenty-seven memory-backed adapter audits stay in progress.

## Physical memory across the existing typed modules

The other twenty-seven memory-backed adapters now use the pinned physical-shadow
mapping: five bounds, four box/projection, seven vector updates, three memory
primitives, seven audio kernels and the clock initializer. Full object, buffer
and scratch spans reject wrap and shadow-boundary crossings before snapshots;
aliases compare mapped host ranges. The cached clock view and presentation
interval word also use mapped addresses. Clock initialization checks its full
208-byte nested frame. Countdown progress rejects aliases with its 16-byte scratch
before publishing state, while inactive/expired branches ignore unused stack.
Clock, box-sample and box-sphere native results now match the original's
zero-extended 32-bit saved-LR restoration. Geometry retains divergent guest-off/
host-on flush controls; portable math APIs and entry counts are unchanged.

Both Windows configurations pass forty suites. Existing virtual fixtures remain
unchanged, with separate independent sparse physical passes adding 14,536 calls:
8,680 native and 5,856 retained. Shape bounds add 3,200; vectors 1,792; memory
primitives 768; transformed boxes 768; projections 768; delay blocks 1,128;
feedback blocks 1,504; clock initialization 4,608 plus 51 cached live-rate changes.
Coverage includes individually high objects/buffers/SP, unaligned fields,
host offsets above 4 GiB, exact tails, shadow/wrap fallback, prologue aliases,
history wrap, late audio rejection, all rounding/initial flush modes and
preserved scalar/vector/condition/FP contracts. Independent setup mapping,
whole committed-region comparisons and unbiased canaries detect wrong addresses.
Only proven untouched native scratch is normalized under each existing contract;
retained clock calls normalize their nondeterministic timestamp only.

A fresh-profile 24-second Direct3D Release startup reaches menu installation and
frame pacing without logged errors. Both Windows EXE/plugin privacy scans pass.
All forty-three memory-backed typed entries now have physical fixtures, with two
additional scalar-only entries. This finishes the address audit of the existing
forty-five-entry subset. Full readable-C++ game conversion remains in progress;
these checks establish no new gameplay route, performance gain or animation fix.

## Alpha 10 publication

Published `v0.1.0-alpha.10` from source commit
`07e107a3eaee3b04acfc4b23c0f03931800befab`. The public tag resolves to that
commit. All forty-five typed entry points are packaged, with physical fixtures
for all forty-three memory-backed entries. Both Windows configurations pass
forty suites; all eighteen portable component suites pass on Windows, Ubuntu
and Apple Silicon in the
[matching CI run](https://github.com/WK2D/N3-Ninety-Nine-Nights-Recomp/actions/runs/39743331088).

All 76 allowlisted package members, CRCs, fixed ZIP metadata, source-commit
manifest and corresponding-source hashes pass verification. Packaged runtime
binaries match the tested Release outputs, and every embedded icon image matches
the project ICO. The extracted importer entry point and a fresh-profile
24-second Direct3D startup pass; startup reaches menu installation and frame
pacing without logged errors. Binary privacy checks pass. Game data, profiles,
logs, PDBs and loose images remain excluded. Existing local saves/settings and
the stable development launcher remain in place.

The public prerelease contains exactly the Windows ZIP, optional corresponding
sources and checksum list. All three public asset SHA-256 digests and sizes
match their local files. README and packaged instructions point to Alpha 10.
This release closes the existing typed subset's address audit; full game-code
conversion, broader gameplay validation and higher-FPS animation work remain open.

## Explicit deterministic chance decisions

Entry `0x8209E230` now uses `RandomSequenceState`, editable sequence parameters,
normal/alternate thresholds and `ChanceDecision` through `native/chance_roll`.
Six translated call sites use this helper. It advances the existing shared
32-bit sequence exactly once per call, retains its modulo-100 bias and selects
an enabled alternate only when positive. Signed thresholds remain unclamped,
including guaranteed outcomes. This exposes code-level control without adding
player settings or assigning unproven gameplay roles to the callers.

The adapter maps the object/owner byte, shared seed and both 64-bit argument
homes. It rejects home/source/seed aliases and nonlinear spans before dependent
reads, retaining original write-before-read behavior for unsupported layouts.
Only the selected threshold is read. All memory bytes and GPR/FPR/VMX/control
results are compared; no scratch is normalized. The global seed stays on its
existing game owner thread and other inlined sequence users remain translated.

Both Windows configurations pass forty-two suites. New retained comparisons
cover 4,096 calls (3,072 native, 1,024 retained), 1,024 chained replay calls and
sixteen cases with the unused threshold on an inaccessible page. They include
all rounding/initial flush/exception-mask modes, host/guest control divergence,
unaligned/high object/owner/homes, offsets above 4 GiB, wrap/boundary fallback,
threshold/seed overlaps and home aliases. Portable fixtures cover 20,000
threshold combinations, edited recurrence parameters, wrap, guaranteed outcomes
and a 100,000-roll replay. A fixture initially marked an adjacent, nonoverlapping
source as an alias; correcting that expected route required no adapter change.

One broader run reported a direction-basis whole-memory mismatch at sample 198,
nearest rounding, initial flush on. That older suite passed subsequent complete
builds, 120 process replays and replays pinned to each available logical
processor. Its first differing guest byte is now reported on failure. The cause
has not been established and no direction runtime fix is claimed; retain this
as an open validation issue rather than treating the reruns as an explanation.

A fresh-profile 24-second Direct3D Release startup reaches menu installation and
frame pacing without logged errors; Windows EXE/plugin privacy scans pass.
Development has forty-six typed entries: forty-four with guest-memory fixtures
and two scalar-only operations. No additional gameplay route, speedup or
higher-FPS animation fix is established. Full game-code conversion remains open.

## Alpha 11 publication

Published `v0.1.0-alpha.11` from source commit
`49663600b8c90371a0f22f24d018a94eaf54b1a6`. The public tag resolves to that
commit. The package includes forty-six typed entries and the new deterministic
chance decision. Both current Windows configurations pass forty-two suites;
all nineteen portable component suites pass on Windows, Ubuntu and Apple Silicon
in the [matching CI run](https://github.com/WK2D/N3-Ninety-Nine-Nights-Recomp/actions/runs/39746146786).

The package's 76 allowlisted members, CRCs, fixed metadata, manifest commit and
corresponding-source hashes pass verification. Packaged binaries match the
tested Release outputs, and every embedded icon image matches the project ICO.
The extracted importer entry point and fresh-profile 24-second Direct3D startup
pass; menu installation and frame pacing are logged without errors. Binary
privacy scans pass. No game data, profiles, logs, PDBs or loose images are added.
All three public asset digests and sizes match locally: Windows ZIP, optional
corresponding sources and checksum list. Existing local saves/settings and the
stable development launcher remain in place.

Release notes preserve the unresolved intermittent direction-basis validation
issue described above. Passing reruns do not establish its cause or a runtime
fix. No new gameplay coverage, performance gain, animation fix or complete
game-code conversion is claimed.

## Typed kind flags and conditional state queries

Fourteen entries now use `native/state_queries`: eleven shared kind-bit queries,
an identity-gated flag query, a category-gated flag query and a byte-preserving
override. Explicit flag words/masks, two-word identities, category and byte
inputs can be inspected and edited without guest registers. Numeric bit meanings
remain unassigned; fourteen entry points share a small group of operations and
do not imply fourteen reconstructed subsystems.

Adapters preserve wrapped kind/row offsets, physical mapping, raw byte returns,
all integer/condition results, both identity-query argument homes and its SP `-8`
store. Source/home and later-read/scratch aliases reject before publication or
dependent traversal. Identity matches skip related/kind/table reads; category
1024 skips the kind table; byte overrides skip unused fields. They do not change
host or guest FP controls/status. Retained translations handle nonlinear ranges
and unsupported aliases.

Both Windows configurations pass forty-four suites. New differential tests cover
28,672 calls: 26,464 native and 2,208 retained, plus eighty inaccessible-unused-page
cases. All committed bytes, scalar/vector registers, condition/control state and
exact FP state match without scratch normalization. Fixtures include individually
high objects, owners, record/table cells and homes, alignments, offsets above
4 GiB, wrapped indices, high register halves, boundaries and prologue aliases.
Portable fixtures cover every bit, edited/combined/zero masks, identity/category
gates and 2,304 byte selections. Test setup was corrected where a skipped kind
read made a boundary case native-safe, and to initialize a moved category
fixture's kind field; no adapter change was needed for either fixture correction.

A fresh-profile 24-second Direct3D Release startup reaches menu installation and
frame pacing without logged errors; Windows EXE/plugin privacy scans pass.
The older intermittent direction-basis issue did not recur in this batch's
builds, and remains open without a claimed fix. Development now has sixty typed
entries: fifty-eight memory-backed and two scalar-only. No new gameplay route,
speedup or animation fix is established; full game conversion remains open.

## Alpha 12 publication

Published `v0.1.0-alpha.12` from source commit
`b6e54c379a49a3db01fbbfbb93bc64b24b09aaa7`. The public tag resolves to that
commit. The package includes sixty typed entries, fifty-eight with guest-memory
fixtures and two scalar-only operations. Both Windows configurations pass
forty-four suites; all twenty portable component suites pass on Windows, Ubuntu
and Apple Silicon in the
[matching CI run](https://github.com/WK2D/N3-Ninety-Nine-Nights-Recomp/actions/runs/39749085368).

All 76 allowlisted package members, CRCs, fixed ZIP metadata, manifest source
commit and corresponding-source hashes pass verification. Packaged runtime
binaries match the tested Release outputs, and every embedded icon image matches
the project ICO. The extracted importer and fresh-profile 24-second Direct3D
startup pass, reaching menu installation and frame pacing without logged errors.
Binary privacy checks pass; game data, profiles, logs, PDBs and loose images remain
excluded. The public prerelease has exactly the Windows ZIP, optional
corresponding sources and checksum list; all three public sizes and SHA-256
digests match local files. README and packaged instructions point to Alpha 12.

The older intermittent direction-basis validation issue remains open without a
claimed cause or fix. This release establishes no additional gameplay coverage,
performance gain, animation fix or complete game-code conversion. Entry counts
are not a reliable conversion percentage.

## Pinned ReXGlue and N3 fork review

On 2 November 2026, the exact Forza Horizon 1: ReImagined `a27387e4`,
Recompiled Halo Reach `329148bb`, pgr4-native `89705a9b`, and Donelys N3
`c408ddfe` revisions were reviewed. The installed ReXGlue nightly
`0.10.0.24-dev.gbd833a2` remains newer than upstream `main`, so the SDK pin was
retained.

The project-built Xenos plugin now applies three title-independent BSD ReIGlue
fixes before N3's live-resolution extension: texture-watch validity, the
shared-memory valid-range fast path, and independent D3D12 fence HRESULT checks.
Generated PCH/init headers are declared as codegen outputs to avoid a
stale-header Ninja race. Corresponding-source packaging includes each patch,
its source commit, and the ReIGlue notice.

N3 now has a PAL text-language setting for the five languages already present
on the supported disc. Two verified call sites return the configured Xbox
language code so the game selects its original text and matching font table.
A separate setting validates and mounts a complete alternate `SoundRes`
directory supplied from another user-owned edition. The case-insensitive file
set, XACT wave-bank structure and formats, sound-bank payloads, and preload bank
list must match before a read-only VFS overlay is installed. No voice files are
copied or bundled, and alternate executables remain unsupported. Explicit
`fullscreen=true` provenance is retained when saving profile settings. The
optional frame-pacing trace now reports effective FPS, mean, p95, p99, maximum,
and long-interval counts instead of presentation totals.

No Donelys GPL launcher/native module or all-rights-reserved branding was
copied. Its Electron launcher, F5 keyboard overlay, fullscreen/60 FPS defaults,
and duplicate graphics UI were not adopted. PGR4's title-specific native
renderer and the remaining Forza/Halo title or Vulkan patches likewise remain
reference material rather than speculative N3 changes.

Validation used the repository-pinned Clang 20.1.8, portable MSVC 14.44/Windows
SDK 10.0.26100.0, CMake 3.31.8, and Ninja. The corresponding-source bundle
completed, and `tools/prepare-gpu.py` applied all three patches plus the
live-resolution extension to the exact `bd833a2` source. A RelWithDebInfo
portable build compiled and linked successfully; all 23 CTest tests passed,
including the new voice-pack, text-language, and frame-pacing tests. An
out-of-tree pinned-SDK probe compiled and linked `text_language.cpp`,
`voice_override.cpp`, and `voice_pack.cpp`; the profile configuration regression
test also passed with real ReXGlue cvar source tracking. Modified Python and
PowerShell tooling parsed successfully, and `git diff --check` passed.

`private/game/default.xex` was not available in this checkout. Strict game
codegen, the full `tools/build.ps1` runtime/GPU build, callback-equivalence
tests that require generated code, and process startup therefore remain
unverified for this milestone. No alternate voice directory was mounted, and no
claim is made about audible Japanese voices, visual correctness, or gameplay
correctness.

## Documentation archive and offline mod staging

On 2 November 2026, the user's local MIT-licensed N3-ReGPU project at
`c03c26e7b80851a391ffb5f19bbc499c0f84fb5c` was audited for same-title
documentation, format evidence, and modding design. Its safe offline stager was
adapted to ReXGlue conventions; its generated translation, ReGPU renderer,
kernel/XAM host, and unverified runtime conclusions were not transplanted. The
original notice and reviewed revision are retained under `LICENSES/`.

Historical WK2D Alpha 1 through Alpha 12 release notes and the Alpha 12 package
guide now live in `docs/releases/upstream/`. Active docs have a separate index,
evidence labels, current package guide, and release-authoring directory.
Packaging and publishing require an explicit version and no longer consume
archived Alpha 12 files implicitly. Publishing defaults to the private fork and
its `private/main` remote; alternate repository and remote names must be
explicit.

The mod stager accepts deterministic manifests only beneath `data/`, records
providers and conflict winners, rejects executable/system overrides and unsafe
Windows paths, and builds a temporary complete tree before replacing
`out/game`. Unchanged base files are hardlinked when possible; each winning
override is unlinked and copied. `--copy-base` provides physical separation.
The launcher now accepts a validated `-GameDirectory`, allowing the staged tree
to run without changing the default `private/game` path.

Fourteen synthetic Python tests pass. They cover load order, conflict winners,
copy and hardlink behavior, repeat staging, defaults, executable rejection,
duplicate IDs, arbitrary output, source/output overlap, links/reparse points,
and report-name collisions. Modified Python files compile; the PowerShell
launcher parses; `game-build.json` parses; local Markdown links and
`git diff --check` pass.

The owned ISO hash was recomputed and the sibling Python XDVDFS reader reproduced
the checked-in partition, file-count, and extracted-byte totals plus the
documented extension inventory. Node.js was unavailable, so this repository's
JavaScript reader was not rerun. No 5.8 GB extraction or real-game mod tree was
created, no packed-resource format was decoded, and no game build, launch,
visual check, or gameplay route was exercised for this milestone. The stager
currently enables opaque whole-file replacement, not archive-member editing or
a stable runtime gameplay-mod API.

## Latest ReXGlue and build-pipeline review

On 2 November 2026, GitHub's release metadata was checked directly. The newest
published Windows SDK remains nightly `0.10.0.24-dev.gbd833a2`, full commit
`bd833a2ab69d305f99ddf57418fc38ffec8af93d`, with the same asset URL and
SHA-256 already recorded in `tools/toolchain.lock.json`. ReXGlue `main` diverges
at the older v0.10.0 release, so no SDK downgrade or speculative fork
replacement was made.

Current ReIGlue, Forza Horizon 1: ReImagined, Fable 2 Recomp,
NocturneRecomp, openNG2, and Viva Pinata Recomp revisions were reviewed for
build and porting practices. N3 independently adopted exact installed-SDK
provenance, transactional SDK replacement, commit-derived source bundle names,
strict CMake/codegen version checks, final-package SDK provenance, and offline
lock-selection tests. GPL project code and code without an established
applicable license were not copied.

The review identified a local regeneration defect: the official codegen tool
rewrote `generated/rexglue.cmake` and removed N3's generated-header output
ordering fix. A checked post-codegen transformation now restores those outputs,
rejects unexpected template drift, and routes CMake's incremental codegen
through the same SDK/XEX validation. An actual manifest-timestamp rebuild
invoked that wrapper, regenerated the file, reapplied the integration, and left
the corrected form in place.

The owned ISO was imported read only into ignored local storage for this
validation. The import produced 3,342 files / 5,770,038,003 bytes and the
expected XEX SHA-256
`0fe8973b6ff45d3f8bd03a51a8c0d8cdf278b3d43e793497777e075f4e94a804`.
The source bundler captured the SDK plus fifteen pinned dependencies; a second
run was incremental. GPU preparation refreshed from the exact SDK archive,
applied all three selected ReIGlue patches plus N3's renderer extension, and a
second run was incremental.

The pinned Clang 20.1.8 / MSVC 14.44 / Windows SDK 26100 RelWithDebInfo and
Release builds completed after strict codegen. CMake found the exact SDK and
the explicitly selected Python interpreter. All 47 CTest suites passed in each
configuration. A separate SDK-independent portable build passed all 23
component suites. Twenty-six Python lock, generated-CMake, release-scanner, and
mod-stager tests passed; modified Python, PowerShell, and JSON parsed
successfully. The release binary privacy scan also passed all four allowlisted
executables after excluding username substrings embedded inside longer API
symbols while retaining bounded narrow- and wide-string detection.
Deliberately corrupting the local SDK marker caused bootstrap to replace the
SDK from the verified archive and restore the complete marker. Simulated
interrupted-replacement recovery also passed. The online latest-release check
and dirty-package provenance rejection passed.

After commit `9b34fdb`, a nonpublished `v0.0.0-sdkreview` package admitted 76
allowlisted entries. Repeating packaging produced the same
`87506cd252270a02e0dc998ba5b3e54b0c6ff7408e09c28b57e941ee4cd715f0`
SHA-256. Every payload hash, the complete SDK identity, source commit,
corresponding-source digest, and both final checksums were independently
verified. The archive contained no PDB, XEX, ISO, game, profile, image, or log
payload.

Thirty-second RelWithDebInfo and extracted Release-package smoke runs survived
until the harness stopped them. Both reached GPU pipeline creation, native
frame-clock initialization, audio callbacks, and controller connection without
error, critical, unregistered target, exception, or floating-point-fault
entries. No visual observation, input exercise, save/load test, mission route,
performance measurement, published release, Vulkan run, or non-Windows game
build was performed. The packaged run used the command-line game-data override;
it did not exercise the first-run import UI. Process survival does not establish
correct presentation or gameplay.

Recent ReIGlue changes for loaded-only RenderDoc attachment, keyboard tap
sampling, opt-in resolve readback, and Xenon-accurate VMX floating-point
operations remain candidates. They modify runtime or generator components that
N3 does not currently rebuild from source. They require a matched SDK build,
regenerated translation comparisons, and repeated gameplay evidence before
adoption.

## Blender mod-authoring plan

**Historical:** This entry records the initial planning milestone on
2 November 2026, not the current add-on. See the
[current Blender baseline](BLENDER-MODDING.md#status-and-selected-scope).

On 2 November 2026, the loose-asset mod plan was expanded for the user's
separate Blender 5.2 add-on project. The selected first milestone is read-only
`.skin` dependency inspection and `.bm` import. Read-only `.36t` preview follows
model work, while bounded read-only `.pak` research follows the loose-asset
path. Export and package writing remain gated rather than assumed.

A read-only local scan of the verified extraction found 187 loose `.bm` and 216
loose `.skin` files, including 162 same-relative-stem pairs. Every `.skin`
contained exactly one NUL-terminated `.bm` reference and at least one `.fx`
reference; 205 contained a `.dds` reference. The median sizes were 12,510 bytes
for `.bm` and 297 bytes for `.skin`. These are observed dependency clues, not a
complete record layout or evidence of skeletal data.

The documented architecture now separates pure bounded codecs, Blender
adapters, future constrained writers, the existing offline stager, and runtime
validation. A structural version 1 `n3-blender-export.json` contract binds
future outputs to the supported XEX, producer/profile versions, source and
output hashes, claimed capabilities, unknown-data preservation, and explicit
validation results. The receipt is not yet consumed by `tools/mods.py`.

No add-on code, parser, importer, exporter, synthetic fixture, private-corpus
test suite, Blender background run, asset round trip, staged output, game
launch, visual comparison, or gameplay route was completed for this milestone.
The separate add-on project was not scaffolded or modified.

## Development launcher expansion

The Windows development launcher now exposes normal, borderless, exclusive, and
profile-configured window modes; monitor selection; frame-rate, text-language,
voice, anisotropic, display, render-resolution, and VSync overrides; named
profiles; explicit user/cache/log roots; native ISO/XEX setup and remembered-path
reset; and dry-run JSON plans. The normal default remains a 1280 x 720 window
using local ignored development paths.

Mod manifests can be listed without a build or extraction. The launcher can
stage `mods/enabled.txt` or a comma-separated ordered ID list into the fixed
disposable `out/game/` tree, optionally copy the base instead of hardlinking,
launch the stage, or stop after staging. It retains the stager's immutable-base,
path-containment, reparse-point, reserved-name, and executable-override
protections. Native setup and mod staging are deliberately mutually exclusive.

PowerShell parser checks pass for the launcher and its regression script. The
launcher suite passes 73 checks covering defaults, fullscreen mappings, every
graphics mapping, named profile paths, ordered mod plans, and rejected option
combinations. The expanded Python mod suite passes 15 synthetic tests, including
stable manifest discovery and actual fixture staging. Manual dry runs exercised
native setup, the complete graphics override set, profile resolution, and
explicit mod ordering; mod listing also completed successfully. A
launcher-driven synthetic `-StageOnly` run copied a two-file base, applied one
override, and produced the expected ordered staging report before its disposable
output was removed.

These checks establish option construction and offline staging behavior only.
No launcher-driven visual run, native picker interaction, imported-game reset,
real-mod compatibility check, gameplay route, or performance comparison was
performed for this milestone.

## Gameplay data format investigation

A read-only investigation on 2 November 2026 decoded both packed-resource
variants used by all 522 archives beneath `data/PackedResources/`. Of those,
521 wrap an aligned zlib stream and one stores the shared inner archive
directly. All 63,170 member records have valid ranges and aligned offsets.
Twenty-nine archives contain duplicate names with 76 extra records; every
duplicate payload is byte-identical, while runtime lookup precedence remains
unknown. Four representative compressed archives were reproduced exactly with
zlib level 6 plus their original padding.

The investigation also parsed all 72 loose and 238 packed SOX tables. Every
sample completed a byte-identical parse/serialize round trip, covering 310
tables and 111 unique contents. SOX is a generic tabular format. Fourteen
byte-identical global mechanics tables across the ten `res_init*.pak` variants
expose unit definitions; attack, defense, HP, critical, Orb/experience and
defense-probability curves; level matching; hero and troop progression; items;
item levels; drop probabilities; and item sets. Separate tables expose ability
unlock levels and localized move lists.

Stage archives also contain compiled unit and troop AI, attack scripts, unit
metadata, mission triggers, maps, navigation, effects, and runtime event
sequences. Their retained strings expose level branches, target selection,
counterattacks, troop commands, reinforcement and item-bearing groups, but
their binary layouts are not sufficiently decoded for writing. A dormant
two-list debug-menu layout was found without a traced activation path.

These results establish a practical route to a read-only gameplay-data
inspector and then a numeric SOX editor that emits complete replacement PAKs
through the existing mod stager. No codec or editor was added, no extracted
game data was modified, no rebuilt archive was loaded by the game, and no
gameplay or save-compatibility claim follows from structural round trips.
Duplicate-name lookup order, language-archive selection, loose authoring-file
usage, item-effect meanings, AI/mission layouts, and runtime acceptance remain
open. The format details and staged validation plan are recorded in
[modding](MODDING.md).

## Read-only gameplay data inspector

A dependency-free Python/Tkinter inspector now turns the gameplay-format
investigation into a visual application. It verifies the supported executable,
loads `res_init.pak`, compares the fourteen central mechanics tables across all
ten language-specific initialization archives, and parses every loose SOX
table. Dedicated views expose 100 units and their related level curves, hero
progression, NPC relationships and compiled AI composition, 200 items joined
with English descriptions, 257 localized per-character move rows for the
selected language, and all 103 loaded packed and loose tables. Wide and
duplicate-heading tables retain their raw fields.

The underlying bounded reader supports both observed PAK variants and all three
observed SOX field types. It rejects unsupported reserved values, invalid
alignment and ranges, zlib size/trailing-data errors, malformed descriptors,
impossible row declarations, unsupported types, nonsequential IDs, truncated
strings, and missing footers. Structural JSON export records schemas, hashes,
counts, archive comparisons, build identity, and warnings without row values
or absolute extraction paths.

Nineteen synthetic unit tests pass. A full owned-corpus run validates all 522
packed-resource archives, 63,170 members, 29 duplicate-name archives with 76
extra records and no non-identical duplicate groups, plus 238 packed and 72
loose SOX tables representing 111 unique contents. Tkinter construction,
populated-view, row-selection, joined unit/item/ability, raw-table, headless
report, and report-cleanup smoke checks pass.

These checks establish bounded read-only decoding and UI population only. No
SOX or PAK writer exists, no game data or save was modified, no rebuilt archive
was launched, and no field's runtime ownership, units, gameplay behavior, or
save compatibility was established. The user workflow and current boundary are
documented in [gameplay data inspector](GAMEPLAY-INSPECTOR.md).

## Localization data investigation

The five PAL `data/Text` folders were inventoried as 32 ordinary keyed tables
and one UTF-16BE dashboard table per language. Each slot contains the same
3,849 logical keys in the same order, including 3,747 nonempty strings. English
ordinary files contain ASCII; French, German, Italian, and Spanish use
Windows-1252; all preserve CRLF line endings. The record grammar, comments,
blank lines, whitespace, and one- or two-field layout were traced across all
19,245 localized rows without finding embedded quote syntax.

The first quoted field is translatable. Of the 3,849 rows per slot, 280 have a
second texture, voice, event, or related companion field. Several companion
values legitimately differ between PAL slots, so a rebuild must retain the
target template's companion rather than copying the source row. Filenames,
numeric key sequences, and field counts align across all five slots; comments
do not. The shipped default-table header provides symbolic context for 148
numeric IDs.

Seven briefing SOX files per PAL slot provide 1,120 string slots, with 279-286
nonempty depending on retail line wrapping. Their SOX row IDs align while
their `_TextId` values can differ, making file plus row ID the stable key.
Seven per-character ability files align across 257 rows and expose 771 string
cells, 514 nonempty, while retaining locked level values. English has an
additional unmatched 70-row generic ability table.

Each PAL `res_init<lang>.pak` contains 206 members and 23 SOX tables. Two are
localized: a 200-row item-name/description table and a seven-row character
profile table, together exposing 442 string cells and 310 nonempty values.
The standard PAL text surfaces therefore total 6,182 cells per slot, about
4,850 nonempty. Rebuilding the packed subset requires both SOX serialization
and complete PAK emission.

Thirty-two aligned `.36t` interface textures per PAL slot contain baked menu,
mission, result, map, and character-name labels. The five PAL texture
initialization archives contain byte-identical English, Euro, and special font
atlases. The observed single-byte localization uses the existing
ASCII/Windows-1252 repertoire; another script needs font, mapping, texture, and
likely runtime-decoding work.

These observations establish a practical UTF-8 sheet and template-patching
design for the loose 3,849-row surface. The existing Graphics-menu path already
generates and mounts copies of the loose Text tables without altering the game
folder. No exporter, importer, localization UI, SOX writer, PAK writer, `.36t`
writer, changed-string launch, visual PAL pass, or complete new-language test
was performed. The sheet contract, preservation rules, validation limits, and
staged implementation plan are documented in
[localization data](LOCALIZATION.md).

## Playable hero field guidance

The inspector's playable-character join was audited against `HEROTABLE.SOX`,
`CHARDATA.SOX`, character resources, and voice identifiers. The hero table's
row order does not match the English profile table's order, so the former
row-position join mislabeled Tyurru, Klarrann, Myifee, Vigk Vagk, and
Dwingvatt. The model now maps all seven supported internal unit IDs directly
and retains the raw IDs alongside their corrected names.

The hero progression grid now distinguishes nine direct progression levels
from the generic unit curves. The attack, defense, HP, critical, Orb, and
defense-probability tables expose eleven numbered slots;
`LEVELMATCHINGTABLE.SOX` alone exposes twelve. Every playable row maps slots
1-9 directly and clamps slots 10-12 to level 9, so the generic grid now labels
them curve slots rather than hero levels. The unit list also separates raw
`CHARDATA.SOX` `MaxLevel` from the nine-level playable progression.

Hover guidance covers movement scale, accessory slots, Orb decrease, guard
defense and HP, controllable troop groups, units per group, derived total
capacity, attack-range bonus, and all displayed core-curve families. It
reports the exact source fields, units or uncertainty, retail values observed
across all seven heroes, and known limits. The supported UI domains are hero
level 1-9, accessory count 1-5, and guard-group count 1-2. Other ranges are
explicitly reported as observations rather than safe edit bounds.

The owned-data smoke check loads the corrected seven names, nine progression
rows, twelve structural curve rows, dynamic guides, and derived guard totals.
Fifteen synthetic tests pass, including identity-order regression, range
aggregation, and exclusion of nonhero rows. Python compilation and Tkinter
construction/population checks also pass.

No guest-code caller, damage formula, side-branch selector, Orb-decrease
formula, guard-HP ownership, edited value, rebuilt SOX/PAK, gameplay route, or
save compatibility was validated. These tooltips improve read-only
interpretation; they do not establish writable ranges.

## NPC relationships and compiled AI guidance

The 100 `CHARDATA.SOX` definitions were split into seven playable heroes, 86
named NPCs, and seven `noname` placeholders. The retained `GameObj_ClassID`
enum identifies 49 ordinary units, 28 adjutants, five archers, and one each
for flying unit, catapult, moving tower, and the Vigk Vagk hero subclass among
the named NPC rows. The inspector now labels those exact class IDs and
provides observed-value guidance for 19 numeric or enum-like fields covering
class/troop categories, scale, physical dimensions, level tiers, sound and
crowd selectors, weight, and job linkage.

Five nonnegative `Second Job Index` values resolve as zero-based CHARDATA
positions: `C_LS_SL4_AR` to `C_LS_SL1_OH`, `C_DS_GB1_AR` to
`C_DS_GB1_OH`, `C_DS_GBC` to `C_DS_GBC_OH`, `C_DS_GB2_AR` to
`C_DS_GB2_OH`, and `C_LS_SL_EX4_AR` to `C_LS_SL_EX1_OH`. Linked rows still
carry their own class, animation, attack-script, unit-info, sound, and other
fields. The view therefore separates this explicit job-row relation from
exact shared-resource groups, five exact seven-table stat-profile groups, and
14 inferred naming families. None is labeled as generic record inheritance.

The background loader indexes 39 relevant stage archives and verifies
same-name content before collapsing repeated instances. The supported corpus
contains 664 AIB instances / 95 names, 350 AI-function instances / 19 names,
637 attack-script instances / 85 names, and 637 unit-info instances / 85
names, with no same-name payload conflicts. Seventy-eight of the 86 named NPC
rows have a direct `<UNIT>_DEFAULT.AIB` match; the eight absent programs remain
visibly absent rather than receiving an inferred fallback.

Length-prefixed retained strings expose each indexed AIB's source path,
included functions, function-call occurrences, and `iflevel` branch count.
Forty-seven of the 78 directly matched NPC programs contain level gates and
the programs collectively include 27 function names. Available standalone
`.ai_funcb` resources also expose parameter names. This supports a composition
model in which independently compiled unit programs reuse behavior modules;
it does not establish a single AI template pointer or a complete AIB binary
grammar.

Nineteen synthetic tests pass, including bounded AI-string extraction,
function/parameter recovery, identical repeated-resource collapsing,
same-name conflict rejection, explicit job-link direction, stat twins, and
separate shared-resource and naming-family evidence. Python compilation and a
real Tkinter population check pass for relationship, AI, module, and all 19
attribute rows. No AIB, AI-function, attack-script, unit-info, SOX, or PAK
writer was added; no edited resource was loaded; and no runtime AI, tier
selector, physical-unit, sound, crowd, inheritance, gameplay, or save behavior
was validated.

## AI architecture and offline navigation analysis

The mission, troop, unit, formation, and navigation layers are now documented
in [AI and navigation architecture](AI-NAVIGATION.md). Static tracing
establishes the 60-tick compiled troop evaluator, seven condition cases,
23-case command dispatcher, non-stopping `Stop` semantics, formation breadcrumb
queue, separate movement-speed scaling, capability-gated `UNIT_FLOCKABLE`
formation-recovery path, category-specific melee, ranged, flying, siege, and
special engagement slots, 252-byte runtime NAV node, guest route-list ABI, and
dynamic topology mutation behavior. Unrepresented troop-category branches,
the identities of two external-construction troop variants, and the broader
collision/local-avoidance path remain incomplete.

A dependency-free bounded analyzer now parses the 36 big-endian stage NAV
files, validates adjacency and dynamic ranges, models active topology, emulates
the original backward one-state-per-triangle search, isolates its
portal-transition indexing defect, computes an expanded portal-state Dijkstra
reference, and string-pulls corridors in X/Z. Thirteen synthetic tests cover
malformed inputs, reciprocal geometry, invalid dynamic metadata, activation and
deactivation, observed versus corrected transition selection, endpoint-aware
routing, portal orientation, funnel length, basic radius rejection,
deterministic reporting, and strict JSON output.

The owned corpus contains 26,815 triangles, 531 dynamic triangles, and 112
dynamic-range records. All adjacency is reciprocal across exact shared edges.
The 111 valid ranges cover every dynamic triangle exactly once;
`VZ_MY.NAV` also retains an invalid `(1708, 17)` record beyond its 889
triangles.

With 40 deterministic largest-static-component centroid pairs per stage and
seed `0x4E335241`, all 1,440 route requests succeeded. The original emitted
corridor was longer than endpoint-aware portal-state Dijkstra in 500 cases
(34.7%), with mean ratio 1.01314, 95th percentile 1.06975, and maximum 1.36300.
Correcting only distinct portal-pair selection reduced the mean ratio to
1.00176. Point-agent funneling had zero planar-length invariant failures,
reduced mean waypoint count from 43.29 to 8.15, and produced a mean
midpoint/funnel length ratio of 1.17529.

These are deterministic offline measurements over centroid pairs, not observed
mission traffic. Radius-aware corner clearance, formation width, derived troop
state interactions, broader local avoidance, runtime heap tie equivalence,
route-list allocation, and gameplay correctness remain unvalidated. Static
code also shows no route invalidation when dynamic NAV groups change, but a
troop stalling at a closing gate has not yet been reproduced. No runtime
AI/pathfinding behavior, generated translation, manifest entry, game asset, or
private-derived report changed in this milestone.

## Blender 0.14.0 read-only authoring baseline

The separate Blender 5.2 add-on's 0.14.0 baseline, recorded on 2 November
2026, has eight import operators: loose `.bm` models and `.skin` descriptors,
and character, static resource, terrain, level, navigation, and camera
packages. Supported `.36t` previews and package members are read in memory;
generic package extraction, an exporter, and a native writer are not
implemented. Its companion corpus report records 187 loose `.bm` files, 216
loose `.skin` files, and 1,047 mip-zero `.36t` previews.
Selected or all supported character clips can use neutral `Clip_###` Actions;
representative and no-Action modes are also available. Timing, interpolation,
signal-to-clip linkage, multi-character deformation, and attachment evidence
remain open. The roadmap's visual and isolated in-game/runtime acceptance
gates have not passed.

The add-on's synthetic `tests/test_package.py` covers package lookup,
ambiguity, and malformed input; `tests/blender_smoke.py` checks all eight
operator registrations, synthetic imports, and scene save/reopen. This
contract update did not rerun those companion tests or a private-corpus,
visual, or in-game route. The versioned receipt schema remains owned by this
repository, while `tools/mods.py` does not read or validate a receipt beside
`mod.toml`.

The new synthetic
`tools.mods_test.ModTests.test_ignores_malformed_blender_receipt_when_validating_and_staging`
places invalid JSON beside a valid manifest, verifies that validation and
staging succeed, and checks that the receipt is absent from both the staged
tree and override report while the synthetic model replacement is present.
The focused test passed, and `python -m unittest -v tools.mods_test` passed all
16 tests on Windows with temporary test data rooted in this repository. No
stager or schema behavior was changed.

### 0.14.1 foundation integration

The companion's source manifest now identifies `0.14.1` as an ungated
candidate; the `0.14.0` marker above remains a historical baseline, not a
second current version. Its version-1 aggregate snapshot
`docs\snapshots\character-animation-0.14.0.json` has SHA-256
`dfebfcd60b38d090b6cca0d36ffc8286712714d3be0ceacc308946563b28240a`.
Two `--check` scans of the owned corpus matched it with identical 103-byte
JSON (SHA-256
`3b0a36d794e247105482c80952a14a90626630af5b6d6ad23b338f1d2999c02b`).
They classify 36 character pairs, 3,121 candidates, and 67 unique animation
payloads (49 accepted, 11 trailing-data, seven inverse-bind rejections).
This is not a full release-corpus or in-game gate.

The integration check used recomp base
`62ebd5c139ff9bd169dd3b8eca7c9cd5bb5c0a16` with additional integration
changes; a clean, explicitly pinned recomp commit is still required for
release. The companion's 218 synthetic tests passed under ordinary Python
3.12 and Blender's bundled Python 3.13 without launching Blender; the recomp
mod and contract suites passed 29 tests. The configured CI checks synthetic
Python and packaging only, and archive publication was not authorized at that
foundation checkpoint. The `0.14.1` Blender 5.2.2 source/save-reopen,
Blender-built archive, and isolated-install gates were not run then. Later
synthetic source smoke, archive verification, isolated installation, and
private preview measurements are described below; clean-pinned stable release
gates remain required. No exporter, native writer, or receipt consumer was
added.

## Character animation static trace

**Observed:** the pinned generated code now has a documented path from
character-package setup and BA/AS/INFO resource loading, through copied
92-byte setup records and actor virtual `+0x8C`, to instance binding, row
selection, frame-like advancement, track evaluation, matrix output,
record-dispatch candidates, and root-derived actor displacement. Three
read-only mission fixture pairs have matching BA/AS/INFO counts; same-index
INFO type and AS-record aggregates are documented without payload values.
See `docs\NATIVE-CODE.md` for addresses, generated source anchors, evidence
labels, ABI/lifetime questions, and a bounded future probe plan.

**Observed:** `tools\animation_static_trace.py` and its synthetic in-memory
test suite make the static searches and aggregate correlations reproducible.
All 11 helper tests and all 13 recomp Blender contract tests passed; the
recomp contract consistency check and in-memory Python syntax checks passed.
No Blender, runtime instrumentation, game, or real filesystem staging was
performed for that earlier static-only study; the contract suite exercises
staging only through mocked paths and operations. Runtime-probe evidence is
reported separately below.

**Unknown:** the exact member chosen for a live actor, controller cadence
relative to the simulation clock, source animation FPS, full interpolation,
signal payload meanings, and axes/scale remain open. No animation timing fix,
native writer, or Blender receipt consumer is claimed. The next bounded
experiment must first verify member/row identity, then separately compare
controller and dispatch-window behavior at known clock rates while preserving
the original calls.

## Historical bounded animation-v2 instrumentation

**Observed, implementation:** five opt-in retained-call wrappers now cover
setup `0x82093BE8`, actor controller `0x82080158`, queue `0x82252BD8`,
evaluator `0x82298FF0`, and pose output `0x82249628` (call at `0x8229AD60`,
guest return `0x8229AD64`). Capture is disabled by default, uses bounded
arrays and serialization, validates guest mappings and object identities,
supports actor/clip filters, counts drops and invalids, preserves the original
call and guest/host state, and explicitly flushes on accepted window close.
The optional resource scope binds no actor or AS/INFO relationship. Exact ABI
assumptions, lifetime limits, source identities and commands are documented in
`docs\NATIVE-CODE.md`.

**Observed, build and synthetic tests:** the locked standard
`pwsh -NoProfile -File tools\build.ps1 -Configuration RelWithDebInfo -Jobs 4`
completed with 50/50 native tests passing; the focused trace model/hooks/
registration tests passed 3/3, and
`python -B -m unittest -q tools.animation_trace_manifest_test` passed 9/9.
The standard host SHA-256 was
`50b53466d39826a2cb39d003e55fad1b969d72e5d90f0192d3536065a827d0ae`.
The diagnostic executable and rebuilt private runtime were produced with the
locked ReXGlue `0.10.0.24-dev.gbd833a2`, LLVM 20.1.8, MSVC 14.44,
Windows SDK 10.0.26100.0, CMake 3.31.8 and Ninja.

**Observed, bounded runtime:** resource-scoped PID `15172` exited normally
after 113.475 seconds of a 120-second limit, with a responsive foreground
window and 21 posted input pairs. It selected one manager/instance/BA identity
and stored 64 queue plus 64 evaluation samples, all clip `0`; those
evaluations contain 4,800 valid pose calls. Overall it observed 2,181 queue
calls, 4,354 evaluator calls and 163,275 selected pose calls. Queue/evaluation
capacity drops were 2,117/2,113; lock drops, invalids, invalid outputs,
reentrancy, concurrent activity and calls in flight at flush were zero. There
were no setup or controller calls. The validated, path-free private v2 aggregate
is `private\traces\runtime-instrumentation\trace-resource-30-d\aggregate-v2.json`
(SHA-256 `9812d435178f029eb9179f2ff0e12314a8c20ee46a92b646e9ee95e2e5e46302`);
its paired trace and route remain in the same ignored directory.

**Candidate:** 21 matching members from 36 bounded character-archive
candidates share member SHA-256
`5013c53b8444eb666a9dd239acd00fd5e844f9d3eb6f38036d43e35277b308a5`.
The basename fingerprint does not prove which package was resolved. See the
native-code section for exact guest identities, source and return addresses,
clip counts, and other build/asset hashes.

**Observed, limitations:** the unmodified standard and DirectSound attempts
failed before gameplay because this host has no playback endpoint, with
`0xC0000005` after audio initialization and a guest read at `0x00000014`.
The successful run used a locally rebuilt SDL dummy-audio diagnostic host and
runtime, not the installed SDK DLL. Its executable and GPU-plugin imports were
checked, but the rebuilt DLL is not generally export-identical; silent audio
does not prove normal audio or timing equivalence. With instrumentation disabled
on the same final diagnostic executable, PID `42520` exited normally after
38.362 seconds, posted six foreground input pairs and wrote no trace; no
forced stop was required. An earlier actor-scoped attempt saw queue/evaluator
calls but selected no actor, and an initial resource attempt exposed and
corrected the call-site-versus-return-address guard.

```powershell
pwsh -NoProfile -File tools\animation_trace_run.ps1 -RunId baseline-final-30 -Seconds 45 -FrameRate 30 -Scope resource -Clip all -Disabled -ActivateWindow -AudioBackend dummy -Executable private\traces\runtime-instrumentation\local-sdl-dummy\game-build\n3.exe
```

**Unknown:** the selected resource's actual actor and winning package, signal
records, attachments, root motion, source FPS and interpolation remain
unproven; posted keys do not establish that the title consumed them. This is
not a 30-versus-60 FPS comparison, gameplay acceptance, animation fix, native
writer gate, or Blender run.

## Historical bounded signal/clip research

**Observed, static and private corpus:** an independent all-package inventory
found 11 strict-add-on-rejected BA trailing profiles in 57 occurrences, and
85 unique AS-101 payloads containing 4,300 groups and 18,477 retained bounded
records. The tails are characterized only by offsets, lengths and hashes.
There are also 85 INFO-100 payloads with 4,300 bounded rows. Generated code
statically connects CHARDATA to the three loaders and uses an installed actor
row to index INFO, BA and AS; this does not establish a live resolver choice.
The same numeric signal-schema kind and declared slot count match the AS
payload-word count for 18,474 records; three kind-95 records have no matching
schema kind. AniTool IDs are not the 27 runtime animation types.

**Candidate and rejected:** same-family CHARDATA names and equal counts yield
86 distinct candidate BA/AS/INFO triples, not proven runtime pairings. Their
same-index comparison has 90 of 18,618 record times at or beyond the BA frame
count, rejecting a universal in-range assumption for these candidates. Fifty
records have kinds outside the generic dispatcher's 1–37 range; actor-specific
handling and effects remain unknown. Script substring searches and table
column names are not evidence that scripts cannot encode signals.

**Observed, reproducibility:** `tools\signal_clip_research.py` produces a
deterministic, aggregate-only report and has 18 synthetic tests. The existing
bounded runtime trace remains resource-scoped, with no actor/AS/INFO binding,
no setup/controller calls and only clip-0 queue/evaluation samples. No new
capture or gameplay-semantic trigger was performed for this study. See
`docs\NATIVE-CODE.md` for the structural profile, all tail hashes, addresses,
reproduction command and evidence limitations.

**Unknown and next experiment:** correlate the actual resolver-selected
package/member hashes, actor BA/AS/INFO bindings, selected row and bounded
record dispatch with an independently observed effect for at least two
characters, without exceeding the existing route/capture limits. The present
hooks do not observe effects. Until that edge is proved, retain `Clip_###`,
unsupported tails and no notify markers; source FPS and attachment semantics
are also unproven.

### Earlier companion evidence closeout

At that closeout the companion `0.14.1` candidate shipped detailed runtime evaluator,
root-motion, and attachment evidence documents alongside its roadmap matrix.
The closeout reference for this repository was base
`74897d56dfc9ed853a752a4ffd853040d63526a4` with additional integration
changes, not clean release provenance. The earlier
`62ebd5c139ff9bd169dd3b8eca7c9cd5bb5c0a16` reference above describes the
original foundation comparison.

The closeout inspected commit `74897d5`, authored and committed by
Tzeentchnet with message `Research bounded signal and clip linkage`. Its four
changed files are the intended signal research tool and synthetic tests plus
the corresponding `NATIVE-CODE.md` and `STATUS.md` evidence. Its message has
no trailers and no Copilot co-author. At that closeout the branch was one commit ahead of
`private/main`; neither history nor unrelated working-tree changes were
rewritten.

Source-only deformation covers six 75/91/94-bone payload pairs and 71
candidate occurrences; the root inventory covers 49 accepted unique BA
payloads and 565 occurrences; 44 item rows have name-based weapon candidates.
None proves a live character, local pose, root transfer, equipped attachment,
or visual correctness. The available 30-target capture counted 163,275 pose
spans but recorded no matrices, with 2,117/2,113 queue/evaluator capacity
drops and no actor binding. The corresponding source snapshots, report
hashes, tolerances, missing gates and discriminating experiments are documented
in the companion roadmap and evidence records.

The non-Blender closeout compiled the companion and passed all 316 synthetic
tests under both system Python 3.12.10 and Blender's bundled Python 3.13.13.
It checked the three source snapshots, repeated the character, attachment and
signal reports byte-for-byte, and validated the 41-member local CI archive
contract plus standalone and cross-repository consistency. The locked recomp
build and complete native CTest suite passed 50/50, including the three trace
tests; full Python discovery passed 112 tests and the focused mod/trace/signal/
contract suites passed 67. Scoped correctness lint and the recomp contract
checker passed. That local closeout itself did not constitute a hosted CI run or Blender,
visual, staging, or runtime acceptance.

The recomp trace and route validators, candidate scan and current local
build/audio input hashes also reproduced the existing 30-target aggregate
byte-for-byte in memory (SHA-256
`9812d435178f029eb9179f2ff0e12314a8c20ee46a92b646e9ee95e2e5e46302`).
Its recorded capture base remains
`62ebd5c139ff9bd169dd3b8eca7c9cd5bb5c0a16`; rechecking it at the newer
closeout HEAD does not retroactively change that provenance or establish the
candidate package winner.

At that closeout the source was read-only with eight imports, zero exports,
no writer and no Blender receipt consumer. `Clip_###`, `source_fps_unverified`, no notify
markers, no root extraction and detached unresolved attachments remain in
force. The candidate's Blender 5.2.2, complete applicable corpus, visual,
isolated install, staging and in-game acceptance gates remain open; the CI
candidate ZIP from that historical closeout was not published. Current policy
permits only a source-matching, verified Blender-built ZIP to be published as
a GitHub prerelease while stable gates remain open.

## Current P0 integration evidence

**Observed, source/CI:** the companion `0.14.1` remains an ungated candidate,
now with nine read-only imports, zero exports, 49 explicit shipped paths and
50 archive files including the implicit manifest. The ninth is an explicitly
selected detached attachment diagnostic, not a binding. The latest local
lane passed 456 synthetic tests per Python interpreter. Hosted
[run 41683738344](https://github.com/Tzeentchnet/N3_Blender/actions/runs/41683738344)
passed 316 tests in each Ubuntu 24.04 and Windows 2022 Python 3.13 job at
add-on `fd27105854501f2edd701c71f01a9578b78a53bd`, with zero artifacts.
That run's 41-file archive check is historical and does not cover later
integration changes, Blender or the private corpus. This integration lane
began from clean base revisions add-on
`fd27105854501f2edd701c71f01a9578b78a53bd` and recomp
`bc062b2b7b148ae5f53cf14bfc69464f1ada2d37`; current changes were validated
on top and are not included in those hashes. They are not release pins.
At add-on commit `e90f41354eb40ecf941a11114ad4ba82a1ee54ae`, Blender
5.2.2 built the 50-file, 2,923,173-byte `0.14.1` ZIP with SHA-256
`0efe0f874de65018af383e132f67aee9a4dc2cfe0aa37a1720b91c57147cea8e`.
The exact archive passed source/archive verification, isolated installation,
synthetic import, nine-import/zero-export registration, and save/reopen. This
is prerelease packaging evidence, not stable, visual, runtime, or in-game
approval.
Earlier recomp integration checks reported 51/51 CTests in each
RelWithDebInfo and Release build, 25/25 portable CTests, and 132 Python
tests; these are not gameplay approval.

**Observed, source and preview:** the strict root inventory was rechecked:
36 package pairs, 685 BA occurrences, 67 unique payloads, with 49 accepted,
11 trailing and seven inverse-bind rejections; 565 accepted occurrences.
Its snapshot SHA-256 is
`9335eeecb6416167979dbfcf21bc1ed441ee466a4b696496e491ebf5822a090b`;
two 90-byte `match` comparisons have SHA-256
`cd702e8b3325f8237632b57b1daadbce9537ea2c278acbb803febc428a14409e`.
The 49 unique profiles contain 2,349 root tracks, 77,820 translation and
74,319 rotation keys; occurrence-weighted counts are 30,322, 1,007,015 and
961,252. Root consumption and wraps remain unknown.

Blender 5.2.2 synthetic source/save-reopen and detached-preview smoke passed.
A private comparison measured six hash-selected animation/model pairs, 71
candidate occurrences and 54 samples. Bone maximum and per-bone RMS preview
limits passed; aggregate max/RMS were `3.67390857647365e-6` /
`3.095875030562622e-7`. Vertex max/RMS were `4.3782152044794685e-6` /
`5.383467364220015e-7` unverified preview units; no vertex threshold was
applied. The result is `preview-regression-only`, with metre and release
approval false, not visual or runtime conformance. The companion roadmap
records every profile identity and residual.

**Observed, bounded runtime:** trace-v3 30/40/60 resource runs resolved the
same archive-content/member identity and retained 128 quaternion samples
each, but all stopped `identity_changed` with sample losses and no actor.
Original actor scope rejected 588 setups, 587 with a known getter. Historical
v3/v4 routes without provenance are accepted as unverified. Both readers
validate current v4 provenance; the recomp compares hashes while the add-on
reports recorded-only provenance without host paths. Signal/quaternion losses
and actor-generation mismatches gate correlation in both readers. Acquiring
two loss-free actor-bound profiles with validated live ABI and identity remains a
prerequisite, not completed conformance. Exact event/loss counts, hashes,
residuals and discriminating experiments are in [Native code](NATIVE-CODE.md)
and the companion runtime evidence.

**Observed/inferred, signals and attachments:** pure AS-101/INFO-100 codecs
have synthetic bounds/preservation tests, but two foreground-unowned probes
posted zero inputs and observed zero selection, dispatch and effect. The
occurrence inventory v2 retains indexed alternatives; 44 item rows remain
name-based candidates. Two attachment attempts each saw 151 reads, verified
20 and lost 131 to capacity; a third verified all 151. None observed an
actor, attachment lifecycle or synchronized transform; residuals are
unmeasured and detached preview does not authorize parenting. Detailed
capture/report hashes, scope and next controlled two-character experiments
are recorded in [Native code](NATIVE-CODE.md) and the companion evidence
documents.

**Unknown / blocked:** source FPS, interpolation, repeated-key behavior,
root transfer, signal-to-clip/effect linkage, semantic names, socket and
attachment-local transforms. Keep `Clip_###`, `source_fps_unverified`, no
notify markers, no root extraction and no attachment parenting. No native
writer or receipt consumer exists. Clean-pinned complete applicable corpus,
visual, runtime, writer, staging and in-game stable release gates remain open.
The exact verified `0.14.1` candidate ZIP may be published only as a GitHub
prerelease with those limitations disclosed.

## Historical spatial FSR1 and upstream ReXGlue review

Recorded 19 November 2026.

**Verified at that checkpoint, build and configuration:** the launcher exposed
`-Upscaler FSR1`, `Bilinear`, and `Configured`, with FSR1 selected by default.
Its regression script passed 80 command-construction checks, including the
default FSR1 override, explicit bilinear fallback, and profile-controlled
omission.

The then-pinned ReXGlue source built a matched `rexruntime.dll` and Xenos plugin
with its existing spatial EASU/RCAS path enabled. The separate temporal
FidelityFX runtime is disabled. The RelWithDebInfo source build completed and
all 51 native CTests passed. Binary inspection confirmed the FSR effect and
controls in the runtime and the FSR EASU/RCAS presentation pipelines in the
custom plugin. The established headless startup harness survived 20 seconds
until stopped by the harness.

**Observed, bounded windowed A/B:** isolated 1920 x 1080 FSR1 and bilinear runs
both reached the same graphics-pipeline and title initialization sequence, then
exited with code 3 after approximately 20 and 22 seconds respectively without a
logged renderer error. This does not indicate an FSR-specific failure, but it
also does not establish sustained windowed operation, image quality, scaling
quality, performance, or gameplay correctness. An interactive capture and
visual FSR1/bilinear comparison remain pending.

**Upstream audit at that checkpoint:** the v0.11 line was hundreds of commits
beyond the then-pinned `bd833a2` SDK and contained a broad GPU/module
reorganization, so it was not mixed into the FSR1 milestone. Five independently
applicable correctness fixes from upstream commits `0d5178cc` and `30eaa073`
were adapted to the old paths. Vulkan-only changes and optimizations coupled to
the reorganized GPU architecture were not partially imported. At that
checkpoint, `tools/check-sdk.py` reported the intentionally stale pin. The
later full v0.11 migration is recorded below.

## Stable ReXGlue 0.11.0 and bounded renderer validation

Recorded 19 November 2026.

The project is pinned to stable ReXGlue `v0.11.0`, commit
`a3e1d82678ca20d68d4837a8e9ee4652ff073745`, with official Windows SDK
archive SHA-256
`11ab67a3b8d7abaef501e77ea6c0e7dd588efe207540b46f7a302a03827a6611`.
The official SDK supplies code generation; the supported build compiles the
matched modular runtime and D3D12, Vulkan, and null Xenos drivers from the exact
stable source.

Bootstrap now prepares that source transactionally under
`.tools\rexglue-source`, initializes every stable submodule, pins
Vulkan-Headers at `9fbc2a782ee3f8a4db64e7d991e23da75e893f44` and Vulkan Memory
Allocator at `0f1a757da579831283413295cc7f3b47eb521c77`, and applies the four
original migration patches plus the tracked FSR1 restoration under
`tools\rexglue\patches`. The corresponding-source bundle contains the stable
tree, all 17 dependency trees, all five patches, build metadata, source
manifests, and the AMD FSR1 notice.

The v0.11 migration includes typed settings and lifecycle integration, modular
runtime loading, v0.11 VFS/UI/clock/PPC interfaces, the v0.11 physical-address
policy, VSCR.NJ-aware optimized VMX hooks, and host allocator linkage for every
SDK-facing test executable. The supported RelWithDebInfo source build completed
and all 51 CTests passed in 14.36 seconds; the clean Release build passed the
same 51 CTests in 13.19 seconds. Two focused ReXGlue regressions also verify
that allocating or subsequently protecting a title-facing physical alias does
not remove write access from the raw GPU view.

**D3D12 bounded hardware result:** an NVIDIA GeForce RTX 5070 initialized the
D3D12 device and reached title/menu setup. The original GPU command-thread
access violation at raw physical address `0x21FC7E03C` was traced to
guest allocation and protection state being applied to ReXGlue's precommitted
raw physical GPU view. The patch keeps only that host view read/write while its
page table and ordinary guest aliases retain title-visible protection and
write-watch behavior. Three independent standard-build runs each survived a
20-second bound without the crash or a device-loss signature and were stopped
by exact PID.

**Vulkan bounded hardware result:** the same system loaded the Khronos
validation layer, created the RTX 5070 Vulkan device and 1280 x 720 swapchain,
and sustained the standard build for a 25-second bound. Presentation semaphores
are now owned per swapchain image, and swapchain retirement waits for the
presentation queue outside the normal frame path. Neither
`VUID-vkQueueSubmit-pSignalSemaphores-00067` nor
`VUID-vkDestroySwapchainKHR-swapchain-01282` appeared in the final bounded log.
The process was stopped by exact PID.

Stable v0.11 removed the v0.10 FSR1/CAS/temporal `present_effect` surface. The
current patch set restores only the vendor-neutral spatial FSR1 EASU+RCAS path;
modern temporal upscalers remain absent. D3D12 and FSR1 are the development
launcher defaults, with Vulkan and bilinear available as explicit alternatives.

These results establish compilation, regression coverage, device/swapchain
initialization, and the absence of the two observed renderer failures during
bounded runs on one machine. They do not establish correct images, sustained
performance, other-driver compatibility, save compatibility, or gameplay
correctness. The opening route, cutscene, first mission, and save/load checks
must be repeated on the final v0.11 package.

## 30 FPS game timing, 60 Hz presentation, voice discovery, and F4 settings

Recorded 19 November 2026.

The default 1280 x 720 launch now targets 60 host presentations per second while
holding N3's guest frame clock, float simulation step, and deadline period at
the established original-speed 30 FPS policy and leaving the title presentation
interval unchanged. ReXGlue's capped present loop polls for newly completed
title frames without blocking, then presents the latest image at the selected
30/40/60 cadence. At a 30-title-frame rate, 60 Hz therefore means duplicated
host presentations, not 60 unique gameplay frames. The old setting-dependent
clock override that caused doubled gameplay speed is no longer used.

The F4 settings overlay now renders all `Allowed` settings, including numeric
display presets, as complete drop-down choices. ReXGlue validates numeric
allowed lists rather than accepting arbitrary intermediate values. Remaining
free-form numeric fields commit only on Enter. N3 also rejects unsupported
display heights before posting a window resize, so typing the first digit of a
larger number cannot request a 1 x 1 window.

The development launcher adds `-VoiceLanguage` and discovers complete
`data\Sound\<code>\SoundRes` trees below the selected extracted game. It rejects
unavailable choices and reports what it found, while `-VoiceDirectory` retains
the existing validated external-pack path. The verified supported extraction
contains only `data\Sound\ENG\SoundRes`; its French, German, Italian, and Spanish
resources are text/font data, not alternate voice banks.

At that checkpoint, the reconstructed ReXGlue tree applied the then-current
four tracked patches cleanly. The launcher regression passed 98 checks, the
SDK/package checks passed 15 tests, and the RelWithDebInfo source build passed
all 51 native CTests in 13.71 seconds.
Focused ReXGlue tests pass 13 assertions for numeric allowed-value validation
and 5 assertions for capped presenter polling. The frame-rate regression
normalizes recognized 30/40/60 clock initializers to the 30 FPS game policy and
switches the host presentation target without mutating the initialized clock.

**D3D12 bounded hardware result:** the RTX 5070 run remained alive for 25
seconds at the requested 60 Hz host target. Its title-pacing windows were
normally 29.9-30.0 frames per second, and a DPI-aware follow-up measured the
window client area at 1280 x 720. No access-violation or device-loss signature
was logged.

**Vulkan bounded hardware result:** the validation-layer run remained alive for
25 seconds, created a 1280 x 720 swapchain, measured a 1280 x 720 client area,
and logged a 30 FPS native frame-clock initialization under the 60 Hz host
target. Neither of the previously fixed presentation VUIDs, any other VUID, an
access violation, nor a device-loss signature appeared. Title production during
this debug validation run was below 30 frames per second, so this result does
not establish Vulkan performance or sustained 60 Hz presentation throughput.

These checks do not establish gameplay speed across a complete mission, visual
correctness, 60 unique game frames per second, or interactive F4 keyboard
navigation. The settings validator and editor paths are covered, but a manual
F4 interaction pass remains pending.

## Spatial FSR1 on stable ReXGlue 0.11

Recorded 19 November 2026.

Patch `0005` restores ReXGlue's vendor-neutral spatial FSR1 EASU+RCAS
presentation flow on the stable v0.11 D3D12 and Vulkan presenters. The six
generated shader headers match ReXGlue commit
`b025c4a8fdb2abb9f3779de9b340bd06c4c3c103`, the parent immediately before
upstream removed the path. Intermediate render targets, chained EASU passes,
RCAS sharpening, dithering, and the bilinear fallback are adapted to the v0.11
backend lifetimes and synchronization. The stable runtime and SDK pins did not
change.

The development launcher exposes `-Upscaler FSR1`, `Bilinear`, and
`Configured`, with FSR1 selected by default. Its command-construction regression
passes 106 checks, including the default override, explicit bilinear selection,
and configured omission. Source reconstruction and its marker check pass with
all five patches. The SDK/package suite passes 16 tests, the latest stable SDK
check still verifies v0.11.0, and the final RelWithDebInfo source build passes
all 51 native CTests in 14.46 seconds.

**D3D12 bounded A/B:** separate FSR1 and bilinear runs requested a 1920 x 1080
window with 720p internal rendering and survived their 20-second bounds on the
NVIDIA GeForce RTX 5070 until stopped by exact PID. Captures of the same
Phantagram splash frame were non-black and correctly composed. On the captured
logo region, the same simple edge-response measurement was 7.66 for FSR1 and
4.75 for bilinear, confirming that the selected paths produce the expected
distinct sharpening behavior. Neither log contained a device-removal,
access-violation, exception, or renderer-error signature.

**Vulkan bounded A/B:** separate 20-second FSR1 and bilinear runs enabled
Khronos validation, created 1920 x 1080 swapchains on the same RTX 5070, and
were stopped by exact PID. No VUID, validation error, device-loss,
access-violation, or exception signature appeared. Captures of the same splash
frame were non-black and correctly composed; the corresponding edge-response
measurement was 8.99 for FSR1 and 5.65 for bilinear.

These are bounded startup and single-frame image checks, not a broad
image-quality study. They establish that both backend pipelines initialize,
present valid images, select different filters, and survive a genuine upscale
configuration on one driver. They do not establish performance cost, artifact
behavior in motion, later-mission rendering, HDR behavior, other vendors or
drivers, sustained play, or full gameplay correctness.

FSR4, DLSS Super Resolution, and frame generation remain architectural
investigations rather than selectable features. The current presenter receives
the final guest color image but not real motion vectors, depth, projection
jitter, exposure, camera-reset metadata, camera transforms, or a HUD-less image
and UI mask. Those are required for correct temporal reconstruction and frame
generation. N3's HUD is already baked into the presented guest image. ReXGlue
[issue 526](https://github.com/rexglue/rexglue-sdk/issues/526) and the closed,
unmerged [PR 527](https://github.com/rexglue/rexglue-sdk/pull/527) explored a
Vulkan-only presentation-layer DLSS shortcut with zero motion/depth and a reset
every frame; that is not equivalent to temporal DLSS and is not included here.
No modern FidelityFX SDK, NVIDIA Streamline/NGX code, or proprietary DLSS binary
is tracked or packaged.
