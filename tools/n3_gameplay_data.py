#!/usr/bin/env python3
"""Bounded read-only readers and view models for N3 gameplay data."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
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
                f"Retail hero values: {self.observed_summary}",
                f"Known limits: {self.known_limits}",
                f"Evidence: {self.evidence}",
            )
        )
        return "\n".join(lines)


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
        return {
            "schemaVersion": 1,
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

    notify("Ready")
    return GameData(
        game_root=game_root,
        build=build,
        archive_name=archive.path.name,
        archive_wrapped=archive.wrapped,
        archive_member_count=len(archive.members),
        archive_duplicate_extra_count=archive.duplicate_extra_count,
        tables=tables,
        variants=variants,
        warnings=tuple(warnings),
    )


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
