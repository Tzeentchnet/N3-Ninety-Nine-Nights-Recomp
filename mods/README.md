# N3 mods

Each mod lives in a folder whose name matches the `mod.id` in its `mod.toml`.
Place replacement files beneath `files/data/` using their original relative
paths, then add the mod ID to `enabled.txt`.

See [Modding](../docs/MODDING.md) for the manifest, staging commands, safety
rules, supported replacement boundary, and current archive-format limitations.

Package directories are ignored by Git so user-owned assets are not staged by
accident. Do not force-add original or modified game files.
