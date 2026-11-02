N3 Recompiled - Windows x64

GET STARTED
1. Extract the entire Windows x64 ZIP to a writable folder.
2. Double-click n3.exe. It starts in a 1280 x 720 window.
3. Select an ISO made from your own supported Ninety-Nine Nights disc, or
   select default.xex in an already extracted copy with data beside it.
4. For an ISO, confirm the one-time import (about 5.8 GB of free space).
   The original ISO is unchanged. Setup remembers the local game folder.

No original executable, game assets, saves, disc image, mods, or developer logs
are provided. The program reads selected files locally; there is no upload step.
No Node.js, Python, or development tools are needed to run this package.

REQUIREMENTS
- Windows 10/11 x64 and a Direct3D 12 capable GPU/driver.
- An Xbox-compatible controller is recommended.
- Supported disc: USA/Europe, title 4D5307DB, executable version 0.0.0.3.
- default.xex SHA-256:
  0fe8973b6ff45d3f8bd03a51a8c0d8cdf278b3d43e793497777e075f4e94a804
Other executable revisions are rejected. Title updates are not validated.

LOCAL FILES
Saves, configuration, remembered game location, imported disc data, caches,
and logs default to %LOCALAPPDATA%\N3Recompiled. Keep this folder when updating.
Replace the application folder with a freshly extracted release to update.
An existing extracted game folder remains in its original location.

GRAPHICS
Select Graphics below Tutorial on the main menu. Up/down selects a row,
left/right changes its value, and B returns.
- Frame rate: 30 (default), 40, or 60 FPS.
- Anisotropic filtering: 1x, 2x, 4x, 8x, or 16x.
- Display resolution: 720p, 1080p, 1440p, or 4K.
- Render resolution: 720p (1x), 1440p (2x), or 4K (3x).
- VSync: On or Off.

Higher frame-rate modes remain experimental and animations can appear
accelerated. Display size and internal rendering are independent.

LANGUAGE AND OPTIONAL VOICES
The supported disc includes English, French, German, Italian, and Spanish text
and fonts. Add n3_text_language = "spanish" (or english, french, german,
italian) to %LOCALAPPDATA%\N3Recompiled\n3.toml, then restart.

For voices from another edition that you own, set n3_voice_directory to its
complete extracted SoundRes directory. N3 validates the complete file set,
XACT bank metadata, sound-bank payloads, and preload list before mounting it
read only. Other editions' executables are not supported. No alternate text or
voice files are included.

OPTIONAL COMMAND LINE
n3_import.exe inspect "path\to\your-disc.iso"
n3_import.exe import "path\to\your-disc.iso" "new\game-folder"
n3.exe --game_data_root "path\to\game-folder"
n3.exe --n3_text_language spanish
n3.exe --n3_voice_directory "path\to\SoundRes"

A source checkout also provides an offline loose-file mod stager. It is not
included in this runtime ZIP. A staged tree still requires the verified
default.xex and may be selected with --game_data_root.

ALPHA STATUS
The opening route, first mission, following cutscene, and save/load have been
exercised. Full-game coverage, later missions and characters, other PCs, and
mod compatibility remain unvalidated. Build and startup checks do not establish
gameplay correctness.

THIRD-PARTY SOFTWARE
ReXGlue and its dependencies are credited in THIRD_PARTY.md and licenses/.
The Xenos plugin includes the project's live-resolution extension and selected
BSD ReIGlue fixes; matching source, notices, and build scripts are supplied in
the optional corresponding-source archive. FFmpeg and libmspack include LGPL
components. Microsoft C/C++ runtime DLLs are included under Microsoft's
applicable terms.

PROJECT AND BUG REPORTS
https://github.com/Tzeentchnet/N3-Ninety-Nine-Nights-Recomp
State the release, character/mission, active mod report, and reproduction steps.
Review logs before sharing because they can contain local paths. Never upload
game files, saves, disc images, or other personal material.
