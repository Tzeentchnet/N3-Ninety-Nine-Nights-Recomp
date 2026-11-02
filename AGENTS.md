# Working on N3 Recompiled

This is the Ninety-Nine Nights native Windows recompilation project. Read
README.md and docs/STATUS.md before changing its toolchain or runtime.

- Keep original game data in private/, downloaded tools in .tools/, and translated
  game sources in generated/default/. These directories remain ignored.
- The user-owned supported USA/Europe ISO is at
  `F:\GitHub\N3\N3 - Ninety-Nine Nights (USA, Europe) (En,Fr,De,Es,It).iso`.
  Treat it as read-only, use it when disc extraction or runtime validation needs
  the supported image, and never copy it into tracked files or build artifacts.
- Put function-discovery hints in n3_manifest.toml and host/runtime fixes in src/.
  Regenerate translations instead of editing them manually.
- The launcher defaults to a 1280 x 720 window.
- The desktop shortcut points to tools/launch.ps1 and the stable RelWithDebInfo
  build path. Use tools/install-shortcut.ps1 to refresh it after a path change.
- Run checks appropriate to each change. Native runtime fixes use tools/build.ps1,
  which runs the callback FP regression test. Disc extractor changes use
  `node --test tools/disc.test.mjs`.
- Update docs/STATUS.md with observed milestones and their validation limits.
  A successful build or a surviving process does not establish gameplay correctness.
- At coherent, verified milestones, commit the intended source/documentation
  changes and push to private/main. Keep origin as the read-only upstream remote.
  Inspect staged contents before committing; do not include local game material
  or tool downloads. Do not overwrite unrelated changes or force-push history.

Private remote: https://github.com/Tzeentchnet/N3-Ninety-Nine-Nights-Recomp.git
Upstream remote: https://github.com/WK2D/N3-Ninety-Nine-Nights-Recomp.git
