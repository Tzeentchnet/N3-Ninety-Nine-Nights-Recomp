#!/usr/bin/env python3
"""Bounded read-only readers and view models for N3 gameplay data."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import struct
from typing import Callable, Iterable
import zlib


PAK_OUTER_HEADER_SIZE = 0x800
PAK_ENTRY_SIZE = 268
PAK_NAME_SIZE = 256
PAK_ALIGNMENT = 0x800
SOX_DESCRIPTOR_COUNT = 128
SOX_DESCRIPTOR_SIZE = 68
SOX_ROW_DATA_OFFSET = 0x220C
SOX_FOOTER = b"THEND"
MAX_ARCHIVE_SIZE = 512 * 1024 * 1024
MAX_PAK_MEMBERS = 1_000_000
MAX_SOX_ROWS = 1_000_000
MAX_COMPILED_AI_RESOURCE_SIZE = 16 * 1024 * 1024
MAX_COMPILED_AI_STRING_SIZE = 1024

AI_RESOURCE_SUFFIXES = (".aib", ".ai_funcb", ".as", ".info")
AI_STAGE_EXTRA_ARCHIVES = (
    "ev_ty_res3_res.pak",
    "vf_in2_res3_res.pak",
    "vz_dw2_res3_res.pak",
)

UNIT_CLASS_NAMES = {
    -1: "Unknown",
    0: "Unit",
    1: "Flying unit",
    2: "Horse",
    3: "Archer",
    4: "Catapult",
    5: "Moving tower",
    6: "Adjutant",
    1000: "Hero",
    1001: "Hero Aspharr",
    1002: "Hero Inphy",
    1003: "Hero Klarrann",
    1004: "Hero Vigk Vagk",
    1005: "Hero Myifee",
    1006: "Hero Dwingvatt",
    1007: "Hero Tyurru",
}

NPC_SHARED_RESOURCE_FIELDS = (
    ("unit folder", "Unit folder"),
    ("skin name", "Skin"),
    ("ani name", "Animation"),
    ("AS file", "Attack script"),
    ("Parts file", "Unit-info file"),
)

NPC_STAT_PROFILE_TABLES = (
    "ATTACKTABLE.SOX",
    "DEFENSETABLE.SOX",
    "HPTABLE.SOX",
    "CRITICALTABLE.SOX",
    "ORBTABLE.SOX",
    "DEFENSEPROBTABLE.SOX",
    "LEVELMATCHINGTABLE.SOX",
)

EXPECTED_XEX_SHA256 = (
    "0fe8973b6ff45d3f8bd03a51a8c0d8cdf278b3d43e793497777e075f4e94a804"
)

CORE_TABLES = {
    "CHARDATA.SOX": (
        "Units",
        "Unit definitions, resource identities, scale, level limits, and physical metadata.",
    ),
    "ATTACKTABLE.SOX": (
        "Combat curves",
        "Enemy and friendly attack curves.",
    ),
    "DEFENSETABLE.SOX": (
        "Combat curves",
        "Enemy and friendly defense curves plus True Orb attenuation.",
    ),
    "HPTABLE.SOX": (
        "Combat curves",
        "Enemy and friendly HP curves.",
    ),
    "CRITICALTABLE.SOX": (
        "Combat curves",
        "Critical values and ratios. Duplicate raw headings are retained.",
    ),
    "ORBTABLE.SOX": (
        "Combat curves",
        "Orb Spark and experience values.",
    ),
    "DEFENSEPROBTABLE.SOX": (
        "Combat curves",
        "Enemy, friendly, and hero defense probabilities.",
    ),
    "LEVELMATCHINGTABLE.SOX": (
        "Combat curves",
        "Unit level-matching slots.",
    ),
    "HEROTABLE.SOX": (
        "Heroes",
        "Hero movement, slots, Orb use, guard stats, troop limits, and range.",
    ),
    "TROOPTABLE.SOX": (
        "Troops",
        "Troop range progression and movement values.",
    ),
    "ITEMTABLE.SOX": (
        "Items",
        "Item effects, values, restrictions, conditions, and type.",
    ),
    "ITEMLEVELTABLE.SOX": (
        "Items",
        "Item availability by unit level.",
    ),
    "ITEMDROPTABLE.SOX": (
        "Items",
        "Item-drop probabilities and item IDs. Duplicate raw headings are retained.",
    ),
    "ITEMSETTABLE.SOX": (
        "Items",
        "Item-set composition and set effects.",
    ),
}

PLAYABLE_SUFFIXES = {
    "as": "Aspharr",
    "in": "Inphyy",
    "ty": "Tyurru",
    "kl": "Klarrann",
    "my": "Myifee",
    "vi": "Vigk Vagk",
    "dw": "Dwingvatt",
}

PLAYABLE_UNIT_NAMES = {
    "C_LP_KM": "Aspharr",
    "C_LP_KF": "Inphyy",
    "C_LP_MF": "Tyurru",
    "C_LP_PM": "Klarrann",
    "C_LP_WM": "Myifee",
    "C_DP_TR": "Vigk Vagk",
    "C_DP_GB": "Dwingvatt",
}

LANGUAGE_ENCODINGS = {
    "ENG": "cp1252",
    "FRA": "cp1252",
    "GER": "cp1252",
    "ITA": "cp1252",
    "SPA": "cp1252",
    "JPN": "cp932",
    "KOR": "cp949",
    "CHN": "gb18030",
    "TCH": "big5",
}


class GameplayDataError(RuntimeError):
    """Raised when an owned game-data input is missing or malformed."""


@dataclass(frozen=True)
class PakMember:
    index: int
    name: str
    offset: int
    size: int


@dataclass
class PakArchive:
    path: Path
    wrapped: bool
    payload: bytes
    members: tuple[PakMember, ...]
    compressed_size: int

    def read_member(self, member: PakMember) -> bytes:
        return self.payload[member.offset : member.offset + member.size]

    def find(self, name: str) -> tuple[PakMember, ...]:
        folded = name.casefold()
        return tuple(member for member in self.members if member.name.casefold() == folded)

    @property
    def duplicate_extra_count(self) -> int:
        counts = Counter(member.name.casefold() for member in self.members)
        return sum(count - 1 for count in counts.values() if count > 1)


@dataclass(frozen=True)
class SoxColumn:
    name: str
    type_code: int


SoxValue = int | bytes


@dataclass(frozen=True)
class SoxRow:
    row_id: int
    values: tuple[SoxValue, ...]


@dataclass(frozen=True)
class SoxTable:
    source_name: str
    key: int
    columns: tuple[SoxColumn, ...]
    rows: tuple[SoxRow, ...]
    footer_size: int
    byte_size: int
    sha256: str

    def column_indices(self, name: str) -> tuple[int, ...]:
        folded = name.casefold()
        return tuple(
            index
            for index, column in enumerate(self.columns)
            if column.name.casefold() == folded
        )

    def column_index(self, name: str, occurrence: int = 0) -> int:
        indices = self.column_indices(name)
        if occurrence < 0 or occurrence >= len(indices):
            raise GameplayDataError(
                f"{self.source_name} has no column {name!r} occurrence {occurrence + 1}"
            )
        return indices[occurrence]


@dataclass(frozen=True)
class TableSource:
    id: str
    name: str
    origin: str
    category: str
    description: str
    encoding: str | None
    table: SoxTable


@dataclass(frozen=True)
class BuildVerification:
    status: str
    expected_sha256: str
    actual_sha256: str | None
    message: str


@dataclass(frozen=True)
class VariantVerification:
    archive: str
    status: str
    matched_tables: int
    expected_tables: int
    details: str


@dataclass(frozen=True)
class UnitRecord:
    row: SoxRow
    unit_id: str
    display_name: str
    tables: tuple[tuple[TableSource, SoxRow], ...]


@dataclass(frozen=True)
class ItemRecord:
    row: SoxRow
    name: str
    description: str


@dataclass(frozen=True)
class AbilityRecord:
    character: str
    level: int
    name: str
    command: str
    caption: str
    row_id: int
    source: str


@dataclass(frozen=True)
class FieldGuide:
    key: str
    label: str
    source: str
    description: str
    units: str
    evidence: str
    known_limits: str
    observed_values: tuple[int, ...]
    population_label: str = "Retail hero values"

    @property
    def observed_range(self) -> tuple[int, int] | None:
        if not self.observed_values:
            return None
        return self.observed_values[0], self.observed_values[-1]

    @property
    def observed_summary(self) -> str:
        values = self.observed_values
        if not values:
            return "not available"
        if len(values) == 1:
            return str(values[0])
        if all(right == left + 1 for left, right in zip(values, values[1:])):
            return f"{values[0]}..{values[-1]}"
        if len(values) <= 14:
            return ", ".join(map(str, values))
        return f"{values[0]}..{values[-1]} ({len(values)} distinct values)"

    def tooltip_text(self, current_value: str | None = None) -> str:
        lines = [
            self.label,
            self.description,
            f"Source: {self.source}",
        ]
        if current_value not in {None, ""}:
            lines.append(f"Current value: {current_value}")
        lines.extend(
            (
                f"Units: {self.units}",
                f"{self.population_label}: {self.observed_summary}",
                f"Known limits: {self.known_limits}",
                f"Evidence: {self.evidence}",
            )
        )
        return "\n".join(lines)


@dataclass(frozen=True)
class CompiledResource:
    name: str
    kind: str
    sha256: str
    archives: tuple[str, ...]
    occurrences: int


@dataclass(frozen=True)
class AiProgram:
    resource: CompiledResource
    source_path: str
    included_functions: tuple[str, ...]
    called_functions: tuple[str, ...]
    level_branch_count: int

    @property
    def unique_called_functions(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(self.called_functions))


@dataclass(frozen=True)
class AiFunctionModule:
    resource: CompiledResource
    source_path: str
    parameters: tuple[str, ...]


@dataclass(frozen=True)
class CompiledResourceIndex:
    archive_count: int
    resources: tuple[CompiledResource, ...]
    programs: tuple[AiProgram, ...]
    function_modules: tuple[AiFunctionModule, ...]

    def find_resource(self, name: str) -> CompiledResource | None:
        folded = name.casefold()
        return next(
            (resource for resource in self.resources if resource.name.casefold() == folded),
            None,
        )

    def find_program(self, name: str) -> AiProgram | None:
        folded = name.casefold()
        return next(
            (
                program
                for program in self.programs
                if program.resource.name.casefold() == folded
            ),
            None,
        )

    def find_function_module(self, name: str) -> AiFunctionModule | None:
        stem = _compiled_resource_stem(name)
        return next(
            (
                module
                for module in self.function_modules
                if _compiled_resource_stem(module.resource.name) == stem
            ),
            None,
        )


@dataclass(frozen=True)
class SharedUnitResource:
    field: str
    label: str
    value: str
    peers: tuple[str, ...]


@dataclass(frozen=True)
class NpcProfile:
    unit_id: str
    row_id: int
    class_id: int | None
    class_name: str
    second_job_index: int | None
    second_job_target: str | None
    second_job_target_row_id: int | None
    naming_family_peers: tuple[str, ...]
    shared_resources: tuple[SharedUnitResource, ...]
    identical_stat_peers: tuple[str, ...]
    expected_ai_program: str
    ai_program: AiProgram | None
    attack_script_name: str
    attack_script: CompiledResource | None
    unit_info_name: str
    unit_info: CompiledResource | None
    function_modules: tuple[AiFunctionModule, ...]


@dataclass(frozen=True)
class _FieldGuideSpec:
    key: str
    label: str
    table_name: str
    prefix: str
    field_count: int
    description: str
    units: str
    evidence: str
    known_limits: str


@dataclass(frozen=True)
class _NpcFieldGuideSpec:
    field: str
    label: str
    description: str
    units: str
    evidence: str
    known_limits: str


_HERO_FIELD_SPECS = (
    _FieldGuideSpec(
        "speed",
        "Movement-speed scale",
        "HEROTABLE.SOX",
        "MoveSpeed",
        9,
        "Base movement-speed scale for the selected hero level.",
        "percentage-like scale; 100 is the retail baseline",
        "Field name, 100-based hero progression, and percentage-point movement item bonuses.",
        "Retail values only; no runtime-safe minimum or maximum is established.",
    ),
    _FieldGuideSpec(
        "slots",
        "Accessory slots",
        "HEROTABLE.SOX",
        "SlotCount",
        9,
        "Number of accessory slots unlocked at the selected hero level. The weapon slot is separate.",
        "slot count",
        "Field name plus five separate accessory controls in the shipped status UI.",
        "Retail and UI-supported domain is 1..5 accessory slots.",
    ),
    _FieldGuideSpec(
        "orb",
        "Orb decrease",
        "HEROTABLE.SOX",
        "OrbDecrease",
        9,
        "Base Orb gauge decrease or consumption scalar. The exact formula and direction remain untraced.",
        "unknown; the shipped value resembles a 100-based scalar",
        "Field name and retail values; no translated-code ownership has been established.",
        "Every shipped hero value is 100. Other values are untested.",
    ),
    _FieldGuideSpec(
        "guard_def",
        "Guard defense",
        "HEROTABLE.SOX",
        "GuardianDefense",
        9,
        "Base defense stat for the hero's accompanying guard units.",
        "integer base stat",
        "Field name and independently described percentage modifiers for Guard defense.",
        "Observed retail range only; no runtime-safe upper bound is established.",
    ),
    _FieldGuideSpec(
        "guard_hp",
        "Guard maximum HP",
        "HEROTABLE.SOX",
        "GuardianHP",
        9,
        "Base maximum-HP stat for the hero's guard force. Per-unit versus shared-pool ownership is untraced.",
        "HP points",
        "Field name and independently described Guard maximum-HP item modifiers.",
        "Observed retail range only; no runtime-safe upper bound is established.",
    ),
    _FieldGuideSpec(
        "troops",
        "Controllable troop groups",
        "HEROTABLE.SOX",
        "GuardianControlTroopCount",
        9,
        "Number of guard groups that can be controlled independently.",
        "group count",
        "Field name plus separate left and right Guardian screens and controls.",
        "Retail and UI-supported domain is 1 or 2 groups.",
    ),
    _FieldGuideSpec(
        "units",
        "Guard units per group",
        "HEROTABLE.SOX",
        "GuardianControlTroopUnitCount",
        9,
        "Number of guard units assigned to each controllable troop group.",
        "units per group",
        "Field name and the value reset that accompanies unlocking a second group.",
        "Observed retail values only; allocation and engine-safe bounds are untraced.",
    ),
    _FieldGuideSpec(
        "range",
        "Innate attack-range bonus",
        "HEROTABLE.SOX",
        "AttackRange",
        9,
        "Innate attack-range bonus granted by hero progression.",
        "percentage points",
        "Field name and matching percentage-point attack-range item modifiers.",
        "The innate retail range is not an engine cap; item modifiers exceed it.",
    ),
)

_HERO_CURVE_SPECS = (
    _FieldGuideSpec(
        "atk_e",
        "Enemy-side attack",
        "ATTACKTABLE.SOX",
        "Attack_enemy",
        11,
        "Base attack curve when this unit uses the enemy-side stat branch.",
        "integer base stat",
        "Direct table and field naming; all seven playable rows share this enemy branch.",
        "Observed retail values only; runtime branch selection and edit bounds are untraced.",
    ),
    _FieldGuideSpec(
        "atk_f",
        "Friendly-side attack",
        "ATTACKTABLE.SOX",
        "Attack_friend",
        11,
        "Base attack curve for the friendly-side branch, which is character-specific for playable units.",
        "integer base stat",
        "Direct table and field naming plus character-specific playable-row values.",
        "Likely player/ally-facing, but runtime branch ownership and safe bounds are untraced.",
    ),
    _FieldGuideSpec(
        "def_e",
        "Enemy-side defense",
        "DEFENSETABLE.SOX",
        "Defense_enemy",
        11,
        "Base defense curve when this unit uses the enemy-side stat branch.",
        "integer base stat",
        "Direct table and field naming.",
        "Observed retail values only; runtime branch selection and edit bounds are untraced.",
    ),
    _FieldGuideSpec(
        "def_f",
        "Friendly-side defense",
        "DEFENSETABLE.SOX",
        "Defense_friend",
        11,
        "Base defense curve for the friendly-side stat branch.",
        "integer base stat",
        "Direct table and field naming.",
        "Likely player/ally-facing, but runtime branch ownership and safe bounds are untraced.",
    ),
    _FieldGuideSpec(
        "hp_e",
        "Enemy-side HP",
        "HPTABLE.SOX",
        "HP_enemy",
        11,
        "Maximum-HP curve when this unit uses the enemy-side stat branch.",
        "HP points",
        "Direct table and field naming.",
        "Playable enemy-side tails include zero placeholders; observed extrema are not safe edit limits.",
    ),
    _FieldGuideSpec(
        "hp_f",
        "Friendly-side HP",
        "HPTABLE.SOX",
        "HP_friend",
        11,
        "Maximum-HP curve for the friendly-side branch.",
        "HP points",
        "Direct table and field naming plus character-specific playable-row values.",
        "Likely player/ally-facing, but runtime branch ownership and safe bounds are untraced.",
    ),
    _FieldGuideSpec(
        "crit_e",
        "Enemy-side critical value",
        "CRITICALTABLE.SOX",
        "Critical_enemy",
        11,
        "Critical-rate value for the enemy-side branch.",
        "percentage-like points",
        "Direct table and field naming and matching percentage-point critical item modifiers.",
        "Slots 10 and 11 are zero for playable rows; no safe edit range is established.",
    ),
    _FieldGuideSpec(
        "crit_f",
        "Friendly-side critical value",
        "CRITICALTABLE.SOX",
        "Critical_friend",
        11,
        "Critical-rate value for the friendly-side branch.",
        "percentage-like points",
        "Direct table and field naming and matching percentage-point critical item modifiers.",
        "Slots 10 and 11 are zero for playable rows; no safe edit range is established.",
    ),
    _FieldGuideSpec(
        "orb",
        "Orb Spark curve",
        "ORBTABLE.SOX",
        "OrbSpark",
        11,
        "Numeric Orb Spark progression curve, likely a blue-gauge threshold or capacity.",
        "unknown integer gauge units",
        "Field name and monotonic retail progression; the runtime formula is untraced.",
        "Observed retail values only; threshold versus capacity semantics remain inferred.",
    ),
    _FieldGuideSpec(
        "exp",
        "Unit EXP value",
        "ORBTABLE.SOX",
        "Exp",
        11,
        "EXP value associated with the unit curve. It is not the playable hero level-up threshold.",
        "EXP points",
        "All seven playable rows are zero while non-player units use this field.",
        "Every shipped playable-hero value is zero.",
    ),
    _FieldGuideSpec(
        "guard_e",
        "Enemy-side defense probability",
        "DEFENSEPROBTABLE.SOX",
        "DefenseProb_enemy",
        11,
        "Defense or block probability value for the enemy-side branch.",
        "percentage-like points",
        "Direct table and field naming.",
        "Observed retail values only; probability formula and safe bounds are untraced.",
    ),
    _FieldGuideSpec(
        "guard_f",
        "Friendly-side defense probability",
        "DEFENSEPROBTABLE.SOX",
        "DefenseProb_friend",
        11,
        "Defense or block probability value for the friendly-side branch.",
        "percentage-like points",
        "Direct table and field naming.",
        "Observed retail values only; probability formula and safe bounds are untraced.",
    ),
    _FieldGuideSpec(
        "guard_h",
        "Hero defense probability",
        "DEFENSEPROBTABLE.SOX",
        "DefenseProb_Hero",
        11,
        "Hero-specific defense or block probability value.",
        "percentage-like points",
        "Direct table and field naming.",
        "Observed retail values only; probability formula and safe bounds are untraced.",
    ),
    _FieldGuideSpec(
        "true_orb",
        "True Orb attenuation",
        "DEFENSETABLE.SOX",
        "TrueOrb_attenuation",
        11,
        "Attenuation scalar associated with True Orb or Orb Spark combat.",
        "unknown; percentage-like scalar",
        "Direct field naming; every shipped playable value is 65.",
        "Only 65 is observed for playable heroes; target and formula remain untraced.",
    ),
    _FieldGuideSpec(
        "match",
        "Level-matching result",
        "LEVELMATCHINGTABLE.SOX",
        "Level",
        12,
        "Maps each requested level slot to a stat-curve level.",
        "curve level index",
        "Playable rows map slots 1..9 directly and clamp slots 10..12 to level 9.",
        "A result must identify an available curve level; edited runtime behavior is untested.",
    ),
)

_NPC_FIELD_SPECS = (
    _NpcFieldGuideSpec(
        "unit type",
        "Runtime class ID",
        (
            "Selects the runtime unit class. Retained aidef.h names IDs 0..6 as "
            "Unit, Fly, Horse, Archer, Catapult, MoveTower, and Adjutant, with "
            "hero subclasses at 1000..1007."
        ),
        "GameObj_ClassID enum value",
        "The CHARDATA values exactly match the retained GameObj_ClassID enum.",
        "The enum domain is known, but changing an NPC to another runtime class is untested.",
    ),
    _NpcFieldGuideSpec(
        "troop type",
        "Troop category",
        (
            "Category used by troop range data and mission filters. Numeric labels "
            "have not been mapped to a complete retained enum."
        ),
        "unmapped troop-category ID",
        "Direct CHARDATA and TROOPTABLE field names plus trigger references to TroopType.",
        "Observed retail values only; do not substitute the unrelated TAI_PARAM enum.",
    ),
    _NpcFieldGuideSpec(
        "skin variation num",
        "Skin variation count",
        "Count-like selector associated with the unit's skin resource.",
        "variation count",
        "Direct field name and correlation with shared skin families.",
        "Observed retail values only; zero and out-of-range behavior are untested.",
    ),
    _NpcFieldGuideSpec(
        "unit size",
        "Unit size",
        "Horizontal size or collision-scale metadata; exact runtime consumers are untraced.",
        "unknown engine spatial units",
        "Direct field name and larger retail values on physically larger unit classes.",
        "Observed retail values only; no safe collision or rendering bounds are known.",
    ),
    _NpcFieldGuideSpec(
        "Unit Height",
        "Unit height",
        "Vertical unit dimension metadata; exact collision and targeting use is untraced.",
        "unknown engine spatial units",
        "Direct field name and unit-specific retail values.",
        "Observed retail values only; no safe runtime bounds are known.",
    ),
    _NpcFieldGuideSpec(
        "billboard size",
        "Billboard size",
        "Size metadata for the optional distant-unit billboard representation.",
        "unknown rendering units",
        "Direct field name and correlation with billboard resource fields.",
        "Zero is valid for units without a named billboard; other edit bounds are unknown.",
    ),
    _NpcFieldGuideSpec(
        "unit min scale",
        "Minimum spawn scale",
        "Lower endpoint of the per-unit retail scale-variation interval.",
        "percentage-like scale; 100 is baseline",
        "Paired min/max field names, 100-centered values, and min <= max for every retail NPC.",
        "Observed retail values only; negative, zero, and extreme scales are untested.",
    ),
    _NpcFieldGuideSpec(
        "unit max scale",
        "Maximum spawn scale",
        "Upper endpoint of the per-unit retail scale-variation interval.",
        "percentage-like scale; 100 is baseline",
        "Paired min/max field names, 100-centered values, and min <= max for every retail NPC.",
        "Must remain at least the minimum for the observed relationship; engine limits are unknown.",
    ),
    _NpcFieldGuideSpec(
        "MaxLevel",
        "Configured unit level ceiling",
        (
            "Highest configured stat-curve level for tiered NPC definitions. It is "
            "not the nine-level playable-hero progression cap."
        ),
        "curve level",
        "Direct field name plus the four nondecreasing A/B/C/D level-offset patterns.",
        "Observed NPC values are not proven writer bounds or mission difficulty levels.",
    ),
    _NpcFieldGuideSpec(
        "A_LevelOffset",
        "A tier level",
        "First of four nondecreasing NPC level-tier selectors.",
        "curve level",
        "All 86 named retail NPC rows satisfy A <= B <= C <= D.",
        "The A/B/C/D selector owner is untraced; observed values only.",
    ),
    _NpcFieldGuideSpec(
        "B_LevelOffset",
        "B tier level",
        "Second of four nondecreasing NPC level-tier selectors.",
        "curve level",
        "All 86 named retail NPC rows satisfy A <= B <= C <= D.",
        "The A/B/C/D selector owner is untraced; observed values only.",
    ),
    _NpcFieldGuideSpec(
        "C_LevelOffset",
        "C tier level",
        "Third of four nondecreasing NPC level-tier selectors.",
        "curve level",
        "All 86 named retail NPC rows satisfy A <= B <= C <= D.",
        "The A/B/C/D selector owner is untraced; observed values only.",
    ),
    _NpcFieldGuideSpec(
        "D_LevelOffset",
        "D tier level",
        "Fourth and highest of four nondecreasing NPC level-tier selectors.",
        "curve level",
        "All 86 named retail NPC rows satisfy A <= B <= C <= D.",
        "The A/B/C/D selector owner is untraced; observed values only.",
    ),
    _NpcFieldGuideSpec(
        "Use Level",
        "Use configured level",
        "Boolean-like switch associated with MaxLevel and the four level-tier fields.",
        "0 or 1 flag",
        "Only 0 and 1 occur in named retail NPC definitions.",
        "The runtime branch and mission override behavior remain untraced.",
    ),
    _NpcFieldGuideSpec(
        "SoundAmor",
        "Armor-sound selector",
        "Numeric armor-impact sound selector. The source field retains the shipped spelling.",
        "unmapped sound ID",
        "Direct CHARDATA field name and small enum-like retail domain.",
        "-1 is a retail sentinel; sound-bank ownership and safe substitutions are unknown.",
    ),
    _NpcFieldGuideSpec(
        "SoundWeapon",
        "Weapon-sound selector",
        "Numeric weapon-impact sound selector.",
        "unmapped sound ID",
        "Direct CHARDATA field name and small enum-like retail domain.",
        "-1 is a retail sentinel; sound-bank ownership and safe substitutions are unknown.",
    ),
    _NpcFieldGuideSpec(
        "Weight",
        "Weight",
        "Weight-like physics or reaction scalar; the exact formula is untraced.",
        "unknown; 100-based scalar is plausible",
        "Direct field name; every named retail NPC uses 100.",
        "Only 100 is observed, so direction and safe alternatives are unknown.",
    ),
    _NpcFieldGuideSpec(
        "CrowdUnitType",
        "Crowd unit type",
        "Numeric category paired with the named crowd/voice resource field.",
        "unmapped crowd-category ID",
        "Direct field name and correlation with crowd resource names.",
        "Observed retail values only; the category enum is not independently named.",
    ),
    _NpcFieldGuideSpec(
        "Second Job Index",
        "Explicit job-row link",
        (
            "A nonnegative value is a zero-based CHARDATA row position. All five "
            "retail links resolve to a related combat-job row."
        ),
        "zero-based CHARDATA row index; -1 means no link",
        (
            "All five nonnegative retail values resolve exactly, including "
            "C_DS_GBC to C_DS_GBC_OH; retained AI has a first/second-job condition."
        ),
        "Use -1 or a valid row position structurally; runtime-safe retargeting is untested.",
    ),
)


def unit_class_name(class_id: int | None) -> str:
    if class_id is None:
        return "Unavailable"
    return UNIT_CLASS_NAMES.get(class_id, f"Unmapped class {class_id}")


def _npc_family_key(unit_id: str) -> str:
    stem = re.sub(r"_(?:OH|SP|TH|AR)$", "", unit_id, flags=re.IGNORECASE)
    return re.sub(r"\d+$", "#", stem).casefold()


def _compiled_resource_stem(name: str) -> str:
    stem = name.replace("\\", "/").rsplit("/", 1)[-1].casefold()
    for suffix in (".ai_funcb", ".ai_func", ".aib", ".as", ".info"):
        if stem.endswith(suffix):
            return stem[: -len(suffix)]
    return stem


@dataclass
class GameData:
    game_root: Path
    build: BuildVerification
    archive_name: str
    archive_wrapped: bool
    archive_member_count: int
    archive_duplicate_extra_count: int
    tables: tuple[TableSource, ...]
    variants: tuple[VariantVerification, ...]
    compiled_resources: CompiledResourceIndex
    warnings: tuple[str, ...]

    def table_source(self, name: str) -> TableSource | None:
        folded = name.casefold()
        packed = [
            source
            for source in self.tables
            if source.name.casefold() == folded and source.origin.startswith("PackedResources/")
        ]
        if packed:
            return packed[0]
        return next(
            (source for source in self.tables if source.name.casefold() == folded),
            None,
        )

    def units(self) -> tuple[UnitRecord, ...]:
        character_source = self.table_source("CHARDATA.SOX")
        if character_source is None:
            return ()

        hero_source = self.table_source("HEROTABLE.SOX")
        hero_ids = (
            {
                display_value(row.values[0], hero_source.encoding)
                for row in hero_source.table.rows
                if row.values
            }
            if hero_source
            else set()
        )

        related_names = (
            "ATTACKTABLE.SOX",
            "DEFENSETABLE.SOX",
            "HPTABLE.SOX",
            "CRITICALTABLE.SOX",
            "ORBTABLE.SOX",
            "DEFENSEPROBTABLE.SOX",
            "LEVELMATCHINGTABLE.SOX",
            "ITEMLEVELTABLE.SOX",
            "HEROTABLE.SOX",
        )
        related: list[tuple[TableSource, dict[str, SoxRow]]] = []
        for name in related_names:
            source = self.table_source(name)
            if source is None:
                continue
            by_unit: dict[str, SoxRow] = {}
            for row in source.table.rows:
                if not row.values:
                    continue
                by_unit[display_value(row.values[0], source.encoding)] = row
            related.append((source, by_unit))

        units: list[UnitRecord] = []
        for row in character_source.table.rows:
            unit_id = display_value(row.values[0], character_source.encoding)
            linked = tuple(
                (source, rows[unit_id])
                for source, rows in related
                if unit_id in rows
            )
            units.append(
                UnitRecord(
                    row=row,
                    unit_id=unit_id,
                    display_name=(
                        PLAYABLE_UNIT_NAMES.get(unit_id, unit_id)
                        if unit_id in hero_ids
                        else unit_id
                    ),
                    tables=linked,
                )
            )
        return tuple(units)

    def npc_profiles(self) -> tuple[NpcProfile, ...]:
        character_source = self.table_source("CHARDATA.SOX")
        if character_source is None:
            return ()

        units = self.units()
        rows = character_source.table.rows
        hero_ids = set(PLAYABLE_UNIT_NAMES)
        hero_source = self.table_source("HEROTABLE.SOX")
        if hero_source is not None:
            hero_ids.update(
                display_value(row.values[0], hero_source.encoding)
                for row in hero_source.table.rows
                if row.values
            )
        npc_units = tuple(
            unit
            for unit in units
            if unit.unit_id not in hero_ids and unit.unit_id.casefold() != "noname"
        )

        def value(row: SoxRow, field: str) -> SoxValue | None:
            indices = character_source.table.column_indices(field)
            return row.values[indices[0]] if indices else None

        def text(row: SoxRow, field: str) -> str:
            field_value = value(row, field)
            return (
                display_value(field_value, character_source.encoding)
                if field_value is not None
                else ""
            )

        def number(row: SoxRow, field: str) -> int | None:
            field_value = value(row, field)
            return field_value if isinstance(field_value, int) else None

        family_groups: defaultdict[str, list[str]] = defaultdict(list)
        for unit in npc_units:
            family_groups[_npc_family_key(unit.unit_id)].append(unit.unit_id)

        shared_groups: dict[str, defaultdict[str, list[str]]] = {}
        for field, _label in NPC_SHARED_RESOURCE_FIELDS:
            groups: defaultdict[str, list[str]] = defaultdict(list)
            for unit in npc_units:
                resource_value = text(unit.row, field)
                if resource_value and resource_value.casefold() != "noname":
                    groups[resource_value.casefold()].append(unit.unit_id)
            shared_groups[field] = groups

        stat_groups: defaultdict[tuple[object, ...], list[str]] = defaultdict(list)
        stat_fingerprints: dict[str, tuple[object, ...]] = {}
        stat_sources = tuple(
            self.table_source(table_name) for table_name in NPC_STAT_PROFILE_TABLES
        )
        if all(source is not None for source in stat_sources):
            stat_rows: list[dict[str, SoxRow]] = []
            for source in stat_sources:
                assert source is not None
                stat_rows.append(
                    {
                        display_value(row.values[0], source.encoding): row
                        for row in source.table.rows
                        if row.values
                    }
                )
            for unit in npc_units:
                if not all(unit.unit_id in by_unit for by_unit in stat_rows):
                    continue
                fingerprint = tuple(
                    (
                        NPC_STAT_PROFILE_TABLES[index],
                        stat_rows[index][unit.unit_id].values[1:],
                    )
                    for index in range(len(NPC_STAT_PROFILE_TABLES))
                )
                stat_fingerprints[unit.unit_id] = fingerprint
                stat_groups[fingerprint].append(unit.unit_id)

        profiles = []
        for unit in npc_units:
            second_job_index = number(unit.row, "Second Job Index")
            target_id = None
            target_row_id = None
            if second_job_index is not None and second_job_index >= 0:
                if second_job_index >= len(rows):
                    raise GameplayDataError(
                        f"CHARDATA.SOX row {unit.row.row_id} {unit.unit_id!r} "
                        f"has out-of-range Second Job Index {second_job_index}"
                    )
                target_row = rows[second_job_index]
                target_id = display_value(
                    target_row.values[0], character_source.encoding
                )
                target_row_id = target_row.row_id

            shared = []
            for field, label in NPC_SHARED_RESOURCE_FIELDS:
                resource_value = text(unit.row, field)
                peers = tuple(
                    peer
                    for peer in shared_groups[field].get(
                        resource_value.casefold(), ()
                    )
                    if peer != unit.unit_id
                )
                if peers:
                    shared.append(
                        SharedUnitResource(
                            field=field,
                            label=label,
                            value=resource_value,
                            peers=peers,
                        )
                    )

            fingerprint = stat_fingerprints.get(unit.unit_id)
            stat_peers = (
                tuple(
                    peer
                    for peer in stat_groups[fingerprint]
                    if peer != unit.unit_id
                )
                if fingerprint is not None
                else ()
            )
            family_peers = tuple(
                peer
                for peer in family_groups[_npc_family_key(unit.unit_id)]
                if peer != unit.unit_id
            )

            expected_ai = f"{unit.unit_id}_DEFAULT.AIB"
            program = self.compiled_resources.find_program(expected_ai)
            attack_script_name = text(unit.row, "AS file")
            unit_info_name = text(unit.row, "Parts file")
            modules = []
            if program is not None:
                for function_name in program.included_functions:
                    module = self.compiled_resources.find_function_module(
                        function_name
                    )
                    if module is not None and module not in modules:
                        modules.append(module)

            class_id = number(unit.row, "unit type")
            profiles.append(
                NpcProfile(
                    unit_id=unit.unit_id,
                    row_id=unit.row.row_id,
                    class_id=class_id,
                    class_name=unit_class_name(class_id),
                    second_job_index=second_job_index,
                    second_job_target=target_id,
                    second_job_target_row_id=target_row_id,
                    naming_family_peers=family_peers,
                    shared_resources=tuple(shared),
                    identical_stat_peers=stat_peers,
                    expected_ai_program=expected_ai,
                    ai_program=program,
                    attack_script_name=attack_script_name,
                    attack_script=self.compiled_resources.find_resource(
                        attack_script_name
                    ),
                    unit_info_name=unit_info_name,
                    unit_info=self.compiled_resources.find_resource(
                        unit_info_name
                    ),
                    function_modules=tuple(modules),
                )
            )
        return tuple(profiles)

    def npc_field_guides(self) -> tuple[FieldGuide, ...]:
        character_source = self.table_source("CHARDATA.SOX")
        if character_source is None:
            return ()
        hero_ids = set(PLAYABLE_UNIT_NAMES)
        hero_source = self.table_source("HEROTABLE.SOX")
        if hero_source is not None:
            hero_ids.update(
                display_value(row.values[0], hero_source.encoding)
                for row in hero_source.table.rows
                if row.values
            )
        rows = tuple(
            row
            for row in character_source.table.rows
            if row.values
            and display_value(row.values[0], character_source.encoding)
            not in hero_ids
            and display_value(
                row.values[0], character_source.encoding
            ).casefold()
            != "noname"
        )

        guides = []
        for spec in _NPC_FIELD_SPECS:
            indices = character_source.table.column_indices(spec.field)
            if not indices:
                continue
            values = tuple(
                sorted(
                    {
                        row.values[indices[0]]
                        for row in rows
                        if isinstance(row.values[indices[0]], int)
                    }
                )
            )
            guides.append(
                FieldGuide(
                    key=spec.field,
                    label=spec.label,
                    source=f"CHARDATA.SOX / {spec.field}",
                    description=spec.description,
                    units=spec.units,
                    evidence=spec.evidence,
                    known_limits=spec.known_limits,
                    observed_values=values,
                    population_label="Retail NPC values",
                )
            )
        return tuple(guides)

    def hero_field_guides(self) -> tuple[FieldGuide, ...]:
        source = self.table_source("HEROTABLE.SOX")
        if source is None:
            return ()

        guides = [
            FieldGuide(
                key="level",
                label="Hero level",
                source="HEROTABLE.SOX / numbered fields 1..9",
                description="Playable-character progression level selecting each numbered hero field.",
                units="integer level",
                evidence="The table provides exactly nine fields in every hero progression family.",
                known_limits="Defined retail progression domain is level 1..9.",
                observed_values=tuple(range(1, 10)),
            )
        ]
        for spec in _HERO_FIELD_SPECS:
            guide = self._guide_from_spec(spec, source.table.rows)
            guides.append(guide)
            if spec.key == "units":
                totals = []
                for row in source.table.rows:
                    for level in range(1, 10):
                        group_value = self._numbered_value(
                            source, row, "GuardianControlTroopCount", level
                        )
                        unit_value = self._numbered_value(
                            source, row, "GuardianControlTroopUnitCount", level
                        )
                        if group_value is not None and unit_value is not None:
                            totals.append(group_value * unit_value)
                guides.append(
                    FieldGuide(
                        key="total_units",
                        label="Derived total guard units",
                        source=(
                            "HEROTABLE.SOX / GuardianControlTroopCountN x "
                            "GuardianControlTroopUnitCountN"
                        ),
                        description="Derived total capacity across all controllable guard groups.",
                        units="guard units",
                        evidence=(
                            "Arithmetic derivation from the two directly named troop fields; "
                            "runtime allocation is untraced."
                        ),
                        known_limits=(
                            "Display-only derived value; it is not a separate editable SOX field."
                        ),
                        observed_values=tuple(sorted(set(totals))),
                    )
                )
        return tuple(guides)

    def hero_curve_guides(self) -> tuple[FieldGuide, ...]:
        hero_source = self.table_source("HEROTABLE.SOX")
        if hero_source is None:
            return ()
        hero_ids = {
            display_value(row.values[0], hero_source.encoding)
            for row in hero_source.table.rows
            if row.values
        }
        guides = [
            FieldGuide(
                key="level",
                label="Curve slot",
                source="Core stat tables slots 1..11; LEVELMATCHINGTABLE.SOX slots 1..12",
                description=(
                    "Structural curve slot, not a confirmed playable-character level. "
                    "Only level matching has slot 12."
                ),
                units="slot index",
                evidence="Direct schema counts across the seven displayed core tables.",
                known_limits=(
                    "Stat curves define slots 1..11. Level matching alone defines slots 1..12."
                ),
                observed_values=tuple(range(1, 13)),
            )
        ]
        for spec in _HERO_CURVE_SPECS:
            source = self.table_source(spec.table_name)
            rows = ()
            if source is not None:
                rows = tuple(
                    row
                    for row in source.table.rows
                    if row.values
                    and display_value(row.values[0], source.encoding) in hero_ids
                )
            guides.append(self._guide_from_spec(spec, rows, source))
        return tuple(guides)

    @staticmethod
    def _numbered_value(
        source: TableSource,
        row: SoxRow,
        prefix: str,
        level: int,
    ) -> int | None:
        indices = source.table.column_indices(f"{prefix}{level}")
        if not indices:
            return None
        value = row.values[indices[0]]
        return value if isinstance(value, int) else None

    def _guide_from_spec(
        self,
        spec: _FieldGuideSpec,
        rows: Iterable[SoxRow],
        source: TableSource | None = None,
    ) -> FieldGuide:
        source = source or self.table_source(spec.table_name)
        values = []
        if source is not None:
            for row in rows:
                for level in range(1, spec.field_count + 1):
                    value = self._numbered_value(source, row, spec.prefix, level)
                    if value is not None:
                        values.append(value)
        return FieldGuide(
            key=spec.key,
            label=spec.label,
            source=(
                f"{spec.table_name} / {spec.prefix}1..{spec.field_count}"
            ),
            description=spec.description,
            units=spec.units,
            evidence=spec.evidence,
            known_limits=spec.known_limits,
            observed_values=tuple(sorted(set(values))),
        )

    def items(self) -> tuple[ItemRecord, ...]:
        item_source = self.table_source("ITEMTABLE.SOX")
        description_source = self.table_source("ITEMDESC_ENG.SOX")
        if item_source is None:
            return ()

        names: dict[int, tuple[str, str]] = {}
        if description_source is not None:
            name_index = description_source.table.column_index("Name")
            description_index = description_source.table.column_index("Desc")
            names = {
                row.row_id: (
                    display_value(row.values[name_index], description_source.encoding),
                    display_value(
                        row.values[description_index], description_source.encoding
                    ).replace("\\n", "\n"),
                )
                for row in description_source.table.rows
            }

        result = []
        for row in item_source.table.rows:
            localized = names.get(row.row_id)
            if localized is None:
                fallback = display_value(row.values[0], item_source.encoding)
                localized = (fallback, "")
            result.append(ItemRecord(row, localized[0], localized[1]))
        return tuple(result)

    def abilities(self, language: str = "ENG") -> tuple[AbilityRecord, ...]:
        language = language.upper()
        suffix = f"_{language.casefold()}.sox"
        marker = f"sox/{language.casefold()}/"
        records: list[AbilityRecord] = []
        for source in self.tables:
            origin_folded = source.origin.casefold()
            name_folded = source.name.casefold()
            if marker not in origin_folded or not name_folded.endswith(suffix):
                continue
            if not name_folded.startswith("abilitylocaltable_"):
                continue
            stem = name_folded.removeprefix("abilitylocaltable_").removesuffix(suffix)
            character = PLAYABLE_SUFFIXES.get(stem)
            if character is None:
                continue
            table = source.table
            level_index = table.column_index("_Level")
            name_index = table.column_index("_Name")
            command_index = table.column_index("_Command")
            caption_index = table.column_index("_Caption")
            for row in table.rows:
                records.append(
                    AbilityRecord(
                        character=character,
                        level=int(row.values[level_index]),
                        name=display_value(row.values[name_index], source.encoding),
                        command=display_value(
                            row.values[command_index], source.encoding
                        ),
                        caption=display_value(
                            row.values[caption_index], source.encoding
                        ),
                        row_id=row.row_id,
                        source=source.origin,
                    )
                )
        return tuple(
            sorted(
                records,
                key=lambda record: (
                    tuple(PLAYABLE_SUFFIXES.values()).index(record.character),
                    record.level,
                    record.row_id,
                ),
            )
        )

    def structural_report(self) -> dict[str, object]:
        resource_counts = Counter(
            resource.kind for resource in self.compiled_resources.resources
        )
        resource_instances = Counter()
        for resource in self.compiled_resources.resources:
            resource_instances[resource.kind] += resource.occurrences
        return {
            "schemaVersion": 2,
            "readOnly": True,
            "build": {
                "status": self.build.status,
                "expectedXexSha256": self.build.expected_sha256,
                "actualXexSha256": self.build.actual_sha256,
                "message": self.build.message,
            },
            "archive": {
                "name": self.archive_name,
                "format": "zlib-wrapped" if self.archive_wrapped else "raw",
                "memberCount": self.archive_member_count,
                "duplicateExtraRecords": self.archive_duplicate_extra_count,
            },
            "compiledNpcResources": {
                "stageArchiveCount": self.compiled_resources.archive_count,
                "uniqueByType": {
                    kind: resource_counts[kind]
                    for kind in AI_RESOURCE_SUFFIXES
                },
                "instancesByType": {
                    kind: resource_instances[kind]
                    for kind in AI_RESOURCE_SUFFIXES
                },
                "aiPrograms": len(self.compiled_resources.programs),
                "aiFunctionModules": len(
                    self.compiled_resources.function_modules
                ),
            },
            "variants": [
                {
                    "archive": variant.archive,
                    "status": variant.status,
                    "matchedTables": variant.matched_tables,
                    "expectedTables": variant.expected_tables,
                    "details": variant.details,
                }
                for variant in self.variants
            ],
            "tables": [
                {
                    "id": source.id,
                    "name": source.name,
                    "origin": source.origin,
                    "category": source.category,
                    "key": f"0x{source.table.key:08X}",
                    "rowCount": len(source.table.rows),
                    "columnCount": len(source.table.columns),
                    "byteSize": source.table.byte_size,
                    "sha256": source.table.sha256,
                    "columns": [
                        {"name": column.name, "type": column.type_code}
                        for column in source.table.columns
                    ],
                }
                for source in self.tables
            ],
            "warnings": list(self.warnings),
        }


def _read_u16(data: bytes, offset: int, source: str) -> int:
    if offset < 0 or offset + 2 > len(data):
        raise GameplayDataError(f"{source}: truncated 16-bit value at 0x{offset:X}")
    return struct.unpack_from(">H", data, offset)[0]


def _read_u32(data: bytes, offset: int, source: str) -> int:
    if offset < 0 or offset + 4 > len(data):
        raise GameplayDataError(f"{source}: truncated 32-bit value at 0x{offset:X}")
    return struct.unpack_from(">I", data, offset)[0]


def _read_i32(data: bytes, offset: int, source: str) -> int:
    if offset < 0 or offset + 4 > len(data):
        raise GameplayDataError(f"{source}: truncated 32-bit value at 0x{offset:X}")
    return struct.unpack_from(">i", data, offset)[0]


def _decode_ascii(raw: bytes, source: str, label: str) -> str:
    try:
        return raw.decode("ascii")
    except UnicodeDecodeError as error:
        raise GameplayDataError(f"{source}: non-ASCII {label}") from error


def _align(value: int, alignment: int) -> int:
    return (value + alignment - 1) // alignment * alignment


def _decompress_pak(data: bytes, expected_size: int, source: str) -> tuple[bytes, int]:
    if expected_size < 4 or expected_size > MAX_ARCHIVE_SIZE:
        raise GameplayDataError(
            f"{source}: declared archive size {expected_size} is outside the supported range"
        )
    compressed = data[PAK_OUTER_HEADER_SIZE:]
    decoder = zlib.decompressobj()
    try:
        payload = decoder.decompress(compressed, expected_size + 1)
    except zlib.error as error:
        raise GameplayDataError(f"{source}: invalid zlib stream: {error}") from error
    if len(payload) > expected_size:
        raise GameplayDataError(
            f"{source}: zlib output exceeds declared size {expected_size}"
        )
    if not decoder.eof:
        reason = (
            "zlib output exceeds its declared size"
            if len(payload) == expected_size + 1
            else "truncated zlib stream"
        )
        raise GameplayDataError(f"{source}: {reason}")
    if len(payload) != expected_size:
        raise GameplayDataError(
            f"{source}: decompressed size {len(payload)} does not match "
            f"declared size {expected_size}"
        )
    if any(decoder.unused_data):
        raise GameplayDataError(f"{source}: nonzero data follows the zlib stream")
    return payload, len(compressed) - len(decoder.unused_data)


def read_pak(path: Path) -> PakArchive:
    source = str(path)
    try:
        file_size = path.stat().st_size
    except OSError as error:
        raise GameplayDataError(f"Cannot inspect archive {path}: {error}") from error
    if file_size < 4 or file_size > MAX_ARCHIVE_SIZE:
        raise GameplayDataError(
            f"{source}: file size {file_size} is outside the supported range"
        )
    try:
        data = path.read_bytes()
    except OSError as error:
        raise GameplayDataError(f"Cannot read archive {path}: {error}") from error

    wrapped = (
        len(data) >= PAK_OUTER_HEADER_SIZE + 2
        and not any(data[4:PAK_OUTER_HEADER_SIZE])
    )
    if wrapped:
        payload, compressed_size = _decompress_pak(
            data, _read_u32(data, 0, source), source
        )
    else:
        payload = data
        compressed_size = 0

    member_count = _read_u32(payload, 0, source)
    if member_count > MAX_PAK_MEMBERS:
        raise GameplayDataError(
            f"{source}: member count {member_count} exceeds the supported limit"
        )
    table_end = 4 + member_count * PAK_ENTRY_SIZE
    if table_end > len(payload):
        raise GameplayDataError(
            f"{source}: member table ends at 0x{table_end:X}, beyond archive size "
            f"0x{len(payload):X}"
        )
    minimum_data_offset = _align(table_end, PAK_ALIGNMENT)

    members: list[PakMember] = []
    for index in range(member_count):
        offset = 4 + index * PAK_ENTRY_SIZE
        name_field = payload[offset : offset + PAK_NAME_SIZE]
        terminator = name_field.find(b"\0")
        if terminator < 1:
            raise GameplayDataError(
                f"{source}: member {index} has no nonempty NUL-terminated name"
            )
        if any(name_field[terminator + 1 :]):
            raise GameplayDataError(
                f"{source}: member {index} has nonzero name padding"
            )
        name = _decode_ascii(name_field[:terminator], source, f"member {index} name")
        reserved = _read_u32(payload, offset + 256, source)
        member_offset = _read_u32(payload, offset + 260, source)
        member_size = _read_u32(payload, offset + 264, source)
        if reserved:
            raise GameplayDataError(
                f"{source}: member {index} {name!r} has unsupported reserved value "
                f"0x{reserved:08X}"
            )
        if member_offset % PAK_ALIGNMENT:
            raise GameplayDataError(
                f"{source}: member {index} {name!r} offset 0x{member_offset:X} "
                f"is not 0x{PAK_ALIGNMENT:X}-aligned"
            )
        if member_offset < minimum_data_offset:
            raise GameplayDataError(
                f"{source}: member {index} {name!r} overlaps the member table"
            )
        if member_size > len(payload) - member_offset:
            raise GameplayDataError(
                f"{source}: member {index} {name!r} range "
                f"0x{member_offset:X}+0x{member_size:X} exceeds archive size"
            )
        members.append(PakMember(index, name, member_offset, member_size))

    return PakArchive(
        path=path,
        wrapped=wrapped,
        payload=payload,
        members=tuple(members),
        compressed_size=compressed_size,
    )


@dataclass
class _CompiledResourceAccumulator:
    name: str
    kind: str
    sha256: str
    archives: list[str]
    occurrences: int
    payload: bytes | None


def extract_compiled_ai_strings(
    data: bytes, source_name: str
) -> tuple[str, ...]:
    if len(data) > MAX_COMPILED_AI_RESOURCE_SIZE:
        raise GameplayDataError(
            f"{source_name}: compiled AI resource size {len(data)} exceeds "
            f"{MAX_COMPILED_AI_RESOURCE_SIZE}"
        )

    strings = []
    offset = 0
    while offset + 4 <= len(data):
        length = struct.unpack_from(">I", data, offset)[0]
        end = offset + 4 + length
        if (
            2 <= length <= MAX_COMPILED_AI_STRING_SIZE
            and end <= len(data)
            and data[end - 1] == 0
            and all(0x20 <= byte <= 0x7E for byte in data[offset + 4 : end - 1])
        ):
            strings.append(data[offset + 4 : end - 1].decode("ascii"))
            offset = end
            continue
        offset += 1
    return tuple(strings)


def parse_ai_program(resource: CompiledResource, data: bytes) -> AiProgram:
    strings = extract_compiled_ai_strings(data, resource.name)
    source_path = next(
        (
            token
            for token in strings
            if token.casefold().startswith("ai\\unit\\")
            and token.casefold().endswith(".ai")
        ),
        "",
    )
    if not source_path:
        raise GameplayDataError(
            f"{resource.name}: retained unit-AI source path was not found"
        )

    included = []
    for index, token in enumerate(strings[:-1]):
        if token.casefold() != "include_ai":
            continue
        candidate = strings[index + 1].replace("/", "\\")
        folded = candidate.casefold()
        if folded.startswith("function\\") and folded.endswith(".ai_func"):
            function_name = candidate[len("function\\") : -len(".ai_func")]
            if function_name and function_name.casefold() not in {
                name.casefold() for name in included
            }:
                included.append(function_name)

    included_by_name = {name.casefold(): name for name in included}
    calls = []
    in_function_block = False
    for token in strings:
        folded = token.casefold()
        if folded == "ai_func":
            in_function_block = True
            continue
        if folded == "ai_func_end":
            in_function_block = False
            continue
        if in_function_block and folded in included_by_name:
            calls.append(included_by_name[folded])

    return AiProgram(
        resource=resource,
        source_path=source_path,
        included_functions=tuple(included),
        called_functions=tuple(calls),
        level_branch_count=sum(
            token.casefold() == "iflevel" for token in strings
        ),
    )


def parse_ai_function_module(
    resource: CompiledResource, data: bytes
) -> AiFunctionModule:
    strings = extract_compiled_ai_strings(data, resource.name)
    source_path = next(
        (
            token
            for token in strings
            if token.casefold().startswith("ai\\unit\\function\\")
            and token.casefold().endswith(".ai_func")
        ),
        "",
    )
    if not source_path:
        raise GameplayDataError(
            f"{resource.name}: retained AI-function source path was not found"
        )

    parameters = []
    in_parameters = False
    for token in strings:
        folded = token.casefold()
        if folded == "ai_function_parameter":
            in_parameters = True
            continue
        if folded == "ai_function_parameter_end":
            in_parameters = False
            continue
        if in_parameters and token.startswith("v_") and token not in parameters:
            parameters.append(token)
    return AiFunctionModule(
        resource=resource,
        source_path=source_path,
        parameters=tuple(parameters),
    )


def _compiled_resource_kind(name: str) -> str | None:
    folded = name.casefold()
    return next(
        (suffix for suffix in AI_RESOURCE_SUFFIXES if folded.endswith(suffix)),
        None,
    )


def load_compiled_resource_index(
    packed_root: Path,
    progress: Callable[[str], None] | None = None,
) -> CompiledResourceIndex:
    notify = progress or (lambda _message: None)
    archive_paths = list(packed_root.glob("*_res2_res.pak"))
    archive_paths.extend(
        path
        for name in AI_STAGE_EXTRA_ARCHIVES
        if (path := packed_root / name).is_file()
    )
    archive_paths = sorted(set(archive_paths), key=lambda path: path.name.casefold())

    accumulated: dict[str, _CompiledResourceAccumulator] = {}
    for index, path in enumerate(archive_paths, 1):
        notify(
            f"NPC resources {index}/{len(archive_paths)}: {path.name}"
        )
        archive = read_pak(path)
        for member in archive.members:
            kind = _compiled_resource_kind(member.name)
            if kind is None:
                continue
            payload = archive.read_member(member)
            digest = hashlib.sha256(payload).hexdigest()
            key = member.name.casefold()
            existing = accumulated.get(key)
            if existing is not None:
                if existing.sha256 != digest:
                    first_archive = existing.archives[0]
                    raise GameplayDataError(
                        f"Compiled resource {member.name!r} differs between "
                        f"{first_archive} and {path.name}"
                    )
                existing.occurrences += 1
                if path.name not in existing.archives:
                    existing.archives.append(path.name)
                continue
            accumulated[key] = _CompiledResourceAccumulator(
                name=member.name,
                kind=kind,
                sha256=digest,
                archives=[path.name],
                occurrences=1,
                payload=payload if kind in {".aib", ".ai_funcb"} else None,
            )

    resources = tuple(
        CompiledResource(
            name=entry.name,
            kind=entry.kind,
            sha256=entry.sha256,
            archives=tuple(entry.archives),
            occurrences=entry.occurrences,
        )
        for entry in sorted(
            accumulated.values(), key=lambda entry: entry.name.casefold()
        )
    )
    resources_by_name = {
        resource.name.casefold(): resource for resource in resources
    }
    programs = []
    function_modules = []
    for key, entry in sorted(accumulated.items()):
        if entry.payload is None:
            continue
        resource = resources_by_name[key]
        if entry.kind == ".aib":
            programs.append(parse_ai_program(resource, entry.payload))
        elif entry.kind == ".ai_funcb":
            function_modules.append(
                parse_ai_function_module(resource, entry.payload)
            )

    return CompiledResourceIndex(
        archive_count=len(archive_paths),
        resources=resources,
        programs=tuple(programs),
        function_modules=tuple(function_modules),
    )


def parse_sox(data: bytes, source_name: str) -> SoxTable:
    if len(data) < SOX_ROW_DATA_OFFSET + len(SOX_FOOTER):
        raise GameplayDataError(
            f"{source_name}: file is too small for a SOX header and footer"
        )
    key = _read_u32(data, 0, source_name)
    column_count = _read_u32(data, 4, source_name)
    row_count = _read_u32(data, 8, source_name)
    if column_count > SOX_DESCRIPTOR_COUNT:
        raise GameplayDataError(
            f"{source_name}: column count {column_count} exceeds "
            f"{SOX_DESCRIPTOR_COUNT}"
        )
    if row_count > MAX_SOX_ROWS:
        raise GameplayDataError(
            f"{source_name}: row count {row_count} exceeds the supported limit"
        )

    columns: list[SoxColumn] = []
    minimum_row_size = 4
    for index in range(column_count):
        offset = 12 + index * SOX_DESCRIPTOR_SIZE
        name_field = data[offset : offset + 64]
        terminator = name_field.find(b"\0")
        if terminator < 1:
            raise GameplayDataError(
                f"{source_name}: column {index} has no nonempty NUL-terminated name"
            )
        if any(byte not in {0, 0x20} for byte in name_field[terminator + 1 :]):
            raise GameplayDataError(
                f"{source_name}: column {index} has unsupported name padding"
            )
        name = _decode_ascii(
            name_field[:terminator], source_name, f"column {index} name"
        )
        type_code = _read_u32(data, offset + 64, source_name)
        if type_code not in {1, 2, 3}:
            raise GameplayDataError(
                f"{source_name}: column {name!r} uses unsupported type {type_code}"
            )
        minimum_row_size += 2 if type_code == 1 else 4
        columns.append(SoxColumn(name, type_code))

    minimum_data_size = row_count * minimum_row_size + len(SOX_FOOTER)
    if minimum_data_size > len(data) - SOX_ROW_DATA_OFFSET:
        raise GameplayDataError(
            f"{source_name}: declared rows cannot fit in the available data"
        )

    cursor = SOX_ROW_DATA_OFFSET
    rows: list[SoxRow] = []
    for row_index in range(row_count):
        row_id = _read_u32(data, cursor, source_name)
        cursor += 4
        expected_id = row_index + 1
        if row_id != expected_id:
            raise GameplayDataError(
                f"{source_name}: row {row_index} has ID {row_id}, expected {expected_id}"
            )
        values: list[SoxValue] = []
        for column in columns:
            if column.type_code == 1:
                size = _read_u16(data, cursor, source_name)
                cursor += 2
                if size > len(data) - cursor:
                    raise GameplayDataError(
                        f"{source_name}: row {row_id} column {column.name!r} "
                        f"string length {size} exceeds the file"
                    )
                values.append(data[cursor : cursor + size])
                cursor += size
            else:
                values.append(_read_i32(data, cursor, source_name))
                cursor += 4
        rows.append(SoxRow(row_id, tuple(values)))

    if data[cursor : cursor + len(SOX_FOOTER)] != SOX_FOOTER:
        raise GameplayDataError(
            f"{source_name}: missing THEND footer at 0x{cursor:X}"
        )
    footer_size = len(data) - cursor
    return SoxTable(
        source_name=source_name,
        key=key,
        columns=tuple(columns),
        rows=tuple(rows),
        footer_size=footer_size,
        byte_size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )


def _encoding_hint(name: str, origin: str) -> str | None:
    upper = f"{origin}/{name}".upper().replace("\\", "/")
    for language, encoding in LANGUAGE_ENCODINGS.items():
        if f"/{language}/" in upper or f"_{language}.SOX" in upper:
            return encoding
    if name.casefold() == "itemtable.sox":
        return "cp949"
    return None


def decode_string(raw: bytes, encoding: str | None = None) -> str:
    if not raw:
        return ""
    candidates: list[str] = []
    if encoding:
        candidates.append(encoding)
    candidates.extend(("ascii", "utf-8", "cp949", "cp932", "gb18030", "big5", "cp1252"))
    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            return raw.decode(candidate)
        except UnicodeDecodeError:
            continue
    return "".join(
        chr(byte) if 0x20 <= byte < 0x7F else f"\\x{byte:02x}" for byte in raw
    )


def display_value(value: SoxValue, encoding: str | None = None) -> str:
    return str(value) if isinstance(value, int) else decode_string(value, encoding)


def _table_metadata(name: str, origin: str) -> tuple[str, str]:
    upper = name.upper()
    if upper in CORE_TABLES:
        return CORE_TABLES[upper]
    if upper.startswith("ABILITY"):
        return "Abilities", "Ability names, commands, captions, or unlock data."
    if upper.startswith("ITEMDESC"):
        return "Items", "Localized item names and descriptions."
    if upper.startswith("MENULIBCHARINFO"):
        return "Heroes", "Localized hero profile information."
    if upper.startswith("LIBRARY_"):
        return "Library", "Gallery and library metadata."
    if upper.startswith("SOUND"):
        return "Audio", "Sound selection metadata."
    if upper.startswith("BRIEFING_") or "/briefing/" in origin.casefold():
        return "Briefings", "Localized mission briefing data."
    return "Other tables", "Unclassified SOX table; raw field names are retained."


def _table_source(
    identifier: str,
    name: str,
    origin: str,
    data: bytes,
) -> TableSource:
    category, description = _table_metadata(name, origin)
    return TableSource(
        id=identifier,
        name=name,
        origin=origin,
        category=category,
        description=description,
        encoding=_encoding_hint(name, origin),
        table=parse_sox(data, origin),
    )


def verify_build(game_root: Path) -> BuildVerification:
    executable = game_root / "default.xex"
    if not executable.is_file():
        return BuildVerification(
            "missing",
            EXPECTED_XEX_SHA256,
            None,
            "default.xex is missing; table data can be inspected but the build is unverified.",
        )
    try:
        digest = hashlib.sha256(executable.read_bytes()).hexdigest()
    except OSError as error:
        raise GameplayDataError(f"Cannot hash {executable}: {error}") from error
    if digest == EXPECTED_XEX_SHA256:
        return BuildVerification(
            "verified",
            EXPECTED_XEX_SHA256,
            digest,
            "Supported USA/Europe executable 0.0.0.3 verified.",
        )
    return BuildVerification(
        "mismatch",
        EXPECTED_XEX_SHA256,
        digest,
        "Executable hash does not match the supported USA/Europe 0.0.0.3 build.",
    )


def _find_packed_resources(game_root: Path) -> Path:
    packed = game_root / "data" / "PackedResources"
    if not packed.is_dir():
        raise GameplayDataError(
            f"Packed-resource directory is missing: {packed}"
        )
    return packed


def _load_tables(game_root: Path, archive: PakArchive) -> tuple[TableSource, ...]:
    sources: list[TableSource] = []
    for member in archive.members:
        if not member.name.casefold().endswith(".sox"):
            continue
        origin = f"PackedResources/{archive.path.name}:{member.name}"
        sources.append(
            _table_source(
                f"pak:{member.index}:{member.name}",
                member.name,
                origin,
                archive.read_member(member),
            )
        )

    data_root = game_root / "data"
    loose_paths = sorted(
        (
            path
            for path in data_root.rglob("*")
            if path.is_file() and path.suffix.casefold() == ".sox"
        ),
        key=lambda path: path.relative_to(data_root).as_posix().casefold(),
    )
    for path in loose_paths:
        relative = path.relative_to(data_root).as_posix()
        try:
            data = path.read_bytes()
        except OSError as error:
            raise GameplayDataError(f"Cannot read loose table {path}: {error}") from error
        sources.append(
            _table_source(f"loose:{relative}", path.name, relative, data)
        )

    return tuple(
        sorted(
            sources,
            key=lambda source: (
                source.category.casefold(),
                source.name.casefold(),
                source.origin.casefold(),
                source.id,
            ),
        )
    )


def _verify_variants(
    packed_root: Path,
    baseline: PakArchive,
) -> tuple[VariantVerification, ...]:
    expected_names = tuple(CORE_TABLES)
    baseline_hashes: dict[str, str] = {}
    for name in expected_names:
        matches = baseline.find(name)
        if matches:
            baseline_hashes[name] = hashlib.sha256(
                baseline.read_member(matches[0])
            ).hexdigest()

    variant_paths = sorted(
        (
            path
            for path in packed_root.iterdir()
            if path.is_file()
            and path.suffix.casefold() == ".pak"
            and path.stem.casefold().startswith("res_init")
        ),
        key=lambda path: path.name.casefold(),
    )
    results: list[VariantVerification] = []
    for path in variant_paths:
        archive = baseline if path == baseline.path else read_pak(path)
        missing: list[str] = []
        mismatched: list[str] = []
        matched = 0
        for name in expected_names:
            members = archive.find(name)
            if not members:
                missing.append(name)
                continue
            digest = hashlib.sha256(archive.read_member(members[0])).hexdigest()
            if baseline_hashes.get(name) == digest:
                matched += 1
            else:
                mismatched.append(name)
        if not missing and not mismatched and matched == len(expected_names):
            status = "identical"
            details = "All core mechanics tables match the baseline archive."
        else:
            status = "different"
            parts = []
            if missing:
                parts.append(f"missing: {', '.join(missing)}")
            if mismatched:
                parts.append(f"different: {', '.join(mismatched)}")
            details = "; ".join(parts) or "Core-table comparison is incomplete."
        results.append(
            VariantVerification(
                path.name, status, matched, len(expected_names), details
            )
        )
    return tuple(results)


def load_game_data(
    game_root: Path,
    progress: Callable[[str], None] | None = None,
) -> GameData:
    game_root = game_root.expanduser().resolve()
    if not game_root.is_dir():
        raise GameplayDataError(f"Game directory does not exist: {game_root}")
    notify = progress or (lambda _message: None)

    notify("Verifying executable")
    build = verify_build(game_root)
    packed_root = _find_packed_resources(game_root)
    archive_path = packed_root / "res_init.pak"
    if not archive_path.is_file():
        raise GameplayDataError(f"Core gameplay archive is missing: {archive_path}")

    notify("Reading res_init.pak")
    archive = read_pak(archive_path)
    notify("Parsing packed and loose SOX tables")
    tables = _load_tables(game_root, archive)
    notify("Comparing language-specific res_init archives")
    variants = _verify_variants(packed_root, archive)
    notify("Indexing compiled NPC resources")
    compiled_resources = load_compiled_resource_index(packed_root, notify)

    warnings: list[str] = []
    if build.status != "verified":
        warnings.append(build.message)
    available = {source.name.upper() for source in tables}
    missing_core = sorted(set(CORE_TABLES) - available)
    if missing_core:
        warnings.append(f"Missing core tables: {', '.join(missing_core)}")
    differing_variants = [
        variant.archive for variant in variants if variant.status != "identical"
    ]
    if differing_variants:
        warnings.append(
            "Core tables differ or are missing in: " + ", ".join(differing_variants)
        )
    if len(variants) != 10:
        warnings.append(
            f"Expected 10 res_init variants, found {len(variants)}."
        )

    data = GameData(
        game_root=game_root,
        build=build,
        archive_name=archive.path.name,
        archive_wrapped=archive.wrapped,
        archive_member_count=len(archive.members),
        archive_duplicate_extra_count=archive.duplicate_extra_count,
        tables=tables,
        variants=variants,
        compiled_resources=compiled_resources,
        warnings=tuple(warnings),
    )
    notify("Validating NPC relationships")
    data.npc_profiles()
    notify("Ready")
    return data


def write_structural_report(data: GameData, destination: Path) -> None:
    destination = destination.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    try:
        temporary.write_text(
            json.dumps(data.structural_report(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        temporary.replace(destination)
    except OSError as error:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise GameplayDataError(
            f"Cannot write structural report {destination}: {error}"
        ) from error


def validate_corpus(
    game_root: Path,
    progress: Callable[[str], None] | None = None,
) -> dict[str, object]:
    game_root = game_root.expanduser().resolve()
    packed_root = _find_packed_resources(game_root)
    notify = progress or (lambda _message: None)

    archive_count = 0
    wrapped_count = 0
    raw_count = 0
    member_count = 0
    duplicate_archive_count = 0
    duplicate_extra_count = 0
    nonidentical_duplicate_names = 0
    packed_sox_count = 0
    loose_sox_count = 0
    unique_sox_hashes: set[str] = set()

    archive_paths = sorted(
        (
            path
            for path in packed_root.iterdir()
            if path.is_file() and path.suffix.casefold() == ".pak"
        ),
        key=lambda path: path.name.casefold(),
    )
    for archive_index, path in enumerate(archive_paths, 1):
        notify(f"Archive {archive_index}/{len(archive_paths)}: {path.name}")
        archive = read_pak(path)
        archive_count += 1
        wrapped_count += int(archive.wrapped)
        raw_count += int(not archive.wrapped)
        member_count += len(archive.members)

        by_name: dict[str, list[PakMember]] = defaultdict(list)
        for member in archive.members:
            by_name[member.name.casefold()].append(member)
            if member.name.casefold().endswith(".sox"):
                table_data = archive.read_member(member)
                parse_sox(table_data, f"{path.name}:{member.name}")
                packed_sox_count += 1
                unique_sox_hashes.add(hashlib.sha256(table_data).hexdigest())
        duplicate_groups = [group for group in by_name.values() if len(group) > 1]
        if duplicate_groups:
            duplicate_archive_count += 1
            duplicate_extra_count += sum(len(group) - 1 for group in duplicate_groups)
            for group in duplicate_groups:
                hashes = {
                    hashlib.sha256(archive.read_member(member)).digest()
                    for member in group
                }
                if len(hashes) > 1:
                    nonidentical_duplicate_names += 1

    data_root = game_root / "data"
    loose_paths = sorted(
        (
            path
            for path in data_root.rglob("*")
            if path.is_file() and path.suffix.casefold() == ".sox"
        ),
        key=lambda path: path.relative_to(data_root).as_posix().casefold(),
    )
    for index, path in enumerate(loose_paths, 1):
        notify(f"Loose SOX {index}/{len(loose_paths)}: {path.name}")
        table_data = path.read_bytes()
        parse_sox(table_data, path.relative_to(data_root).as_posix())
        loose_sox_count += 1
        unique_sox_hashes.add(hashlib.sha256(table_data).hexdigest())

    return {
        "archives": archive_count,
        "wrappedArchives": wrapped_count,
        "rawArchives": raw_count,
        "members": member_count,
        "duplicateArchives": duplicate_archive_count,
        "duplicateExtraRecords": duplicate_extra_count,
        "nonidenticalDuplicateNames": nonidentical_duplicate_names,
        "packedSoxTables": packed_sox_count,
        "looseSoxTables": loose_sox_count,
        "soxTables": packed_sox_count + loose_sox_count,
        "uniqueSoxContents": len(unique_sox_hashes),
    }
