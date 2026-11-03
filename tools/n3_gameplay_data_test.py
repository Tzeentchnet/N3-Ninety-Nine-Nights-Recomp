"""Regression tests for the read-only N3 gameplay-data inspector."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
import zlib

from tools import n3_gameplay_data as gameplay


def align(value: int, alignment: int = gameplay.PAK_ALIGNMENT) -> int:
    return (value + alignment - 1) // alignment * alignment


def build_sox(
    columns: list[tuple[str, int]],
    rows: list[list[int | bytes | str]],
    *,
    key: int = 0x12345678,
    footer_padding: bytes = b"\0" * 11,
) -> bytes:
    header = bytearray(gameplay.SOX_ROW_DATA_OFFSET)
    struct.pack_into(">III", header, 0, key, len(columns), len(rows))
    for index, (name, type_code) in enumerate(columns):
        encoded = name.encode("ascii")
        if len(encoded) >= 64:
            raise ValueError("synthetic column name is too long")
        offset = 12 + index * gameplay.SOX_DESCRIPTOR_SIZE
        header[offset : offset + 64] = encoded + b"\0" + b" " * (63 - len(encoded))
        struct.pack_into(">I", header, offset + 64, type_code)

    body = bytearray()
    for row_id, values in enumerate(rows, 1):
        if len(values) != len(columns):
            raise ValueError("synthetic row width does not match the schema")
        body += struct.pack(">I", row_id)
        for (_name, type_code), value in zip(columns, values, strict=True):
            if type_code == 1:
                raw = value.encode("utf-8") if isinstance(value, str) else bytes(value)
                body += struct.pack(">H", len(raw)) + raw
            else:
                body += struct.pack(">i", int(value))
    return bytes(header + body + gameplay.SOX_FOOTER + footer_padding)


def build_pak(entries: list[tuple[str, bytes]], *, wrapped: bool) -> bytes:
    table_end = 4 + len(entries) * gameplay.PAK_ENTRY_SIZE
    cursor = align(table_end)
    payload = bytearray(cursor)
    struct.pack_into(">I", payload, 0, len(entries))
    for index, (name, data) in enumerate(entries):
        encoded = name.encode("ascii")
        if len(encoded) >= gameplay.PAK_NAME_SIZE:
            raise ValueError("synthetic member name is too long")
        record = 4 + index * gameplay.PAK_ENTRY_SIZE
        payload[record : record + gameplay.PAK_NAME_SIZE] = (
            encoded + b"\0" * (gameplay.PAK_NAME_SIZE - len(encoded))
        )
        struct.pack_into(">III", payload, record + 256, 0, cursor, len(data))
        payload.extend(data)
        cursor = align(len(payload))
        payload.extend(b"\0" * (cursor - len(payload)))

    if not wrapped:
        return bytes(payload)
    compressed = zlib.compress(bytes(payload), 6)
    result = bytearray(struct.pack(">I", len(payload)))
    result.extend(b"\0" * (gameplay.PAK_OUTER_HEADER_SIZE - len(result)))
    result.extend(compressed)
    result.extend(b"\0" * (align(len(result)) - len(result)))
    return bytes(result)


def build_compiled_ai_tokens(tokens: list[str]) -> bytes:
    data = bytearray(b"\0" * 8)
    for token in tokens:
        encoded = token.encode("ascii")
        data += struct.pack(">I", len(encoded) + 1)
        data += encoded + b"\0"
        data += b"\0" * 8
    return bytes(data)


class PakTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_pak(self, data: bytes, name: str = "sample.pak") -> Path:
        path = self.root / name
        path.write_bytes(data)
        return path

    def test_reads_raw_archive_and_preserves_duplicate_records(self) -> None:
        path = self.write_pak(
            build_pak(
                [
                    ("FIRST.SOX", b"first"),
                    ("duplicate.bin", b"same"),
                    ("duplicate.bin", b"same"),
                ],
                wrapped=False,
            )
        )
        archive = gameplay.read_pak(path)

        self.assertFalse(archive.wrapped)
        self.assertEqual(len(archive.members), 3)
        self.assertEqual(archive.duplicate_extra_count, 1)
        duplicates = archive.find("DUPLICATE.BIN")
        self.assertEqual(len(duplicates), 2)
        self.assertEqual(archive.read_member(duplicates[0]), b"same")

    def test_reads_zlib_wrapped_archive_with_zero_padding(self) -> None:
        path = self.write_pak(
            build_pak([("TABLE.SOX", b"payload")], wrapped=True)
        )
        archive = gameplay.read_pak(path)

        self.assertTrue(archive.wrapped)
        self.assertGreater(archive.compressed_size, 0)
        self.assertEqual(archive.read_member(archive.members[0]), b"payload")

    def test_rejects_nonzero_data_after_zlib_stream(self) -> None:
        data = bytearray(build_pak([("TABLE.SOX", b"payload")], wrapped=True))
        data[-1] = 1
        path = self.write_pak(bytes(data))

        with self.assertRaisesRegex(
            gameplay.GameplayDataError, "nonzero data follows"
        ):
            gameplay.read_pak(path)

    def test_rejects_reserved_member_value(self) -> None:
        data = bytearray(build_pak([("TABLE.SOX", b"payload")], wrapped=False))
        struct.pack_into(">I", data, 4 + 256, 9)
        path = self.write_pak(bytes(data))

        with self.assertRaisesRegex(gameplay.GameplayDataError, "reserved value"):
            gameplay.read_pak(path)

    def test_rejects_member_outside_archive(self) -> None:
        data = bytearray(build_pak([("TABLE.SOX", b"payload")], wrapped=False))
        struct.pack_into(">I", data, 4 + 264, len(data))
        path = self.write_pak(bytes(data))

        with self.assertRaisesRegex(gameplay.GameplayDataError, "exceeds archive"):
            gameplay.read_pak(path)


class CompiledAiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def resource(name: str, kind: str, data: bytes) -> gameplay.CompiledResource:
        return gameplay.CompiledResource(
            name=name,
            kind=kind,
            sha256=hashlib.sha256(data).hexdigest(),
            archives=("stage_res2_res.pak",),
            occurrences=1,
        )

    @staticmethod
    def program_payload(source: str = "C_TEST_Default.ai") -> bytes:
        return build_compiled_ai_tokens(
            [
                "include_ai",
                "Function\\TroopCommand.ai_func",
                "include_ai",
                "Function\\BattleMeleeAttack.ai_func",
                "AI_ELEMENT",
                "AI_FUNC",
                "TroopCommand",
                "iflevel",
                "BattleMeleeAttack",
                "TroopCommand",
                "endlevel",
                "AI_FUNC_END",
                "AI_ELEMENT_END",
                f"ai\\unit\\{source}",
                "AIDef.h",
            ]
        )

    @staticmethod
    def module_payload() -> bytes:
        return build_compiled_ai_tokens(
            [
                "AI_FUNCTION_PARAMETER",
                "v_SlotIndex",
                "v_Probability",
                "AI_FUNCTION_PARAMETER_END",
                "AI_ELEMENT",
                "AI_ELEMENT_END",
                "ai\\unit\\function\\TroopCommand.ai_func",
                "AIDef.h",
            ]
        )

    def test_extracts_ai_composition_level_gates_and_module_parameters(self) -> None:
        program_data = self.program_payload()
        program = gameplay.parse_ai_program(
            self.resource("C_TEST_DEFAULT.AIB", ".aib", program_data),
            program_data,
        )
        self.assertEqual(program.source_path, "ai\\unit\\C_TEST_Default.ai")
        self.assertEqual(
            program.included_functions,
            ("TroopCommand", "BattleMeleeAttack"),
        )
        self.assertEqual(
            program.called_functions,
            ("TroopCommand", "BattleMeleeAttack", "TroopCommand"),
        )
        self.assertEqual(program.unique_called_functions, (
            "TroopCommand",
            "BattleMeleeAttack",
        ))
        self.assertEqual(program.level_branch_count, 1)

        module_data = self.module_payload()
        module = gameplay.parse_ai_function_module(
            self.resource("TROOPCOMMAND.AI_FUNCB", ".ai_funcb", module_data),
            module_data,
        )
        self.assertEqual(
            module.parameters, ("v_SlotIndex", "v_Probability")
        )
        self.assertEqual(
            module.source_path,
            "ai\\unit\\function\\TroopCommand.ai_func",
        )

    def test_collapses_identical_stage_resources_by_logical_name(self) -> None:
        program = self.program_payload()
        module = self.module_payload()
        entries = [
            ("C_TEST_DEFAULT.AIB", program),
            ("TROOPCOMMAND.AI_FUNCB", module),
            ("C_TEST.as", b"attack script"),
            ("C_TEST.info", b"unit info"),
        ]
        for name in ("one_res2_res.pak", "two_res2_res.pak"):
            (self.root / name).write_bytes(build_pak(entries, wrapped=True))

        index = gameplay.load_compiled_resource_index(self.root)
        self.assertEqual(index.archive_count, 2)
        self.assertEqual(len(index.programs), 1)
        self.assertEqual(len(index.function_modules), 1)
        resource = index.find_resource("c_test_default.aib")
        self.assertIsNotNone(resource)
        assert resource is not None
        self.assertEqual(resource.occurrences, 2)
        self.assertEqual(resource.archives, (
            "one_res2_res.pak",
            "two_res2_res.pak",
        ))
        self.assertIsNotNone(index.find_function_module("TroopCommand"))

    def test_rejects_conflicting_stage_resources_with_the_same_name(self) -> None:
        (self.root / "one_res2_res.pak").write_bytes(
            build_pak(
                [("C_TEST_DEFAULT.AIB", self.program_payload())],
                wrapped=True,
            )
        )
        (self.root / "two_res2_res.pak").write_bytes(
            build_pak(
                [
                    (
                        "C_TEST_DEFAULT.AIB",
                        self.program_payload("C_OTHER_Default.ai"),
                    )
                ],
                wrapped=True,
            )
        )

        with self.assertRaisesRegex(
            gameplay.GameplayDataError,
            "differs between one_res2_res.pak and two_res2_res.pak",
        ):
            gameplay.load_compiled_resource_index(self.root)


class SoxTests(unittest.TestCase):
    def test_parses_all_observed_types_and_duplicate_headings(self) -> None:
        data = build_sox(
            [("Name", 1), ("Value", 2), ("Value", 3)],
            [[b"alpha", -4, 9], ["beta", 10, -12]],
        )
        table = gameplay.parse_sox(data, "sample.sox")

        self.assertEqual(table.key, 0x12345678)
        self.assertEqual(table.column_indices("value"), (1, 2))
        self.assertEqual(table.rows[0].values, (b"alpha", -4, 9))
        self.assertEqual(table.rows[1].row_id, 2)
        self.assertEqual(table.footer_size, len(gameplay.SOX_FOOTER) + 11)

    def test_rejects_unknown_column_type(self) -> None:
        data = build_sox([("Unknown", 99)], [[1]])
        with self.assertRaisesRegex(gameplay.GameplayDataError, "unsupported type"):
            gameplay.parse_sox(data, "unknown.sox")

    def test_rejects_nonsequential_row_id(self) -> None:
        data = bytearray(build_sox([("Value", 3)], [[1], [2]]))
        second_id = gameplay.SOX_ROW_DATA_OFFSET + 8
        struct.pack_into(">I", data, second_id, 7)
        with self.assertRaisesRegex(gameplay.GameplayDataError, "expected 2"):
            gameplay.parse_sox(bytes(data), "rows.sox")

    def test_rejects_truncated_string(self) -> None:
        data = bytearray(build_sox([("Name", 1)], [[b"abc"]]))
        struct.pack_into(">H", data, gameplay.SOX_ROW_DATA_OFFSET + 4, 0x7FFF)
        with self.assertRaisesRegex(gameplay.GameplayDataError, "exceeds the file"):
            gameplay.parse_sox(bytes(data), "string.sox")

    def test_rejects_missing_footer(self) -> None:
        data = bytearray(build_sox([("Value", 3)], [[1]]))
        footer = gameplay.SOX_ROW_DATA_OFFSET + 8
        data[footer : footer + len(gameplay.SOX_FOOTER)] = b"XXXXX"
        with self.assertRaisesRegex(gameplay.GameplayDataError, "missing THEND"):
            gameplay.parse_sox(bytes(data), "footer.sox")

    def test_decodes_language_hints_without_losing_raw_values(self) -> None:
        korean = "기사의 문장".encode("cp949")
        self.assertEqual(gameplay.decode_string(korean, "cp949"), "기사의 문장")
        self.assertEqual(gameplay.display_value(-12), "-12")


class GameDataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.game = self.root / "game"
        self.packed = self.game / "data" / "PackedResources"
        self.packed.mkdir(parents=True)
        (self.game / "default.xex").write_bytes(b"synthetic executable")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_loads_synthetic_extraction_and_exports_structure_only(self) -> None:
        character = build_sox(
            [("name", 1), ("unit type", 3), ("MaxLevel", 3)],
            [[b"C_TEST", 1000, 9]],
        )
        (self.packed / "res_init.pak").write_bytes(
            build_pak([("CHARDATA.SOX", character)], wrapped=True)
        )
        loose_root = self.game / "data" / "sox"
        loose_root.mkdir()
        (loose_root / "abilitytable.sox").write_bytes(
            build_sox(
                [
                    ("_AbilityID", 3),
                    ("_UnitSoxID", 3),
                    ("_Level", 3),
                    ("_2DImgFileName", 1),
                ],
                [[0, 0, 1, b""]],
            )
        )

        data = gameplay.load_game_data(self.game)
        self.assertEqual(data.build.status, "mismatch")
        self.assertEqual(len(data.tables), 2)
        self.assertEqual(len(data.units()), 1)
        self.assertTrue(data.warnings)

        destination = self.root / "report.json"
        gameplay.write_structural_report(data, destination)
        report = json.loads(destination.read_text(encoding="utf-8"))
        self.assertTrue(report["readOnly"])
        self.assertEqual(len(report["tables"]), 2)
        serialized = destination.read_text(encoding="utf-8")
        self.assertNotIn(str(self.game), serialized)
        self.assertNotIn("C_TEST", serialized)

    def test_maps_playable_units_and_builds_hero_field_guides(self) -> None:
        unit_ids = [
            "C_LP_KM",
            "C_LP_KF",
            "C_LP_MF",
            "C_LP_PM",
            "C_LP_WM",
            "C_DP_TR",
            "C_DP_GB",
        ]
        character = build_sox(
            [("name", 1), ("unit type", 3), ("MaxLevel", 3)],
            [[unit_id.encode("ascii"), 1000 + index, 1] for index, unit_id in enumerate(unit_ids)],
        )
        families = (
            "MoveSpeed",
            "SlotCount",
            "OrbDecrease",
            "GuardianDefense",
            "GuardianHP",
            "GuardianControlTroopCount",
            "GuardianControlTroopUnitCount",
            "AttackRange",
        )
        hero_columns = [("UnitName", 1)] + [
            (f"{family}{level}", 3)
            for family in families
            for level in range(1, 10)
        ]
        hero_rows = []
        for index, unit_id in enumerate(unit_ids):
            values: list[int | bytes] = [unit_id.encode("ascii")]
            values += [100 + index * 5 + level for level in range(9)]
            values += [min(1 + level // 2, 5) for level in range(9)]
            values += [100] * 9
            values += [65 + level for level in range(9)]
            values += [800 + level * 100 for level in range(9)]
            values += [1] * 4 + [2] * 5
            values += [15 + level * 3 for level in range(9)]
            values += [level * 5 for level in range(9)]
            hero_rows.append(values)
        hero = build_sox(hero_columns, hero_rows)
        (self.packed / "res_init.pak").write_bytes(
            build_pak(
                [("CHARDATA.SOX", character), ("HEROTABLE.SOX", hero)],
                wrapped=True,
            )
        )

        data = gameplay.load_game_data(self.game)
        names = {unit.unit_id: unit.display_name for unit in data.units()}
        self.assertEqual(names["C_LP_MF"], "Tyurru")
        self.assertEqual(names["C_LP_PM"], "Klarrann")
        self.assertEqual(names["C_LP_WM"], "Myifee")
        self.assertEqual(names["C_DP_TR"], "Vigk Vagk")
        self.assertEqual(names["C_DP_GB"], "Dwingvatt")

        guides = {guide.key: guide for guide in data.hero_field_guides()}
        self.assertEqual(guides["level"].observed_range, (1, 9))
        self.assertEqual(guides["speed"].observed_range, (100, 138))
        self.assertEqual(guides["orb"].observed_values, (100,))
        self.assertIn("1..5", guides["slots"].known_limits)
        self.assertEqual(guides["total_units"].observed_range, (15, 78))
        self.assertIn("Current value: 125", guides["speed"].tooltip_text("125"))

    def test_builds_curve_guides_from_playable_rows_only(self) -> None:
        hero = build_sox(
            [("UnitName", 1)],
            [[b"C_LP_MF"], [b"C_DP_GB"]],
        )
        attack_columns = [("UnitName", 1)] + [
            (f"{prefix}{level}", 3)
            for prefix in ("Attack_enemy", "Attack_friend")
            for level in range(1, 12)
        ]
        attack = build_sox(
            attack_columns,
            [
                [b"C_LP_MF"] + list(range(10, 21)) + list(range(100, 111)),
                [b"C_DP_GB"] + list(range(20, 31)) + list(range(200, 211)),
                [b"C_NOT_HERO"] + [999] * 22,
            ],
        )
        matching_columns = [("name", 1)] + [
            (f"Level{level}", 3) for level in range(1, 13)
        ]
        matching = build_sox(
            matching_columns,
            [
                [b"C_LP_MF"] + list(range(1, 10)) + [9, 9, 9],
                [b"C_DP_GB"] + list(range(1, 10)) + [9, 9, 9],
                [b"C_NOT_HERO"] + [11] * 12,
            ],
        )
        (self.packed / "res_init.pak").write_bytes(
            build_pak(
                [
                    ("HEROTABLE.SOX", hero),
                    ("ATTACKTABLE.SOX", attack),
                    ("LEVELMATCHINGTABLE.SOX", matching),
                ],
                wrapped=True,
            )
        )

        data = gameplay.load_game_data(self.game)
        guides = {guide.key: guide for guide in data.hero_curve_guides()}
        self.assertEqual(guides["level"].observed_range, (1, 12))
        self.assertEqual(guides["atk_e"].observed_range, (10, 30))
        self.assertEqual(guides["atk_f"].observed_range, (100, 210))
        self.assertNotIn(999, guides["atk_f"].observed_values)
        self.assertEqual(guides["match"].observed_values, tuple(range(1, 10)))

    def test_builds_separate_npc_job_resource_stat_and_ai_relationships(self) -> None:
        character_columns = [
            ("name", 1),
            ("unit folder", 1),
            ("skin name", 1),
            ("skin variation num", 3),
            ("ani name", 1),
            ("unit type", 3),
            ("unit size", 3),
            ("AS file", 1),
            ("Second Job Index", 3),
            ("Parts file", 1),
            ("Unit Height", 3),
            ("troop type", 3),
            ("billboard size", 3),
            ("unit min scale", 3),
            ("unit max scale", 3),
            ("MaxLevel", 3),
            ("A_LevelOffset", 3),
            ("B_LevelOffset", 3),
            ("C_LevelOffset", 3),
            ("D_LevelOffset", 3),
            ("Use Level", 3),
            ("SoundAmor", 3),
            ("SoundWeapon", 3),
            ("Weight", 3),
            ("CrowdUnitType", 3),
        ]

        def character_row(
            unit_id: str,
            folder: str,
            skin: str,
            animation: str,
            class_id: int,
            script: str,
            second_job: int,
            info: str,
            troop_type: int,
        ) -> list[int | str]:
            return [
                unit_id,
                folder,
                skin,
                2,
                animation,
                class_id,
                35,
                script,
                second_job,
                info,
                180,
                troop_type,
                200,
                95,
                105,
                4,
                1,
                2,
                3,
                4,
                1,
                1,
                1,
                100,
                4,
            ]

        character = build_sox(
            character_columns,
            [
                character_row(
                    "C_TEST1_OH",
                    "char\\C_TEST1\\",
                    "C_TEST1",
                    "C_TEST1_OH.ba",
                    0,
                    "C_TEST1_OH.as",
                    -1,
                    "C_TEST1_OH.info",
                    2,
                ),
                character_row(
                    "C_TEST1_AR",
                    "char\\C_TEST1\\",
                    "C_TEST1",
                    "C_TEST1_AR.ba",
                    3,
                    "C_TEST1_AR.as",
                    0,
                    "C_TEST1_AR.info",
                    3,
                ),
                character_row(
                    "C_TWIN",
                    "char\\C_TWIN\\",
                    "C_TWIN",
                    "C_TWIN.ba",
                    0,
                    "C_TWIN.as",
                    -1,
                    "C_TWIN.info",
                    2,
                ),
                character_row(
                    "C_LP_KM",
                    "char\\C_LP_KM\\",
                    "C_LP_KM",
                    "C_LP_KM.ba",
                    1001,
                    "C_LP_KM.as",
                    -1,
                    "C_LP_KM.info",
                    2,
                ),
                character_row(
                    "noname",
                    "noname",
                    "noname",
                    "noname",
                    0,
                    "noname",
                    -1,
                    "noname",
                    2,
                ),
            ],
        )
        hero = build_sox([("UnitName", 1)], [[b"C_LP_KM"]])
        stat_entries = []
        for table_name in gameplay.NPC_STAT_PROFILE_TABLES:
            stat_entries.append(
                (
                    table_name,
                    build_sox(
                        [("UnitName", 1), ("Value1", 3)],
                        [
                            [b"C_TEST1_OH", 10],
                            [b"C_TEST1_AR", 20],
                            [b"C_TWIN", 10],
                            [b"C_LP_KM", 99],
                            [b"noname", 0],
                        ],
                    ),
                )
            )
        (self.packed / "res_init.pak").write_bytes(
            build_pak(
                [
                    ("CHARDATA.SOX", character),
                    ("HEROTABLE.SOX", hero),
                    *stat_entries,
                ],
                wrapped=True,
            )
        )
        program = CompiledAiTests.program_payload("C_TEST1_AR_Default.ai")
        module = CompiledAiTests.module_payload()
        (self.packed / "test_res2_res.pak").write_bytes(
            build_pak(
                [
                    ("C_TEST1_AR_DEFAULT.AIB", program),
                    ("TROOPCOMMAND.AI_FUNCB", module),
                    ("C_TEST1_AR.as", b"attack script"),
                    ("C_TEST1_AR.info", b"unit info"),
                ],
                wrapped=True,
            )
        )

        data = gameplay.load_game_data(self.game)
        profiles = {profile.unit_id: profile for profile in data.npc_profiles()}
        self.assertEqual(set(profiles), {
            "C_TEST1_OH",
            "C_TEST1_AR",
            "C_TWIN",
        })
        archer = profiles["C_TEST1_AR"]
        self.assertEqual(archer.class_name, "Archer")
        self.assertEqual(archer.second_job_index, 0)
        self.assertEqual(archer.second_job_target, "C_TEST1_OH")
        self.assertEqual(archer.second_job_target_row_id, 1)
        self.assertIn("C_TEST1_OH", archer.naming_family_peers)
        self.assertTrue(
            any(
                shared.field == "unit folder"
                and shared.peers == ("C_TEST1_OH",)
                for shared in archer.shared_resources
            )
        )
        self.assertEqual(
            profiles["C_TEST1_OH"].identical_stat_peers,
            ("C_TWIN",),
        )
        self.assertIsNotNone(archer.ai_program)
        self.assertEqual(
            archer.attack_script_name,
            "C_TEST1_AR.as",
        )
        self.assertEqual(len(archer.function_modules), 1)

        guides = {guide.key: guide for guide in data.npc_field_guides()}
        self.assertEqual(guides["unit type"].observed_values, (0, 3))
        self.assertEqual(guides["Weight"].observed_values, (100,))
        self.assertIn(
            "Retail NPC values",
            guides["unit type"].tooltip_text("3"),
        )

    def test_validates_synthetic_corpus(self) -> None:
        packed_table = build_sox([("Value", 3)], [[10]])
        loose_table = build_sox([("Name", 1)], [[b"test"]])
        (self.packed / "one.pak").write_bytes(
            build_pak(
                [
                    ("A.SOX", packed_table),
                    ("copy.bin", b"same"),
                    ("copy.bin", b"same"),
                ],
                wrapped=True,
            )
        )
        (self.packed / "two.pak").write_bytes(
            build_pak([("B.SOX", packed_table)], wrapped=False)
        )
        loose_path = self.game / "data" / "loose.sox"
        loose_path.write_bytes(loose_table)

        report = gameplay.validate_corpus(self.game)
        self.assertEqual(report["archives"], 2)
        self.assertEqual(report["wrappedArchives"], 1)
        self.assertEqual(report["rawArchives"], 1)
        self.assertEqual(report["members"], 4)
        self.assertEqual(report["duplicateArchives"], 1)
        self.assertEqual(report["duplicateExtraRecords"], 1)
        self.assertEqual(report["nonidenticalDuplicateNames"], 0)
        self.assertEqual(report["packedSoxTables"], 2)
        self.assertEqual(report["looseSoxTables"], 1)
        self.assertEqual(report["uniqueSoxContents"], 2)


if __name__ == "__main__":
    unittest.main()
