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
3. Double-click `n3_launcher.exe`, choose settings, and select **Play**.
4. In the native game-data prompt, select either:
   - an ISO made from your supported disc; or
   - `default.xex` inside an already extracted game directory.
5. If you selected an ISO, confirm the one-time import. It requires
   approximately 5.8 GB of free space and does not modify the source image.

The launcher stores the shared `n3.toml` beside `n3_launcher.exe`; directly
starting `n3.exe` uses the same settings. The application remembers the
validated game directory. Saves, imported game data, caches, and logs default
to:

```text
%LOCALAPPDATA%\N3Recompiled
```

To update a packaged installation, close the game and replace the application
folder with a freshly extracted release. Retain the installation's `n3.toml`
and the profile directory above if you want to keep settings and saves. See
[Installed launcher and in-game settings](docs/SETTINGS.md) for every launcher
page and the F4 advanced overlay.

## Build and install from source

Use the release package above if you only want to play. A source installation
downloads the compiler stack, translates the owned executable, compiles the
runtime, and runs its regression tests.

The one-click source setup requires:

- Windows 10/11 x64;
- an existing clone or downloaded source checkout in a stable writable folder;
- your supported USA/Europe ISO;
- an internet connection;
- several GB for portable tools and build outputs, plus approximately 5.8 GB
  for the extracted game; and
- a Direct3D 12-capable GPU with a current driver.

Git, PowerShell 7, Python, Node.js, 7-Zip, Visual Studio, CMake, Ninja, and
Clang do not need to be installed globally. Setup downloads checksum-pinned
portable copies under the ignored `.tools\` directory and does not require
administrator access. You must explicitly accept Microsoft's Visual Studio 2022
development-tool license before its portable headers and libraries are
downloaded.

### 1. Obtain the source

Clone with Git if it is already installed:

```powershell
git clone https://github.com/Tzeentchnet/N3-Ninety-Nights-Recomp.git
Set-Location N3-Ninety-Nights-Recomp
```

You can instead download GitHub's source archive and extract it. Keep the
checkout in a stable location because the optional desktop shortcut points
back to it.

### 2. Run the setup wizard

Double-click:

```text
setup.cmd
```

Then:

1. Select the supported ISO unless a verified `private\game` is already
   present.
2. Choose the build type and parallel-job count.
3. Review and accept the Microsoft development-tool license.
4. Leave desktop-shortcut creation enabled if desired.
5. Select **Install and build**.

The wizard:

1. downloads and verifies portable PowerShell, Python, Node.js, 7-Zip, and
   MinGit;
2. verifies `default.xex` in the ISO before the large import;
3. imports and hashes the disc into ignored `private\game`;
4. downloads and verifies ReXGlue, Clang, CMake, Ninja, and the portable
   Microsoft build tools;
5. generates translated sources, compiles the runtime, and runs all native
   tests; and
6. opens the native settings launcher.

Progress and command output remain visible throughout. Downloads and valid
completed stages are reused on retry. A failed new game import removes only
the setup-owned staging directory; existing `private\game` data is never
overwritten. The last structured setup log is:

```text
.tools\setup-state\last-setup.jsonl
```

The resulting executables are under
`out\build\win-amd64-relwithdebinfo\`. The desktop shortcut opens the native
settings launcher while retaining `private\game`, `private\user`,
`private\cache`, and profile-local logs.

### Manual source workflow

Developers can still run the individual stages. Install PowerShell 7,
Python 3.10 or newer, Node.js 18 or newer, and 7-Zip, then run:

```powershell
pwsh -NoProfile -File tools\bootstrap.ps1 `
  -AcceptVisualStudioLicense `
  -Python python

node tools\disc.mjs verify `
  'D:\Games\N3.iso' `
  default.xex `
  0fe8973b6ff45d3f8bd03a51a8c0d8cdf278b3d43e793497777e075f4e94a804

node tools\disc.mjs extract `
  'D:\Games\N3.iso' `
  'private\game' `
  'private\disc-manifest.json'

pwsh -NoProfile -File tools\build.ps1
pwsh -NoProfile -File tools\launch.ps1 -Settings
```

Source translation requires the supported `private\game\default.xex`, so disc
verification and extraction must finish before the build. Original game data
remains ignored and must never be committed.

To use an existing Visual Studio 2022 x64 development environment instead of
the portable Microsoft tools, open its x64 developer shell and run
`tools\bootstrap.ps1 -ToolsOnly`.

## Updating a source installation

From the repository root:

```powershell
git pull --ff-only
.\setup.cmd
```

Setup revalidates pinned dependencies and downloads replacements only when
needed. Keep `private\` to retain extracted game data, saves, settings, and
profiles. Advanced users may continue to run `tools\bootstrap.ps1` and
`tools\build.ps1` separately.

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

For a packaged installation, delete the extracted application directory,
including its `n3.toml`.
Remove `%LOCALAPPDATA%\N3Recompiled` separately only if you also want to delete
the remembered game import, saves, caches, and logs.

## Troubleshooting and support

- Review `.tools\setup-state\last-setup.jsonl` if the setup wizard fails.
- The setup wizard requires the built-in Windows `tar.exe`; supported Windows
  10/11 installations include it.
- Manual bootstrap can use `-SevenZip` to select a nonstandard 7-Zip path.
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
