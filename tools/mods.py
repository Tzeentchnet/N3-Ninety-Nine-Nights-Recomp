#!/usr/bin/env python3
"""Validate N3 loose-file mods and build a disposable merged game-data tree."""

# Adapted from N3-ReGPU commit c03c26e7b80851a391ffb5f19bbc499c0f84fb5c
# under its MIT license. See LICENSES/N3-ReGPU.txt.

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
import tempfile
import tomllib
import uuid


MOD_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
INVALID_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
RESERVED_NAME = re.compile(
    r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)", re.IGNORECASE
)
REPORT_NAME = ".n3-mods.json"
PROJECT_ROOT = Path(__file__).resolve().parent.parent


class ModError(RuntimeError):
    pass


@dataclass(frozen=True)
class ModFile:
    relative: PurePosixPath
    source: Path


@dataclass(frozen=True)
class Mod:
    root: Path
    id: str
    name: str
    version: str
    description: str
    files: tuple[ModFile, ...]


def _is_link_or_reparse(path: Path) -> bool:
    info = path.lstat()
    attributes = getattr(info, "st_file_attributes", 0)
    return path.is_symlink() or bool(
        attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def _exists_without_following(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True


def _validate_component(name: str) -> None:
    if (
        not name
        or name in {".", ".."}
        or INVALID_NAME.search(name)
        or name.endswith((".", " "))
        or RESERVED_NAME.match(name)
    ):
        raise ModError(f"Unsafe path component: {name!r}")


def _validate_mod_id(value: str) -> None:
    if not MOD_ID.fullmatch(value):
        raise ModError(
            f"Invalid mod ID {value!r}; use lowercase ASCII letters, digits, '.', '_', or '-'"
        )


def _validate_asset_path(relative: PurePosixPath) -> None:
    if (
        relative.is_absolute()
        or not relative.parts
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise ModError(f"Unsafe mod path: {relative}")
    for part in relative.parts:
        _validate_component(part)
    if relative.parts[0].casefold() != "data":
        raise ModError(f"Mods may only provide files under data/: {relative}")


def _scan_mod_files(files_root: Path) -> tuple[ModFile, ...]:
    if not files_root.is_dir() or _is_link_or_reparse(files_root):
        raise ModError(f"Mod files folder is missing or unsafe: {files_root}")

    found: list[ModFile] = []
    folded_paths: set[str] = set()
    for current, directories, filenames in os.walk(files_root, followlinks=False):
        current_path = Path(current)
        if _is_link_or_reparse(current_path):
            raise ModError(f"Mod contains a linked or reparse directory: {current_path}")
        for directory in directories:
            candidate = current_path / directory
            if _is_link_or_reparse(candidate):
                raise ModError(f"Mod contains a linked or reparse directory: {candidate}")
        for filename in filenames:
            source = current_path / filename
            if _is_link_or_reparse(source) or not source.is_file():
                raise ModError(f"Mod contains a non-regular file: {source}")
            relative = PurePosixPath(source.relative_to(files_root).as_posix())
            _validate_asset_path(relative)
            key = relative.as_posix().casefold()
            if key in folded_paths:
                raise ModError(
                    f"Mod contains duplicate case-insensitive paths: {relative}"
                )
            folded_paths.add(key)
            found.append(ModFile(relative, source))
    return tuple(
        sorted(found, key=lambda item: item.relative.as_posix().casefold())
    )


def load_mod(root: Path) -> Mod:
    if not root.is_dir() or _is_link_or_reparse(root):
        raise ModError(f"Mod folder is missing or unsafe: {root}")
    manifest_path = root / "mod.toml"
    if not manifest_path.is_file() or _is_link_or_reparse(manifest_path):
        raise ModError(f"Mod manifest is missing or unsafe: {manifest_path}")

    try:
        with manifest_path.open("rb") as manifest_file:
            document = tomllib.load(manifest_file)
        metadata = document["mod"]
        mod_id = metadata["id"]
        name = metadata["name"]
        version = metadata["version"]
        description = metadata.get("description", "")
    except (OSError, tomllib.TOMLDecodeError, KeyError, TypeError) as error:
        raise ModError(f"Invalid manifest {manifest_path}: {error}") from error

    for label, value in (
        ("id", mod_id),
        ("name", name),
        ("version", version),
        ("description", description),
    ):
        if not isinstance(value, str) or (label != "description" and not value.strip()):
            raise ModError(f"Manifest field mod.{label} must be a non-empty string")
    _validate_mod_id(mod_id)
    if root.name != mod_id:
        raise ModError(
            f"Mod folder {root.name!r} must match manifest ID {mod_id!r}"
        )

    return Mod(
        root,
        mod_id,
        name.strip(),
        version.strip(),
        description.strip(),
        _scan_mod_files(root / "files"),
    )


def read_load_order(path: Path) -> tuple[str, ...]:
    if not path.is_file() or _is_link_or_reparse(path):
        raise ModError(f"Load-order file is missing or unsafe: {path}")
    ordered: list[str] = []
    seen: set[str] = set()
    for number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), 1
    ):
        value = raw_line.split("#", 1)[0].strip()
        if not value:
            continue
        _validate_mod_id(value)
        if value in seen:
            raise ModError(f"Duplicate mod ID on line {number}: {value}")
        seen.add(value)
        ordered.append(value)
    return tuple(ordered)


def load_enabled_mods(mods_root: Path, order_path: Path) -> tuple[Mod, ...]:
    if not mods_root.is_dir() or _is_link_or_reparse(mods_root):
        raise ModError(f"Mods folder is missing or unsafe: {mods_root}")
    return tuple(
        load_mod(mods_root / mod_id) for mod_id in read_load_order(order_path)
    )


def discover_mods(mods_root: Path) -> tuple[Mod, ...]:
    if not mods_root.is_dir() or _is_link_or_reparse(mods_root):
        raise ModError(f"Mods folder is missing or unsafe: {mods_root}")
    discovered = []
    for candidate in sorted(mods_root.iterdir(), key=lambda path: path.name.casefold()):
        if not candidate.is_dir():
            continue
        discovered.append(load_mod(candidate))
    return tuple(discovered)


def _scan_base_files(
    game: Path,
) -> dict[str, tuple[PurePosixPath, Path]]:
    if not game.is_dir() or _is_link_or_reparse(game):
        raise ModError(f"Game folder is missing or unsafe: {game}")
    if not (game / "default.xex").is_file() or not (game / "data").is_dir():
        raise ModError("Game folder must contain default.xex and data/")

    files: dict[str, tuple[PurePosixPath, Path]] = {}
    for current, directories, filenames in os.walk(game, followlinks=False):
        current_path = Path(current)
        if _is_link_or_reparse(current_path):
            raise ModError(f"Game tree contains a linked or reparse directory: {current_path}")
        for directory in directories:
            candidate = current_path / directory
            if _is_link_or_reparse(candidate):
                raise ModError(f"Game tree contains a linked or reparse directory: {candidate}")
        for filename in filenames:
            source = current_path / filename
            if _is_link_or_reparse(source) or not source.is_file():
                raise ModError(f"Game tree contains a non-regular file: {source}")
            relative = PurePosixPath(source.relative_to(game).as_posix())
            for part in relative.parts:
                _validate_component(part)
            key = relative.as_posix().casefold()
            if key in files:
                raise ModError(
                    f"Game tree contains duplicate case-insensitive paths: {relative}"
                )
            files[key] = (relative, source)
    return files


def _paths_overlap(first: Path, second: Path) -> bool:
    first_parts = tuple(part.casefold() for part in first.parts)
    second_parts = tuple(part.casefold() for part in second.parts)
    common = min(len(first_parts), len(second_parts))
    return first_parts[:common] == second_parts[:common]


def _resolve_path(path: Path) -> Path:
    try:
        return path.resolve(strict=False)
    except (OSError, RuntimeError) as error:
        raise ModError(f"Cannot resolve path safely: {path}: {error}") from error


def _stage_output(requested: Path) -> Path:
    project = _resolve_path(PROJECT_ROOT)
    output = project / "out" / "game"
    for path in (output.parent, output):
        if _exists_without_following(path) and _is_link_or_reparse(path):
            raise ModError(
                f"Stage path must not contain a link or reparse point: {path}"
            )
    if _resolve_path(requested) != _resolve_path(output):
        raise ModError(f"Output must be the project's out/game directory: {output}")
    return output


def _copy_base(
    base_files: dict[str, tuple[PurePosixPath, Path]],
    staging: Path,
    *,
    copy_base: bool,
) -> tuple[int, int]:
    linked = 0
    copied = 0
    for relative, source in (
        value for _, value in sorted(base_files.items())
    ):
        destination = staging.joinpath(*relative.parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if copy_base:
            shutil.copy2(source, destination)
            copied += 1
            continue
        try:
            os.link(source, destination)
            linked += 1
        except OSError:
            shutil.copy2(source, destination)
            copied += 1
    return linked, copied


def stage_mods(
    game: Path,
    mods_root: Path,
    order_path: Path,
    output: Path,
    *,
    replace: bool,
    copy_base: bool,
) -> dict[str, object]:
    game = game.absolute()
    mods_root = mods_root.absolute()
    order_path = order_path.absolute()
    output = _stage_output(output.absolute())

    resolved_output = _resolve_path(output)
    if any(
        _paths_overlap(resolved_output, _resolve_path(source))
        for source in (game, mods_root, order_path)
    ):
        raise ModError(
            "Output must not overlap the game, mods, or load-order paths, including aliases"
        )
    if output.exists() and not replace:
        raise ModError(f"Output already exists; pass --replace to rebuild it: {output}")
    if _exists_without_following(output) and (
        not output.is_dir() or _is_link_or_reparse(output)
    ):
        raise ModError(f"Existing output is not a safe directory: {output}")

    enabled = load_enabled_mods(mods_root, order_path)
    base_files = _scan_base_files(game)
    report_key = REPORT_NAME.casefold()
    if any(
        key == report_key or key.startswith(report_key + "/")
        for key in base_files
    ):
        raise ModError(
            f"Game tree contains the reserved staging report path: {REPORT_NAME}"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    if _is_link_or_reparse(output.parent):
        raise ModError(
            f"Stage parent must not be a link or reparse point: {output.parent}"
        )
    staging = Path(
        tempfile.mkdtemp(prefix=f".{output.name}.stage-", dir=output.parent)
    )
    backup: Path | None = None

    try:
        linked, copied = _copy_base(
            base_files, staging, copy_base=copy_base
        )
        applied: dict[str, dict[str, object]] = {}
        conflicts: list[dict[str, str]] = []

        for mod in enabled:
            for mod_file in mod.files:
                key = mod_file.relative.as_posix().casefold()
                if key in base_files:
                    target_relative = base_files[key][0]
                elif key in applied:
                    target_relative = PurePosixPath(str(applied[key]["path"]))
                else:
                    target_relative = mod_file.relative

                destination = staging.joinpath(*target_relative.parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                if destination.exists():
                    if (
                        not destination.is_file()
                        or _is_link_or_reparse(destination)
                    ):
                        raise ModError(
                            f"Override target is not a regular file: {target_relative}"
                        )
                    destination.unlink()

                previous = applied.get(key)
                providers = list(previous["providers"]) if previous else []
                if previous:
                    conflicts.append(
                        {
                            "path": target_relative.as_posix(),
                            "loser": str(previous["winner"]),
                            "winner": mod.id,
                        }
                    )
                providers.append(mod.id)
                shutil.copy2(mod_file.source, destination)
                applied[key] = {
                    "path": target_relative.as_posix(),
                    "winner": mod.id,
                    "providers": providers,
                    "replacesBase": key in base_files,
                }

        report: dict[str, object] = {
            "schemaVersion": 1,
            "generatedUtc": datetime.now(timezone.utc).isoformat(),
            "base": str(game),
            "loadOrder": [mod.id for mod in enabled],
            "baseFiles": len(base_files),
            "hardlinkedBaseFiles": linked,
            "copiedBaseFiles": copied,
            "overrides": [applied[key] for key in sorted(applied)],
            "conflicts": conflicts,
        }
        (staging / REPORT_NAME).write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )

        if output.exists():
            backup = output.with_name(
                f".{output.name}.backup-{uuid.uuid4().hex}"
            )
            os.replace(output, backup)
        try:
            os.replace(staging, output)
        except Exception:
            if (
                backup is not None
                and backup.exists()
                and not output.exists()
            ):
                os.replace(backup, output)
            raise
        if backup is not None:
            shutil.rmtree(backup)
        return report
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def _validate_command(args: argparse.Namespace) -> None:
    enabled = load_enabled_mods(args.mods.absolute(), args.order.absolute())
    file_count = sum(len(mod.files) for mod in enabled)
    print(f"Validated {len(enabled)} enabled mods with {file_count} files")
    for mod in enabled:
        print(f"{mod.id} {mod.version}: {len(mod.files)} files")


def _list_command(args: argparse.Namespace) -> None:
    discovered = discover_mods(args.mods.absolute())
    records = [
        {
            "id": mod.id,
            "name": mod.name,
            "version": mod.version,
            "description": mod.description,
            "files": len(mod.files),
        }
        for mod in discovered
    ]
    if args.json:
        print(json.dumps({"schemaVersion": 1, "mods": records}, indent=2))
        return
    if not records:
        print("No mods found")
        return
    for record in records:
        description = f" - {record['description']}" if record["description"] else ""
        print(
            f"{record['id']} {record['version']}: {record['name']} "
            f"({record['files']} files){description}"
        )


def _stage_command(args: argparse.Namespace) -> None:
    report = stage_mods(
        args.game,
        args.mods,
        args.order,
        args.output,
        replace=args.replace,
        copy_base=args.copy_base,
    )
    print(
        f"Staged {report['baseFiles']} base files and {len(report['overrides'])} overrides "
        f"from {len(report['loadOrder'])} mods"
    )
    if args.copy_base:
        print(f"Copied {report['copiedBaseFiles']} base files as requested")
    elif report["copiedBaseFiles"]:
        print(
            f"Hardlinks were unavailable for {report['copiedBaseFiles']} base files; "
            "those files were copied"
        )
    if report["conflicts"]:
        print(f"Resolved {len(report['conflicts'])} conflicts by load order")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    default_mods = PROJECT_ROOT / "mods"
    default_order = default_mods / "enabled.txt"

    validate = commands.add_parser(
        "validate", help="validate enabled mod manifests and files"
    )
    validate.add_argument("--mods", type=Path, default=default_mods)
    validate.add_argument("--order", type=Path, default=default_order)
    validate.set_defaults(run=_validate_command)

    list_command = commands.add_parser(
        "list", help="list every discovered mod package"
    )
    list_command.add_argument("--mods", type=Path, default=default_mods)
    list_command.add_argument("--json", action="store_true")
    list_command.set_defaults(run=_list_command)

    stage = commands.add_parser("stage", help="build a merged game tree")
    stage.add_argument("--game", type=Path, default=PROJECT_ROOT / "private" / "game")
    stage.add_argument("--mods", type=Path, default=default_mods)
    stage.add_argument("--order", type=Path, default=default_order)
    stage.add_argument("--output", type=Path, default=PROJECT_ROOT / "out" / "game")
    stage.add_argument("--replace", action="store_true")
    stage.add_argument(
        "--copy-base",
        action="store_true",
        help="copy every base file instead of using hardlinks",
    )
    stage.set_defaults(run=_stage_command)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        args.run(args)
    except (ModError, OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
