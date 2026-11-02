# Release documentation

Release material is separated into current authoring files and immutable
upstream history.

## Current private project

- `PACKAGE-README.txt` is the user guide embedded as `README.txt` in a future
  Windows package.
- Create release notes as `<tag>.md` in this directory, for example
  `v0.2.0-alpha.1.md`.
- `tools/package-release.py --version <tag>` builds the allowlisted package.
- `tools/publish-release.py --version <tag>` reads the matching notes only after
  the exact committed package has been pushed to `private/main`.

Both release tools require an explicit version, and packaging refuses an
uncommitted source tree before recording its commit and exact SDK provenance.
Historical WK2D notes are never used implicitly for a new package.

## Upstream archive

[`upstream/`](upstream/README.md) preserves the WK2D Alpha 1 through Alpha 12
release notes and the package guide shipped with Alpha 12. They document the
public upstream tags and validation available at those points. They are
**historical**, not a capability statement for the current private branch.
