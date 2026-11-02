# Documentation

These documents describe the supported USA/Europe `0.0.0.3` executable unless
a section explicitly says otherwise.

## Active documentation

| Document | Contents |
| --- | --- |
| [Development status](STATUS.md) | Observed milestones, validation evidence, unresolved issues, and explicit limits |
| [Native engine modules](NATIVE-CODE.md) | Typed C++ replacements, guest adapters, equivalence boundaries, and test coverage |
| [Game-code conversion plan](CONVERSION-PLAN.md) | Converted domains, remaining generated code, and criteria for future native modules |
| [Native code and platform roadmap](PORTING.md) | Portable components, renderer/platform work, and deeper game changes |
| [Modding](MODDING.md) | Safe loose-file staging, manifests, load order, verified asset inventory, and future mod hooks |
| [Reference projects](REFERENCES.md) | Reviewed projects, exact revisions, adopted ideas, and licensing boundaries |
| [Supported game build](game-build.json) | Disc and executable identity used by import and compatibility checks |
| [Release documentation](releases/README.md) | Current package-document contract and archived upstream release records |

## Evidence labels

Reverse-engineering and modding claims use these labels:

- **Verified**: reproduced by a checked-in tool or test against the supported
  image, executable, or synthetic fixture.
- **Observed**: directly seen in owned data or a runtime trace, but the complete
  behavior or format is not established.
- **Inferred**: supported by naming, structure, or another implementation and
  still requires an N3-specific test.
- **Planned**: a design direction, not a current compatibility promise.
- **Historical**: a record of an upstream release or past development state,
  not a statement about the current private branch.

Update the relevant document in the same change whenever code establishes or
invalidates one of these claims. Build success and process survival are not
gameplay validation.
