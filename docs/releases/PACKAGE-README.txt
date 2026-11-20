N3 Recompiled - Windows x64

GET STARTED
1. Extract the entire Windows x64 ZIP to a writable folder.
2. Double-click n3_launcher.exe, choose settings, and select Play.
3. The game starts in a 1280 x 720 window by default.
4. Select an ISO made from your own supported Ninety-Nine Nights disc, or
   select default.xex in an already extracted copy with data beside it.
5. For an ISO, confirm the one-time import (about 5.8 GB of free space).
   The original ISO is unchanged. Setup remembers the local game folder.

No original executable, game assets, saves, disc image, mods, or developer logs
are provided. The program reads selected files locally; there is no upload step.
No Node.js, Python, or development tools are needed to run this package.

REQUIREMENTS
- Windows 10/11 x64 and a Direct3D 12 capable GPU/driver.
- Vulkan is an optional command-line backend and requires a current
  Vulkan-capable GPU driver.
- An Xbox-compatible controller is recommended.
- Supported disc: USA/Europe, title 4D5307DB, executable version 0.0.0.3.
- default.xex SHA-256:
  0fe8973b6ff45d3f8bd03a51a8c0d8cdf278b3d43e793497777e075f4e94a804
Other executable revisions are rejected. Title updates are not validated.

LOCAL FILES
The launcher saves n3.toml in this writable application folder. Directly
starting n3.exe uses that same configuration. Saves, remembered game location,
imported disc data, caches, and logs default to
%LOCALAPPDATA%\N3Recompiled. Keep both n3.toml and that folder when updating.
An existing extracted game folder remains in its original location.

INSTALLED LAUNCHER
Open n3_launcher.exe for normal play. Its tabs configure:
- Play and game-data reselection.
- Graphics, display mode, renderer, presentation, filtering, and VSync.
- Text/subtitle language, spoken-audio source, volume, and mute behavior.
- Physical controller backend, deadzones, remapping, and axis inversion.
- Keyboard/mouse controller emulation and every game binding.

Reset page changes only the visible page until you choose Save or Play. Save
keeps the launcher open. Play saves first, starts n3.exe, and closes the
launcher. Change on next Play resets only the remembered game-data location;
it does not remove imported files, saves, or settings.

GRAPHICS
Use the launcher's Graphics tab before play. The in-game Graphics page below
Tutorial remains available: up/down selects a row, left/right changes its
value, and B returns.
- Presentation rate: 30, 40, or 60 Hz (60 default).
- Anisotropic filtering: 1x, 2x, 4x, 8x, or 16x.
- Display resolution: 720p, 1080p, 1440p, or 4K.
- Render resolution: 720p (1x), 1440p (2x), or 4K (3x).
- Presentation effect: spatial FSR1 or bilinear.
- VSync: On or Off.

Presentation rate does not change the established original-speed 30 FPS game
clock. The latest game frame is repeated for a 60 Hz host output target; this is
not true 60 FPS gameplay. Display size and internal rendering are independent.
Spatial FSR1 uses EASU and RCAS on the final guest image; it does not generate
frames. Bilinear presentation remains available for comparison. Temporal FSR4,
DLSS upscaling, and frame generation are not included.

LANGUAGE AND OPTIONAL VOICES
The supported disc includes English, French, German, Italian, and Spanish text
and fonts. Select the text/subtitle language in the launcher's Language & Audio
tab, then start or restart the game.

The supported USA/Europe disc contains only the English SoundRes voice tree.
The five text choices do not imply five on-disc voice banks.

For voices from another edition that you own, browse to its complete extracted
SoundRes directory in the launcher. N3 validates the complete file set, XACT
bank metadata, sound-bank payloads, and preload list before mounting it read
only. Other editions' executables are not supported. No alternate text or voice
files are included.

INPUT
The Controller tab remaps physical buttons, triggers, sticks, and axes. Each
row names the game control; the selected value names its physical source. The
Keyboard & Mouse tab maps keys and mouse movement to the same game controls.
Bindings accept comma-separated alternatives and chords such as Shift+Up.

F4 ADVANCED SETTINGS
Press F4 while the game window is focused to toggle ReXGlue's advanced settings
overlay. It provides searchable settings and a Save to config button. That
button writes the same application-folder n3.toml used by the launcher.
Allowed choices use drop-downs; free-form numeric/text values commit on Enter.
Some advanced changes require a restart. hid.keybind_* entries are
keyboard/mouse emulation; n3.controller.* entries are physical pad remapping.

OPTIONAL COMMAND LINE
n3_import.exe inspect "path\to\your-disc.iso"
n3_import.exe import "path\to\your-disc.iso" "new\game-folder"
n3.exe --title.game_root "path\to\game-folder"
n3.exe --n3.text_language spanish
n3.exe --n3.voice_directory "path\to\SoundRes"
n3.exe --gpu.driver vulkan
n3.exe --gpu.xenos.present_effect fsr1
n3.exe --gpu.xenos.present_effect bilinear

A source checkout also provides an offline loose-file mod stager. It is not
included in this runtime ZIP. A staged tree still requires the verified
default.xex and may be selected with --title.game_root.

ALPHA STATUS
The opening route, first mission, following cutscene, and save/load have been
exercised. Full-game coverage, later missions and characters, other PCs, and
mod compatibility remain unvalidated. Build and startup checks do not establish
gameplay correctness.

PROJECT LICENSE
Project-authored software and documentation are licensed under the BSD 3-Clause
License in LICENSE.txt. This grant does not cover original N3 game material,
which is not included.

THIRD-PARTY SOFTWARE
ReXGlue and its dependencies are credited in THIRD_PARTY.md and licenses/.
The source-built modular ReXGlue 0.11 runtime includes the tracked D3D12
physical-memory and Vulkan presentation corrections plus spatial AMD FSR1.
Matching source, patches, notices, and build scripts are supplied in the
optional corresponding-source archive. FFmpeg and libmspack include LGPL
components. Microsoft C/C++ runtime DLLs are included under Microsoft's
applicable terms.

PROJECT AND BUG REPORTS
https://github.com/Tzeentchnet/N3-Ninety-Nine-Nights-Recomp
State the release, character/mission, active mod report, and reproduction steps.
Review logs before sharing because they can contain local paths. Never upload
game files, saves, disc images, or other personal material.
