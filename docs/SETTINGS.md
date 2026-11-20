# Installed launcher and in-game settings

Release packages include `n3_launcher.exe`, the default entry point for normal
play. It is a native Windows application and does not require PowerShell,
Python, Node.js, or .NET. Extract the whole package to a writable folder, open
the launcher, choose settings, then select **Play**.

The launcher writes `n3.toml` beside `n3_launcher.exe` and `n3.exe`. Starting
`n3.exe` directly reads that same file, so command-line or shortcut launches do
not use a separate graphics or input profile. Saves, remembered game-data
location, imported ISO contents, caches, and logs remain under
`%LOCALAPPDATA%\N3Recompiled`.

The launcher preserves settings it does not manage when it updates `n3.toml`.
It reports malformed configuration, invalid curated values, an unavailable
voice directory, an unwritable installation, a missing `n3.exe`, and process
launch failures instead of silently continuing.

## Launcher pages

- **Play** shows the shared configuration file and remembered game-data
  location. **Change on next Play** removes only the remembered location when
  Play is selected; the native game-data prompt then accepts a supported ISO or
  an extracted `default.xex`. It does not delete an imported game, saves, or
  settings.
- **Graphics** selects window mode and size, monitor, output resolution,
  presentation rate, D3D12 or Vulkan, FSR1 or bilinear presentation, internal
  render scale, anisotropic filtering, and VSync.
- **Language & Audio** selects the original text/subtitle language, spoken-audio
  source, volume, and mute behavior. The supported USA/Europe disc contains all
  five text languages but only English spoken audio. Compatible discovered or
  user-selected `SoundRes` folders appear as additional spoken-audio choices.
- **Controller** selects the input backend, vibration, Guide-button forwarding,
  stick deadzones, physical button/trigger/stick mappings, and axis inversion.
  Each row names the control the game receives; its drop-down names the
  physical source. A source may feed more than one game control, and
  **Disabled** leaves that game control unbound.
- **Keyboard & Mouse** enables controller emulation, optional mouse-to-right-
  stick input, sensitivity, passthrough, and every Xbox-style game binding.
  Bindings accept comma-separated alternatives and modifier chords such as
  `Shift+Up`. An empty field is unbound.

**Reset page** restores only the visible page in the form. Choose **Save** or
**Play** to write the reset values. **Save** leaves the launcher open; **Play**
saves first, starts the sibling `n3.exe`, then closes the launcher.

Presentation rate controls host output cadence while N3 retains the established
original-speed 30 FPS game clock. A 60 Hz selection repeats the latest title
frame when necessary; it is not true 60 FPS simulation or animation.

## F4 advanced settings overlay

Press **F4** while the game window is focused to toggle ReXGlue's advanced
settings overlay. The binding is `ui.bind.settings` and can itself be changed.
The overlay is useful for inspecting settings or making a temporary live
change, but the installed launcher is the supported curated interface.

The overlay contains:

- a search field and categories based on setting scopes;
- check boxes, drop-downs, numeric fields, paths, and key-chord controls;
- help text when a setting is hovered; and
- **Save to config**, which writes the same installation-folder `n3.toml` used
  by the launcher and direct `n3.exe` startup.

Allowed-value settings use drop-downs. Free-form numeric and text fields commit
on Enter. Settings marked for restart take effect on the next game start;
launcher changes naturally take effect when Play starts a new process. Close
the overlay with F4 again.

Input names in the overlay have two distinct purposes:

- `hid.keybind_*` maps keyboard and mouse inputs to an emulated Xbox controller.
- `n3.controller.*` remaps physical controller state before N3 reads it.

The F4 overlay does not select or import game data. Use the launcher's Play page
or the native game-data prompt for that operation.

## Development launcher

Source checkouts also have `tools\launch.ps1` for isolated development profiles,
mod staging, and one-process command-line overrides. It explicitly places its
configuration under `private\user` or `private\profiles\<name>` and does not
overwrite the installation-folder `n3.toml`. See the
[development launcher guide](LAUNCHER.md).

`tools\launch.ps1 -Settings` opens this same native settings interface while
forwarding the selected source-checkout game, user, cache, log, and
configuration paths. The one-click source setup wizard and installed desktop
shortcut use that mode, so Save and Play remain on the private development
profile instead of `%LOCALAPPDATA%`.
