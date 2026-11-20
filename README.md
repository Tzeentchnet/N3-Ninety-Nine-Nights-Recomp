# N3 Recompiled

> [!TIP]
> **Blender importer:** [N3 Blender](https://github.com/Tzeentchnet/N3_Blender)
> provides Blender 5.2 tools for researching and importing
> **N3: Ninety-Nine Nights** assets.

<img src="resources/n3-icon.png" width="128" height="128" alt="N3 Recompiled icon">

A native Windows recompilation of **N3: Ninety-Nine Nights** using
[ReXGlue](https://github.com/rexglue/rexglue-sdk). PowerPC game code is
translated ahead of time and runs through a native Windows host with a
Direct3D 12 Xenos renderer by default, with Vulkan available as an opt-in
development backend.

No game assets, executable, generated game translations, or downloaded
toolchains are included. You must supply your own supported game data.

For a source checkout on Windows 10/11, double-click `setup.cmd` for the
project-local toolchain, verified ISO import, compile/test, shortcut, and
settings-launcher flow. A release ZIP remains the simpler compiler-free option.

## Project information

- [Installation and first-run setup](INSTALL.md)
- [Fork relationship and differences](docs/FORK.md)
- [Current development status](docs/STATUS.md)
- [Installed launcher and in-game settings](docs/SETTINGS.md)
- [Development and build guide](docs/DEVELOPMENT.md)
- [Documentation index](docs/README.md)

## License

Project-authored source and documentation are available under the
[BSD 3-Clause License](LICENSE). Third-party and adapted work retain their own
terms; see [third-party notices](THIRD_PARTY.md) and [`LICENSES/`](LICENSES/).

The license does not grant rights to **N3: Ninety-Nine Nights**, its executable,
game data, artwork, audio, trademarks, or other proprietary material.
