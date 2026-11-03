"""Regression tests for the offline N3 mod stager."""

# Adapted from N3-ReGPU commit c03c26e7b80851a391ffb5f19bbc499c0f84fb5c
# under its MIT license. See LICENSES/N3-ReGPU.txt.

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from tools import mods


def make_mod(root: Path, mod_id: str, files: dict[str, bytes]) -> None:
    mod_root = root / mod_id
    mod_root.mkdir(parents=True)
    (mod_root / "mod.toml").write_text(
        "\n".join(
            (
                "[mod]",
                f'id = "{mod_id}"',
                f'name = "{mod_id}"',
                'version = "1.0.0"',
                "",
            )
        ),
        encoding="utf-8",
    )
    for relative, content in files.items():
        target = mod_root / "files" / Path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)


class ModTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.game = self.root / "game"
        self.mods = self.root / "mods"
        self.output = self.root / "out" / "game"
        self.project_root = mock.patch.object(mods, "PROJECT_ROOT", self.root)
        self.project_root.start()
        self.addCleanup(self.project_root.stop)
        (self.game / "data" / "interface").mkdir(parents=True)
        (self.game / "data" / "Prop").mkdir(parents=True)
        (self.game / "default.xex").write_bytes(b"xex")
        (self.game / "data" / "interface" / "sample.36t").write_bytes(
            b"base-texture"
        )
        (self.game / "data" / "Prop" / "sample.bm").write_bytes(b"base-model")
        self.mods.mkdir()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def make_directory_link(self, link: Path, target: Path) -> None:
        try:
            os.symlink(target, link, target_is_directory=True)
            return
        except OSError as error:
            if os.name != "nt":
                self.skipTest(f"Directory links are unavailable: {error}")
        powershell = shutil.which("pwsh") or shutil.which("powershell.exe")
        if not powershell:
            self.skipTest(
                "Directory symlinks and PowerShell junction creation are unavailable"
            )
        environment = os.environ.copy()
        environment.update(
            N3_TEST_LINK=str(link), N3_TEST_TARGET=str(target)
        )
        result = subprocess.run(
            [
                powershell,
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "New-Item -ItemType Junction -Path $env:N3_TEST_LINK "
                "-Target $env:N3_TEST_TARGET | Out-Null",
            ],
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            self.skipTest(
                f"Directory junctions are unavailable: {result.stderr.strip()}"
            )

    @staticmethod
    def remove_directory_link(link: Path) -> None:
        if os.name == "nt":
            os.rmdir(link)
        else:
            link.unlink()

    def test_stages_overrides_without_changing_base(self) -> None:
        make_mod(
            self.mods,
            "author.first",
            {
                "data/interface/sample.36t": b"first-texture",
                "data/Prop/new.skin": b"new-skin",
            },
        )
        make_mod(
            self.mods,
            "author.second",
            {
                "data/interface/sample.36t": b"second-texture",
                "data/Prop/sample.bm": b"second-model",
            },
        )
        order = self.mods / "enabled.txt"
        order.write_text("author.first\nauthor.second\n", encoding="utf-8")

        report = mods.stage_mods(
            self.game,
            self.mods,
            order,
            self.output,
            replace=False,
            copy_base=False,
        )

        self.assertEqual(
            (self.game / "data" / "interface" / "sample.36t").read_bytes(),
            b"base-texture",
        )
        self.assertEqual(
            (self.output / "data" / "interface" / "sample.36t").read_bytes(),
            b"second-texture",
        )
        self.assertEqual(
            (self.output / "data" / "Prop" / "sample.bm").read_bytes(),
            b"second-model",
        )
        self.assertEqual(
            (self.output / "data" / "Prop" / "new.skin").read_bytes(),
            b"new-skin",
        )
        self.assertEqual(len(report["conflicts"]), 1)
        self.assertEqual(report["conflicts"][0]["winner"], "author.second")

        stored = json.loads(
            (self.output / mods.REPORT_NAME).read_text(encoding="utf-8")
        )
        self.assertEqual(
            stored["loadOrder"], ["author.first", "author.second"]
        )
        self.assertFalse(
            os.path.samefile(
                self.game / "data" / "interface" / "sample.36t",
                self.output / "data" / "interface" / "sample.36t",
            )
        )
        self.assertFalse(
            os.path.samefile(
                self.mods
                / "author.second"
                / "files"
                / "data"
                / "interface"
                / "sample.36t",
                self.output / "data" / "interface" / "sample.36t",
            )
        )
        (
            self.output / "data" / "interface" / "sample.36t"
        ).write_bytes(b"edited-override")
        self.assertEqual(
            (self.game / "data" / "interface" / "sample.36t").read_bytes(),
            b"base-texture",
        )

    def test_discovers_all_mods_in_stable_order(self) -> None:
        make_mod(
            self.mods,
            "zeta.model",
            {"data/Prop/sample.bm": b"model"},
        )
        make_mod(
            self.mods,
            "alpha.texture",
            {"data/interface/sample.36t": b"texture"},
        )

        discovered = mods.discover_mods(self.mods)

        self.assertEqual(
            [mod.id for mod in discovered],
            ["alpha.texture", "zeta.model"],
        )
        self.assertEqual([len(mod.files) for mod in discovered], [1, 1])

    def test_ignores_malformed_blender_receipt_when_validating_and_staging(
        self,
    ) -> None:
        mod_id = "author.blender"
        make_mod(self.mods, mod_id, {"data/Prop/sample.bm": b"synthetic-model"})
        order = self.mods / "enabled.txt"
        order.write_text(f"{mod_id}\n", encoding="utf-8")
        without_receipt = mods.load_enabled_mods(self.mods, order)

        receipt = self.mods / mod_id / "n3-blender-export.json"
        malformed = b'{"schemaVersion": 1, "modId": '
        receipt.write_bytes(malformed)
        with self.assertRaises(json.JSONDecodeError):
            json.loads(malformed)
        self.assertEqual(mods.load_enabled_mods(self.mods, order), without_receipt)

        with mock.patch("builtins.print"):
            self.assertEqual(
                mods.main(
                    ["validate", "--mods", str(self.mods), "--order", str(order)]
                ),
                0,
            )
            self.assertEqual(
                mods.main(
                    [
                        "stage",
                        "--game",
                        str(self.game),
                        "--mods",
                        str(self.mods),
                        "--order",
                        str(order),
                        "--output",
                        str(self.output),
                        "--copy-base",
                    ]
                ),
                0,
            )

        self.assertEqual(receipt.read_bytes(), malformed)
        self.assertEqual(
            (self.output / "data" / "Prop" / "sample.bm").read_bytes(),
            b"synthetic-model",
        )
        self.assertEqual(
            {
                path.relative_to(self.output).as_posix()
                for path in self.output.rglob("*")
                if path.is_file()
            },
            {
                mods.REPORT_NAME,
                "default.xex",
                "data/interface/sample.36t",
                "data/Prop/sample.bm",
            },
        )
        report = json.loads(
            (self.output / mods.REPORT_NAME).read_text(encoding="utf-8")
        )
        self.assertEqual(report["loadOrder"], [mod_id])
        self.assertEqual(
            report["overrides"],
            [
                {
                    "path": "data/Prop/sample.bm",
                    "winner": mod_id,
                    "providers": [mod_id],
                    "replacesBase": True,
                }
            ],
        )
        self.assertNotIn(receipt.name, json.dumps(report))

    def test_copied_base_can_be_modified_without_changing_original(self) -> None:
        order = self.mods / "enabled.txt"
        order.write_text("", encoding="utf-8")
        report = mods.stage_mods(
            self.game,
            self.mods,
            order,
            self.output,
            replace=False,
            copy_base=True,
        )

        base = self.game / "data" / "Prop" / "sample.bm"
        staged = self.output / "data" / "Prop" / "sample.bm"
        self.assertEqual(report["hardlinkedBaseFiles"], 0)
        self.assertEqual(report["copiedBaseFiles"], report["baseFiles"])
        self.assertFalse(os.path.samefile(base, staged))
        staged.write_bytes(b"edited-copy")
        self.assertEqual(base.read_bytes(), b"base-model")

    def test_hardlinked_base_is_shared_but_overrides_are_private(self) -> None:
        make_mod(
            self.mods,
            "author.texture",
            {"data/interface/sample.36t": b"private-override"},
        )
        order = self.mods / "enabled.txt"
        order.write_text("author.texture\n", encoding="utf-8")
        report = mods.stage_mods(
            self.game,
            self.mods,
            order,
            self.output,
            replace=False,
            copy_base=False,
        )
        if report["hardlinkedBaseFiles"] == 0:
            self.skipTest("The filesystem did not support hardlinks")

        self.assertTrue(
            os.path.samefile(
                self.game / "default.xex", self.output / "default.xex"
            )
        )
        base = self.game / "data" / "interface" / "sample.36t"
        override = self.output / "data" / "interface" / "sample.36t"
        self.assertFalse(os.path.samefile(base, override))
        override.write_bytes(b"edited-override")
        self.assertEqual(base.read_bytes(), b"base-texture")

    def test_replace_rebuilds_existing_stage(self) -> None:
        make_mod(
            self.mods,
            "author.texture",
            {"data/interface/sample.36t": b"version-one"},
        )
        order = self.mods / "enabled.txt"
        order.write_text("author.texture\n", encoding="utf-8")
        mods.stage_mods(
            self.game,
            self.mods,
            order,
            self.output,
            replace=False,
            copy_base=True,
        )

        source = (
            self.mods
            / "author.texture"
            / "files"
            / "data"
            / "interface"
            / "sample.36t"
        )
        source.write_bytes(b"version-two")
        mods.stage_mods(
            self.game,
            self.mods,
            order,
            self.output,
            replace=True,
            copy_base=True,
        )
        self.assertEqual(
            (self.output / "data" / "interface" / "sample.36t").read_bytes(),
            b"version-two",
        )

    def test_default_cli_paths_follow_project_root(self) -> None:
        (self.root / "mods" / "enabled.txt").write_text("", encoding="utf-8")
        self.game.rename(self.root / "private-game")
        (self.root / "private").mkdir()
        (self.root / "private-game").rename(self.root / "private" / "game")
        self.assertEqual(mods.main(["validate"]), 0)
        with mock.patch("builtins.print") as output:
            self.assertEqual(
                mods.main(["stage", "--copy-base"]),
                0,
            )
        messages = [str(call.args[0]) for call in output.call_args_list]
        self.assertIn("Copied 3 base files as requested", messages)
        self.assertFalse(any("unavailable" in message for message in messages))
        self.assertTrue((self.output / mods.REPORT_NAME).is_file())

    def test_rejects_executable_override(self) -> None:
        make_mod(self.mods, "author.bad", {"default.xex": b"replacement"})
        order = self.mods / "enabled.txt"
        order.write_text("author.bad\n", encoding="utf-8")
        with self.assertRaisesRegex(
            mods.ModError, "only provide files under data"
        ):
            mods.load_enabled_mods(self.mods, order)

    def test_rejects_duplicate_load_order(self) -> None:
        order = self.mods / "enabled.txt"
        order.write_text("author.same\nauthor.same\n", encoding="utf-8")
        with self.assertRaisesRegex(mods.ModError, "Duplicate mod ID"):
            mods.read_load_order(order)

    def test_rejects_arbitrary_output_before_touching_source(self) -> None:
        order = self.mods / "enabled.txt"
        order.write_text("", encoding="utf-8")
        with self.assertRaisesRegex(mods.ModError, "project's out/game"):
            mods.stage_mods(
                self.game,
                self.mods,
                order,
                self.game / "staged",
                replace=False,
                copy_base=True,
            )
        self.assertEqual((self.game / "default.xex").read_bytes(), b"xex")
        self.assertFalse((self.game / "staged").exists())

    def test_cli_rejects_destination_outside_project(self) -> None:
        order = self.mods / "enabled.txt"
        order.write_text("", encoding="utf-8")
        result = subprocess.run(
            [
                sys.executable,
                str(Path(mods.__file__).resolve()),
                "stage",
                "--game",
                str(self.game),
                "--mods",
                str(self.mods),
                "--order",
                str(order),
                "--output",
                str(self.output),
                "--replace",
            ],
            cwd=self.root,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("project's out/game", result.stderr)
        self.assertFalse(self.output.exists())
        self.assertEqual((self.game / "default.xex").read_bytes(), b"xex")

    def test_rejects_source_and_output_overlap(self) -> None:
        order = self.mods / "enabled.txt"
        order.write_text("", encoding="utf-8")
        self.output.mkdir(parents=True)
        sentinel = self.output / "sentinel"
        sentinel.write_bytes(b"keep")

        for game, mods_root, order_path in (
            (self.root, self.mods, order),
            (self.game / "..", self.mods, order),
            (self.output / "nested", self.mods, order),
            (self.game, self.root, order),
            (self.game, self.mods, self.output / "enabled.txt"),
        ):
            with self.subTest(
                game=game, mods=mods_root, order=order_path
            ):
                with self.assertRaisesRegex(
                    mods.ModError, "must not overlap"
                ):
                    mods.stage_mods(
                        game,
                        mods_root,
                        order_path,
                        self.output,
                        replace=True,
                        copy_base=True,
                    )
                self.assertEqual(sentinel.read_bytes(), b"keep")
                self.assertEqual(
                    (self.game / "default.xex").read_bytes(), b"xex"
                )

    def test_rejects_output_aliasing_source_via_ancestor_link(self) -> None:
        order = self.mods / "enabled.txt"
        order.write_text("", encoding="utf-8")
        self.output.mkdir(parents=True)
        sentinel = self.output / "sentinel"
        sentinel.write_bytes(b"keep")
        alias = self.root / "alias"
        self.make_directory_link(alias, self.output.parent)
        try:
            with self.assertRaisesRegex(mods.ModError, "must not overlap"):
                mods.stage_mods(
                    alias / "game",
                    self.mods,
                    order,
                    self.output,
                    replace=True,
                    copy_base=True,
                )
            self.assertEqual(sentinel.read_bytes(), b"keep")
        finally:
            self.remove_directory_link(alias)

    def test_rejects_linked_output_parent(self) -> None:
        order = self.mods / "enabled.txt"
        order.write_text("", encoding="utf-8")
        self.make_directory_link(self.output.parent, self.game)
        try:
            with self.assertRaisesRegex(
                mods.ModError, "link or reparse"
            ):
                mods.stage_mods(
                    self.game,
                    self.mods,
                    order,
                    self.output,
                    replace=True,
                    copy_base=True,
                )
            self.assertEqual(
                (self.game / "default.xex").read_bytes(), b"xex"
            )
            self.assertFalse((self.game / "game").exists())
        finally:
            self.remove_directory_link(self.output.parent)

    def test_rejects_linked_existing_stage(self) -> None:
        order = self.mods / "enabled.txt"
        order.write_text("", encoding="utf-8")
        self.output.parent.mkdir()
        self.make_directory_link(self.output, self.game)
        try:
            with self.assertRaisesRegex(
                mods.ModError, "link or reparse"
            ):
                mods.stage_mods(
                    self.game,
                    self.mods,
                    order,
                    self.output,
                    replace=True,
                    copy_base=True,
                )
            self.assertEqual(
                (self.game / "default.xex").read_bytes(), b"xex"
            )
        finally:
            self.remove_directory_link(self.output)

    def test_rejects_reserved_report_collision_without_mutating_base(
        self,
    ) -> None:
        order = self.mods / "enabled.txt"
        order.write_text("", encoding="utf-8")
        report = self.game / ".N3-MODS.JSON"
        report.write_bytes(b"original")
        with self.assertRaisesRegex(
            mods.ModError, "reserved staging report"
        ):
            mods.stage_mods(
                self.game,
                self.mods,
                order,
                self.output,
                replace=False,
                copy_base=False,
            )
        self.assertEqual(report.read_bytes(), b"original")
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
