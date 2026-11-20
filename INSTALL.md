# Install and set up N3 Recompiled

N3 Recompiled runs on Windows 10/11 x64. It does not include the original
**N3: Ninety-Nine Nights** executable or game assets. You must provide your own
supported USA/Europe disc image or an extraction made from that disc.

The supported executable is version `0.0.0.3` with this SHA-256:

```text
0fe8973b6ff45d3f8bd03a51a8c0d8cdf278b3d43e793497777e075f4e94a804
```

Other executable revisions and title updates are not currently supported.

## Install a release package

Use this path if a current Windows x64 ZIP is available on the
[Releases page](https://github.com/Tzeentchnet/N3-Ninety-Nine-Nights-Recomp/releases).
A packaged build does not require Git, Node.js, Python, or development tools.

1. Download the Windows x64 ZIP from the project Releases page.
2. Extract the entire ZIP to a writable folder.
3. Double-click `n3.exe`.
4. Select either:
   - an ISO made from your supported disc; or
   - `default.xex` inside an already extracted game directory.
5. If you selected an ISO, confirm the one-time import. It requires
   approximately 5.8 GB of free space and does not modify the source image.

The application remembers the validated game directory. Saves, configuration,
imported game data, caches, and logs default to:

```text
%LOCALAPPDATA%\N3Recompiled
```

To update a packaged installation, close the game and replace the application
folder with a freshly extracted release. Keep the profile directory above if
you want to retain saves and settings.

## Build and install from source

### Requirements

- Windows 10/11 x64
- Git
- [PowerShell 7](https://github.com/PowerShell/PowerShell)
- Node.js 18 or newer
- Python 3.10 or newer
- [7-Zip](https://www.7-zip.org/), normally installed at
  `C:\Program Files\7-Zip\7z.exe`
- An internet connection for the pinned toolchain downloads
- Several GB for tools and build outputs, plus approximately 5.8 GB for the
  extracted game
- A Direct3D 12-capable GPU and current driver

An Xbox-compatible controller is recommended. Vulkan is available as an
optional development backend and requires a current Vulkan-capable driver.

### 1. Clone the repository

Open PowerShell 7 and run:

```powershell
git clone https://github.com/Tzeentchnet/N3-Ninety-Nights-Recomp.git
Set-Location N3-Ninety-Nights-Recomp
```

Keep the checkout in a stable, writable location. The optional desktop
shortcut points back to this directory.

### 2. Bootstrap the pinned toolchain

The normal bootstrap downloads verified project-local copies of ReXGlue,
Clang, CMake, Ninja, and the Microsoft build tools:

```powershell
pwsh -NoProfile -File tools\bootstrap.ps1 `
  -AcceptVisualStudioLicense `
  -Python python
```

`-AcceptVisualStudioLicense` records that you accept Microsoft's
development-tool license. Downloads stay under the ignored `.tools\`
directory.

If 7-Zip is installed elsewhere, pass its executable explicitly:

```powershell
pwsh -NoProfile -File tools\bootstrap.ps1 `
  -AcceptVisualStudioLicense `
  -SevenZip 'D:\Tools\7-Zip\7z.exe' `
  -Python python
```

To use an existing Visual Studio 2022 x64 development environment instead of
the portable Microsoft tools, open its x64 developer shell and run:

```powershell
pwsh -NoProfile -File tools\bootstrap.ps1 -ToolsOnly -Python python
```

### 3. Prepare your game data

The standard development layout extracts the owned disc to `private\game`:

```powershell
node tools\disc.mjs extract `
  'D:\Games\N3.iso' `
  'private\game' `
  'private\disc-manifest.json'
```

Replace the example ISO path with your own. The destination must not already
exist. The extractor verifies the supported executable and writes a manifest
containing a SHA-256 for every extracted file.

Alternatively, skip this step and use the native ISO/XEX picker after building,
as described under [First launch](#5-first-launch).

Game data remains under ignored `private\` paths and must not be committed.

### 4. Build

Build the default `RelWithDebInfo` configuration:

```powershell
pwsh -NoProfile -File tools\build.ps1
```

The build script regenerates translated sources, compiles the native runtime,
and runs the native regression suite. The resulting executable is:

```text
out\build\win-amd64-relwithdebinfo\n3.exe
```

### 5. First launch

If you extracted the disc to `private\game`, run:

```powershell
pwsh -NoProfile -File tools\launch.ps1
```

If you skipped manual extraction, run the native setup flow:

```powershell
pwsh -NoProfile -File tools\launch.ps1 -Setup
```

Select your owned ISO or the `default.xex` from an existing extraction. ISO
import validates the game and places the extraction under the active local
profile without changing the source image.

The development launcher defaults to:

- a 1280 x 720 window;
- Direct3D 12;
- spatial FSR1 presentation;
- a 60 Hz host presentation target with the original-speed 30 FPS game clock;
- `private\user` for saves and settings;
- `private\cache` for caches; and
- `logs\runtime-windowed.log` for the runtime log.

See the [launcher guide](docs/LAUNCHER.md) for resolution, renderer, language,
profile, and mod options.

### 6. Optional desktop shortcut

After a successful build, create a desktop shortcut to the stable development
launcher:

```powershell
pwsh -NoProfile -File tools\install-shortcut.ps1
```

The shortcut uses the current checkout and its
`RelWithDebInfo` build. Re-run the command if you move the repository.

## Updating a source installation

From the repository root:

```powershell
git pull --ff-only
pwsh -NoProfile -File tools\bootstrap.ps1 `
  -AcceptVisualStudioLicense `
  -Python python
pwsh -NoProfile -File tools\build.ps1
```

Bootstrap revalidates the pinned dependencies and downloads replacements only
when needed. Keep `private\` if you want to retain extracted game data, saves,
settings, and profiles.

## Resetting game selection

To forget only the remembered game directory and reopen the native picker:

```powershell
pwsh -NoProfile -File tools\launch.ps1 -ResetGameSelection
```

This does not delete imported game data, saves, settings, logs, or caches.

## Uninstalling

For a source installation:

1. Back up anything you want to retain from `private\`, especially saves.
2. Delete the `N3 Recompiled` desktop shortcut if you created it.
3. Delete the repository directory.

For a packaged installation, delete the extracted application directory.
Remove `%LOCALAPPDATA%\N3Recompiled` separately only if you also want to delete
the remembered game import, saves, settings, caches, and logs.

## Troubleshooting and support

- If bootstrap cannot find 7-Zip, use the `-SevenZip` option shown above.
- If the build says the SDK or prepared source is missing or stale, rerun
  `tools\bootstrap.ps1`.
- If the game is rejected, confirm that it is the supported USA/Europe
  executable and has not been updated or modified.
- Review [current compatibility and validation limits](docs/STATUS.md) before
  reporting a gameplay problem.
- Report fork-specific problems through the
  [project issue tracker](https://github.com/Tzeentchnet/N3-Ninety-Nine-Nights-Recomp/issues).

When reporting a problem, include the commit or release, active profile,
renderer, reproduction steps, and relevant log text. Review logs for local
paths first, and never upload game files, disc images, or saves.
