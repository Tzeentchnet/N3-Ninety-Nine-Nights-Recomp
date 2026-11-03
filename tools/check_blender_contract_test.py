from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import copy
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import unittest
from unittest import mock

from tools import check_blender_contract as checks
from tools import mods


ROOT = Path(__file__).resolve().parent.parent


class MemoryTree(checks.FileTree):
    """Keep every test fixture in memory rather than creating a checkout."""

    def __init__(self, files: dict[str, str]):
        self.root = (ROOT / "tools" / "_virtual_blender_contract").resolve()
        self.files = {self.path(name): value for name, value in files.items()}

    def path(self, name: str) -> Path:
        return (self.root / name).resolve()

    def read(self, path: Path) -> str:
        try:
            return self.files[path.resolve()]
        except KeyError as error:
            raise checks.ConsistencyError(f"cannot read {path}") from error

    def is_file(self, path: Path) -> bool:
        return path.resolve() in self.files

    def is_dir(self, path: Path) -> bool:
        return any(path.resolve() in item.parents for item in self.files)

    def resolve(self, path: Path) -> Path:
        path = path.resolve()
        return next((item for item in self.files if str(item).casefold() == str(path).casefold()), path)

    def put(self, name: str, value: str) -> None:
        self.files[self.path(name)] = value


def fixture_schema() -> dict:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Synthetic café",
        "type": "object",
        "additionalProperties": False,
        "required": ["schemaVersion", "modId", "target", "producer", "exports"],
        "properties": {
            "schemaVersion": {"const": 1},
            "modId": {"type": "string"},
            "target": {"type": "object"},
            "producer": {"type": "object"},
            "exports": {"type": "array"},
        },
    }


def digest(schema: dict) -> str:
    canonical = json.dumps(schema, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def fixture_marker(schema: dict) -> dict:
    return {
        "marker_version": 1,
        "addon_version": "1.2.3",
        "blender_minimum": "5.2.0",
        "read_only": True,
        "import_operator_count": 8,
        "import_operators": list(checks.IMPORT_OPERATORS),
        "package_members": "in-memory",
        "redistributable_fixtures": "synthetic",
        "exporter": False,
        "native_writer": False,
        "recomp_receipt_consumer": False,
        "receipt_schema_version": 1,
        "receipt_schema_sha256": digest(schema),
        "visual_gates_passed": False,
        "runtime_gates_passed": False,
    }


def marker_comment(marker: dict) -> str:
    return f"<!-- n3-blender-baseline\n{json.dumps(marker, indent=2)}\n-->\n"


def table() -> str:
    rows = ["| Read-only import | Operator |", "| --- | --- |"]
    rows.extend(f"| Synthetic {index} | `{operator}` |" for index, operator in enumerate(checks.IMPORT_OPERATORS))
    return "\n".join(rows) + "\n"


def synthetic_tree() -> tuple[MemoryTree, dict]:
    schema = fixture_schema()
    authoring = (
        "# Blender contract\n\n## Status and selected scope\n\n"
        "The **1.2.3 read-only baseline** has eight import operators. "
        "There is no exporter or native N3 writer, and the recomp stager "
        "does not consume the optional Blender receipt.\n\n"
        + marker_comment(fixture_marker(schema))
        + "\n"
        + table()
        + "\n[Modding](MODDING.md#blender-authoring-track)\n"
        + "[Schema](schemas/n3-blender-export-v1.schema.json)\n"
    )
    modding = (
        "# Modding\n\n## Current boundary\n\n"
        "| Import | 1.2.3 baseline: eight read-only operators |\n"
        "| Receipt | no exporter or receipt consumer |\n\n"
        "## Blender authoring track\n\n"
        "The 1.2.3 baseline has eight read-only operators. "
        "No exporter or native writer exists. The current stager neither reads "
        "nor validates a `n3-blender-export.json` beside `mod.toml`.\n"
    )
    porting = (
        "# Porting\n\n## Deeper game changes\n\n"
        "The 1.2.3 baseline has eight read-only import operators and has no "
        "exporter or native writer. The current stager does not consume, "
        "validate, or stage a receipt.\n"
    )
    status = (
        "# Status\n\n## Blender 1.2.3 read-only authoring baseline\n\n"
        "The 1.2.3 baseline has eight import operators. An exporter, and a "
        "native writer are not implemented. The stager does not read or "
        "validate a receipt.\n"
    )
    return MemoryTree(
        {
            "docs/BLENDER-MODDING.md": authoring,
            "docs/MODDING.md": modding,
            "docs/PORTING.md": porting,
            "docs/STATUS.md": status,
            checks.SCHEMA_PATH: json.dumps(schema),
            "tools/mods.py": (
                "def _scan_mod_files(path):\n    return ()\n\n"
                "def load_mod(root):\n"
                "    manifest_path = root / 'mod.toml'\n"
                "    files = _scan_mod_files(root / 'files')\n"
                "    return manifest_path.read_text()\n"
            ),
        }
    ), schema


class ContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tree, self.schema = synthetic_tree()

    def test_synthetic_contract_and_cli_pass(self) -> None:
        checks.check_contract(self.tree)
        stdout = io.StringIO()
        with mock.patch.object(checks, "FileTree", return_value=self.tree), redirect_stdout(stdout):
            self.assertEqual(checks.main(["--root", str(self.tree.root)]), 0)
        self.assertIn("receipt schema", stdout.getvalue())

    def test_scoped_documents_have_checked_local_links_and_fragments(self) -> None:
        for doc in checks.SCOPED_DOCS:
            original = self.tree.read(self.tree.path(doc))
            for suffix, message in (
                ("\n[bad](missing.md)\n", "missing local link target"),
                ("\n[bad](MODDING.md#missing-section)\n", "missing fragment"),
                ("\n[bad](modding.md)\n", "incorrect case"),
                ("\n![image][missing-ref]\n", "undefined reference"),
                ("\n![image][picture]\n[picture]: missing.png\n", "missing local link target"),
            ):
                with self.subTest(doc=doc, suffix=suffix):
                    self.tree.put(doc, original + suffix)
                    with self.assertRaisesRegex(checks.ConsistencyError, message):
                        checks.check_contract(self.tree)
            self.tree.put(doc, original)

    def test_code_external_links_images_and_reference_links(self) -> None:
        doc = checks.SCOPED_DOCS[0]
        original = self.tree.read(self.tree.path(doc))
        self.tree.put(
            doc,
            original
            + "\n[ref][guide] ![logo][image]\n"
            + "[guide]: MODDING.md#blender-authoring-track\n"
            + "[image]: <images/synthetic(1).png>\n"
            + "[remote](https://example.invalid/missing.md)\n"
            + "`[inline](missing-inline.md)`\n"
            + "```md\n[code](missing-fenced.md)\n```\n"
            + "<pre>[html code](missing-html.md)</pre>\n"
            + "    [indented](missing-indented.md)\n",
        )
        self.tree.put("docs/images/synthetic(1).png", "synthetic")
        checks.check_contract(self.tree)

    def test_hidden_inline_comment_opener_cannot_mask_broken_link(self) -> None:
        doc = checks.SCOPED_DOCS[1]
        self.tree.put(doc, self.tree.read(self.tree.path(doc)) + "\n`<!--` [bad](missing.md)\n")
        with self.assertRaisesRegex(checks.ConsistencyError, "missing local link target"):
            checks.check_contract(self.tree)

    def test_baseline_marker_malformed_duplicate_and_false_claims(self) -> None:
        name = checks.SCOPED_DOCS[0]
        original = self.tree.read(self.tree.path(name))
        marker = marker_comment(fixture_marker(self.schema))
        changes = (
            original.replace(marker, ""),
            original + marker,
            original.replace(marker, "<!-- n3-blender-baseline\n{broken}\n-->"),
            original.replace('"marker_version": 1,', '"marker_version": 1, "marker_version": 1,'),
            original.replace('"recomp_receipt_consumer": false', '"recomp_receipt_consumer": true'),
            original.replace('"exporter": false', '"exporter": 0'),
            original.replace('"receipt_schema_version": 1', '"receipt_schema_version": 2'),
        )
        for changed in changes:
            with self.subTest(changed=changed[:100]):
                self.tree.put(name, changed)
                with self.assertRaises(checks.ConsistencyError):
                    checks.check_contract(self.tree)

    def test_scoped_claims_and_historical_versions_are_checked(self) -> None:
        changes = (
            (checks.SCOPED_DOCS[0], "no exporter or native N3 writer", "an exporter and a native N3 writer", "no-writer"),
            (checks.SCOPED_DOCS[0], "does not consume the optional Blender receipt", "consumes the optional Blender receipt", "non-consumption"),
            (checks.SCOPED_DOCS[1], "neither reads nor validates", "reads and validates", "non-consumption"),
            (checks.SCOPED_DOCS[2], "does not consume, validate, or stage a receipt", "consumes, validates, and stages a receipt", "non-consumption"),
            (checks.SCOPED_DOCS[3], "does not read or validate a receipt", "reads and validates a receipt", "non-consumption"),
            (checks.SCOPED_DOCS[2], "1.2.3 baseline", "1.2.2 baseline", "baseline version"),
            (checks.SCOPED_DOCS[1], "eight read-only operators", "seven read-only operators", "capability table"),
        )
        for name, old, new, message in changes:
            with self.subTest(name=name, old=old):
                original = self.tree.read(self.tree.path(name))
                self.tree.put(name, original.replace(old, new))
                with self.assertRaisesRegex(checks.ConsistencyError, message):
                    checks.check_contract(self.tree)
                self.tree.put(name, original)

    def test_conflicting_or_fenced_receipt_claims_are_rejected(self) -> None:
        name = checks.SCOPED_DOCS[2]
        original = self.tree.read(self.tree.path(name))
        changes = (
            original.replace(
                "stager does not consume, validate, or stage a receipt",
                "stager consumes a receipt\n\n```\n"
                "stager does not consume, validate, or stage a receipt\n```",
            ),
            original + "\nThe stager consumes the receipt.\n",
            original + "\nThe native writer is implemented.\n",
        )
        for changed in changes:
            with self.subTest(changed=changed[-160:]):
                self.tree.put(name, changed)
                with self.assertRaises(checks.ConsistencyError):
                    checks.check_contract(self.tree)
        self.tree.put(name, original)

    def test_operator_table_drift_is_detected(self) -> None:
        name = checks.SCOPED_DOCS[0]
        original = self.tree.read(self.tree.path(name))
        row = "| Synthetic 0 | `import_scene.n3_bm` |\n"
        for replacement in ("", row + row, "| Extra | `export_scene.n3` |\n"):
            with self.subTest(replacement=replacement):
                self.tree.put(name, original.replace(row, replacement))
                with self.assertRaisesRegex(checks.ConsistencyError, "operator table"):
                    checks.check_contract(self.tree)

    def test_schema_version_shape_and_fingerprint_drift(self) -> None:
        changes = (
            (lambda value: value["properties"]["schemaVersion"].update(const=2), "schemaVersion 1"),
            (lambda value: value["properties"]["schemaVersion"].update(const=True), "schemaVersion 1"),
            (lambda value: value["required"].append("schemaVersion"), "schemaVersion 1"),
            (lambda value: value["required"].append({}), "schemaVersion 1"),
            (lambda value: value.update(description="changed contract"), "fingerprint mismatch"),
        )
        for change, message in changes:
            with self.subTest(message=message):
                schema = copy.deepcopy(self.schema)
                change(schema)
                self.tree.put(checks.SCHEMA_PATH, json.dumps(schema))
                with self.assertRaisesRegex(checks.ConsistencyError, message):
                    checks.check_contract(self.tree)
        self.tree.put(checks.SCHEMA_PATH, json.dumps(self.schema, indent=4))
        checks.check_contract(self.tree)
        self.tree.put(checks.SCHEMA_PATH, '{"type":"object","type":"array"}')
        with self.assertRaisesRegex(checks.ConsistencyError, "duplicate JSON key"):
            checks.check_contract(self.tree)

    def test_stager_receipt_reference_requires_claim_review(self) -> None:
        self.tree.put(
            "tools/mods.py",
            "def load_mod(root):\n    return (root / 'n3-blender-export.json').read_text()\n",
        )
        with self.assertRaisesRegex(checks.ConsistencyError, "stager references the Blender receipt"):
            checks.check_contract(self.tree)

    def test_generic_or_aliased_stager_root_reads_require_review(self) -> None:
        original = self.tree.read(self.tree.path("tools/mods.py"))
        changes = (
            original.replace(
                "    files = _scan_mod_files(root / 'files')",
                "    for path in root.glob('*.json'):\n        path.read_text()\n"
                "    files = _scan_mod_files(root / 'files')",
            ),
            original.replace("    manifest_path = root / 'mod.toml'", "    alias = root\n    manifest_path = root / 'mod.toml'"),
            original.replace("    return manifest_path.read_text()", "    return manifest_path.parent.iterdir()"),
            original.replace("    return ()", "    return path.parent.iterdir()", 1),
            original + "\ndef consume_receipt(path):\n    return path.read_text()\n",
            original + "\ndef stage(mod):\n    return mod.root.iterdir()\n",
        )
        for changed in changes:
            with self.subTest(changed=changed[-160:]):
                self.tree.put("tools/mods.py", changed)
                with self.assertRaisesRegex(checks.ConsistencyError, "unverified|requires review"):
                    checks.check_contract(self.tree)

    def test_mocked_validation_and_staging_ignore_malformed_receipt(self) -> None:
        base = self.tree.root
        mod_root = base / "mods" / "author.synthetic"
        manifest_path = mod_root / "mod.toml"
        receipt_path = mod_root / "n3-blender-export.json"
        payload = mod_root / "files" / "data" / "fixture.bm"
        mod_file = mods.ModFile(PurePosixPath("data/fixture.bm"), payload)
        manifest = b'[mod]\nid = "author.synthetic"\nname = "Synthetic"\nversion = "1.0.0"\n'
        opened = []

        def fake_open(path: Path, mode: str = "r", *args: object, **kwargs: object):
            opened.append(path)
            if path == manifest_path:
                return io.BytesIO(manifest)
            if path == receipt_path:
                return io.BytesIO(b"{ malformed") if "b" in mode else io.StringIO("{ malformed")
            raise AssertionError(f"unexpected open: {path}")

        with (
            mock.patch.object(Path, "is_dir", autospec=True, return_value=True),
            mock.patch.object(Path, "is_file", autospec=True, side_effect=lambda path: path in {manifest_path, receipt_path}),
            mock.patch.object(Path, "open", autospec=True, side_effect=fake_open),
            mock.patch.object(mods, "_is_link_or_reparse", return_value=False),
            mock.patch.object(mods, "_scan_mod_files", return_value=(mod_file,)) as scan,
        ):
            mod = mods.load_mod(mod_root)
        self.assertEqual(opened, [manifest_path])
        scan.assert_called_once_with(mod_root / "files")
        self.assertEqual(mod.files, (mod_file,))

        game = base / "game"
        mods_root = base / "mods"
        order = base / "enabled.txt"
        output = base / "out" / "game"
        staging = base / "out" / ".synthetic-stage"
        with (
            mock.patch.object(mods, "_stage_output", return_value=output),
            mock.patch.object(mods, "_resolve_path", side_effect=lambda path: path),
            mock.patch.object(mods, "_exists_without_following", return_value=False),
            mock.patch.object(mods, "_is_link_or_reparse", return_value=False),
            mock.patch.object(mods, "load_enabled_mods", return_value=(mod,)),
            mock.patch.object(mods, "_scan_base_files", return_value={}),
            mock.patch.object(mods, "_copy_base", return_value=(0, 0)),
            mock.patch.object(Path, "exists", autospec=True, return_value=False),
            mock.patch.object(Path, "mkdir", autospec=True),
            mock.patch.object(Path, "write_text", autospec=True) as write_report,
            mock.patch.object(Path, "open", autospec=True, side_effect=AssertionError("unexpected file read")),
            mock.patch.object(mods.tempfile, "mkdtemp", return_value=str(staging)),
            mock.patch.object(mods.os, "replace") as replace,
            mock.patch.object(mods.shutil, "copy2") as copy_payload,
        ):
            report = mods.stage_mods(game, mods_root, order, output, replace=False, copy_base=True)
        copy_payload.assert_called_once_with(payload, staging / "data" / "fixture.bm")
        replace.assert_called_once_with(staging, output)
        self.assertEqual([entry["path"] for entry in report["overrides"]], ["data/fixture.bm"])
        self.assertNotIn("n3-blender-export", json.dumps(report))
        self.assertEqual(write_report.call_args.args[0], staging / mods.REPORT_NAME)

    def test_missing_scoped_input_reports_a_failure(self) -> None:
        del self.tree.files[self.tree.path(checks.SCHEMA_PATH)]
        stderr = io.StringIO()
        with mock.patch.object(checks, "FileTree", return_value=self.tree), redirect_stderr(stderr):
            self.assertEqual(checks.main(["--root", str(self.tree.root)]), 1)
        self.assertIn("missing local link target", stderr.getvalue())
        self.assertIn("n3-blender-export-v1.schema.json", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
