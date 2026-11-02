# Development launcher

`tools/launch.ps1` is the supported entry point for local Windows development
builds. It selects the build, applies one-launch graphics overrides, isolates
profiles, delegates first-run setup to the native application, and can stage
loose-file mods before starting the game.

The launcher is not included in release packages. Running a packaged `n3.exe`
directly uses the application's normal `%LOCALAPPDATA%\N3Recompiled` profile and
native first-run setup instead.

## Defaults

```powershell
pwsh -NoProfile -File tools\launch.ps1
```

The default development launch:

- starts the `RelWithDebInfo` build;
- forces a normal window, whose runtime default is 1280 x 720;
- uses `private\game` as the owned extracted game tree;
- stores saves, settings, remembered game paths, and diagnostics in
  `private\user`;
- stores caches in `private\cache`; and
- writes the runtime log to `logs\runtime-windowed.log`.

Original game data remains local and ignored by Git. The launcher rejects
reparse points in game, mod, profile, cache, and log paths.

## Options

| Option | Values / default | Behavior |
| --- | --- | --- |
| `-Configuration` | `RelWithDebInfo` (default), `Release`, `Debug` | Selects `out\build\win-amd64-<configuration>\n3.exe`. |
| `-WindowMode` | `Windowed` (default), `Borderless`, `Exclusive`, `Configured` | Forces a normal window, borderless fullscreen, exclusive fullscreen, or leaves the saved ReXGlue fullscreen settings untouched. |
| `-Width`, `-Height` | Positive pixels | Override one or both window dimensions for this launch. |
| `-Monitor` | `0` through `16` | Selects the ReXGlue monitor index. |
| `-FrameRate` | `Original`, `30`, `40`, `60` | Overrides `n3_frame_rate`; `Original` uses the original game timing value `0`. |
| `-TextLanguage` | `English`, `French`, `German`, `Italian`, `Spanish` | Selects the matching original PAL text resources. |
| `-VoiceDirectory` | Existing directory | Mounts a validated alternate `SoundRes` directory read only. |
| `-Anisotropic` | `1`, `2`, `4`, `8`, `16` | Selects the numeric anisotropic-filtering override. |
| `-DisplayResolution` | `720`, `1080`, `1440`, `2160` | Selects the display/output preset. It cannot be combined with `-Width` or `-Height`. |
| `-RenderResolution` | `720`, `1440`, `2160` | Selects internal 1x, 2x, or 3x rendering. |
| `-VSync` | `Configured`, `On`, `Off` | Leaves the profile value untouched or forces host presentation VSync for this launch. |
| `-GameDirectory` | Existing directory | Uses an explicit extracted game tree and bypasses remembered-path/native picker behavior. The normal default is `private\game`. |
| `-Setup` | Switch | Omits the game-root override so the native application can use its remembered path or open its ISO/XEX picker. |
| `-ResetGameSelection` | Switch | Deletes only the active profile's `game-path.txt` and implies `-Setup`, forcing native selection on the next real launch. |
| `-Profile` | Letters, digits, `.`, `_`, `-` | Uses isolated defaults below `private\profiles\<name>`. |
| `-UserDirectory` | Directory path | Overrides the user/profile root. |
| `-CacheDirectory` | Directory path | Overrides the cache root. |
| `-LogFile` | File path | Overrides the runtime log path. |
| `-ListMods` | Switch | Lists discovered manifests and exits without requiring a build or game extraction. |
| `-UseEnabledMods` | Switch | Stages IDs from `mods\enabled.txt`, lowest to highest priority. |
| `-Mod` | Comma-separated IDs | Stages exactly these IDs in the supplied low-to-high priority order. |
| `-ModsDirectory` | Existing directory | Selects the mod-manifest root; the default is `mods`. |
| `-ModOrder` | Existing file | Replaces `enabled.txt` when used with `-UseEnabledMods`. |
| `-CopyModBase` | Switch | Copies all unchanged base files instead of using hardlinks. |
| `-StageOnly` | Switch | Builds `out\game` and exits without requiring or starting `n3.exe`. |
| `-Python` | Command or executable path | Selects the Python interpreter used for `tools\mods.py`. |
| `-DryRun` | Switch | Prints the resolved launch plan as JSON without creating paths, resetting setup, staging mods, checking the executable, or starting the game. |

Options omitted from the command line remain available to the active profile's
`n3.toml`. Explicit launcher values override saved values for that process.

## Window and graphics examples

```powershell
# Borderless fullscreen on monitor 1, with the saved graphics values.
pwsh -NoProfile -File tools\launch.ps1 `
  -WindowMode Borderless -Monitor 1

# An explicit 1080p window with 1440p internal rendering.
pwsh -NoProfile -File tools\launch.ps1 `
  -Width 1920 -Height 1080 -RenderResolution 1440

# Exclusive fullscreen, 4K output/rendering, 16x filtering, and VSync.
pwsh -NoProfile -File tools\launch.ps1 `
  -WindowMode Exclusive `
  -DisplayResolution 2160 `
  -RenderResolution 2160 `
  -Anisotropic 16 `
  -VSync On

# Inspect the exact arguments without launching.
pwsh -NoProfile -File tools\launch.ps1 `
  -DryRun -Setup -WindowMode Configured -FrameRate Original
```

Higher frame-rate modes remain experimental. A requested limit does not fix the
known accelerated-animation behavior or establish pacing across the game.

## Profiles and paths

A named profile keeps independent saves, settings, remembered game selection,
menu cache, shader cache, diagnostics, and runtime log:

```powershell
pwsh -NoProfile -File tools\launch.ps1 -Profile vanilla
pwsh -NoProfile -File tools\launch.ps1 -Profile mod-testing -UseEnabledMods
```

The generated defaults are:

```text
private\profiles\<name>\
  n3.toml
  game-path.txt
  cache\
  logs\
    runtime.log
```

Explicit path options override their corresponding named-profile defaults:

```powershell
pwsh -NoProfile -File tools\launch.ps1 `
  -Profile test `
  -UserDirectory 'D:\N3-Profiles\Test' `
  -CacheDirectory 'E:\N3-Cache\Test' `
  -LogFile 'D:\N3-Logs\test.log'
```

The launcher creates writable user, cache, and log parent directories for a
real launch. `-DryRun` resolves them without creating them.

## Native setup and reset

Use the application's native setup flow instead of the default
`private\game` extraction:

```powershell
pwsh -NoProfile -File tools\launch.ps1 -Setup
```

If the active profile has a valid remembered game folder, the application uses
it. Otherwise, the native picker accepts either an owned ISO or `default.xex`
inside an extracted game tree. ISO import verifies the supported executable and
places the extraction under the active profile. The source image is unchanged.

To discard only the remembered selection and force the picker:

```powershell
pwsh -NoProfile -File tools\launch.ps1 `
  -Profile import-test -ResetGameSelection
```

`-ResetGameSelection` never removes imported game data, saves, configuration,
logs, or caches. Under `-DryRun`, it reports the planned reset without deleting
anything.

## Mod discovery and staging

List every valid manifest beneath `mods`:

```powershell
pwsh -NoProfile -File tools\launch.ps1 -ListMods
```

Stage `mods\enabled.txt` into the fixed disposable `out\game` tree and launch:

```powershell
pwsh -NoProfile -File tools\launch.ps1 -UseEnabledMods
```

Select an ordered set without editing `enabled.txt`:

```powershell
pwsh -NoProfile -File tools\launch.ps1 `
  -Mod author.base,author.compatibility,author.personal
```

IDs are ordered from lowest to highest priority; later providers win a conflict.
The launcher writes an ephemeral order file, invokes the same validated offline
stager documented in [Modding](MODDING.md), removes that order file, and launches
with `out\game`. The owned source extraction is never modified.

For staging without a game launch:

```powershell
pwsh -NoProfile -File tools\launch.ps1 -UseEnabledMods -StageOnly
```

Use `-CopyModBase` when physical separation is more important than disk usage.
Otherwise, unchanged files may be hardlinked; treat `out\game` as read only and
restage it after changing mod sources.

## Precedence and rejected combinations

- `-Setup` and `-GameDirectory` are mutually exclusive.
- `-ResetGameSelection` implies `-Setup` and cannot accompany
  `-GameDirectory`.
- Setup/reset cannot accompany mod staging because staging needs an existing
  extracted source tree.
- `-DisplayResolution` cannot accompany `-Width` or `-Height`.
- `-UseEnabledMods` and `-Mod` are mutually exclusive.
- `-ModOrder` requires `-UseEnabledMods`.
- `-CopyModBase` and `-StageOnly` require a mod-selection mode.
- Mod staging treats `-GameDirectory` as its immutable source, but always
  launches the completed `out\game` tree.
- An explicit `-UserDirectory`, `-CacheDirectory`, or `-LogFile` takes
  precedence over the corresponding named-profile default.
- `-WindowMode Configured` and `-VSync Configured` omit command-line overrides,
  allowing `n3.toml` to decide.

The launcher reports invalid combinations before creating directories or
starting external tools.

## Validation limits

The launcher's regression script checks option mappings, named paths, ordered
mod plans, and conflict rejection:

```powershell
pwsh -NoProfile -File tools\launch_test.ps1
```

These tests validate command construction and staging orchestration. They do
not establish visual correctness, controller behavior, mod compatibility, or
gameplay coverage.
