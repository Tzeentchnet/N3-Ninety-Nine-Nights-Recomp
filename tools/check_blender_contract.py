"""Check the recomp's documented Blender baseline and receipt contract."""

from __future__ import annotations

import argparse
import ast
import hashlib
import html
import json
import os
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path
from urllib.parse import unquote, urlsplit

PROJECT_ROOT = Path(__file__).resolve().parent.parent
IMPORT_OPERATORS = (
    "import_scene.n3_bm",
    "import_scene.n3_skin",
    "import_scene.n3_character_package",
    "import_scene.n3_static_resource_package",
    "import_scene.n3_bsmap_terrain_package",
    "import_scene.n3_level_package",
    "import_scene.n3_navigation_package",
    "import_scene.n3_camera_package",
    "import_scene.n3_detached_attachment",
)
HISTORICAL_BASELINE_VERSION = "0.14.0"
MARKER_NAME = "n3-blender-baseline"
SCHEMA_PATH = "docs/schemas/n3-blender-export-v1.schema.json"
SCOPED_DOCS = (
    "docs/BLENDER-MODDING.md",
    "docs/MODDING.md",
    "docs/PORTING.md",
    "docs/STATUS.md",
)
_SEMVER = re.compile(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\Z")


class ConsistencyError(ValueError):
    """The documented Blender contract is inconsistent."""


class FileTree:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def read(self, path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise ConsistencyError(f"cannot read {path}: {error}") from error

    def is_file(self, path: Path) -> bool:
        return path.is_file()

    def is_dir(self, path: Path) -> bool:
        return path.is_dir()

    def resolve(self, path: Path) -> Path:
        return path.resolve()


def _blank(text: str) -> str:
    return "".join(char if char in "\r\n" else " " for char in text)


def _unquote_container(line: str) -> str:
    while match := re.match(r"^ {0,3}>[ \t]?", line):
        line = line[match.end() :]
    return line


def _mask_blocks(text: str) -> str:
    """Mask fenced/indented code and HTML comments while retaining offsets."""
    masked: list[str] = []
    fence: tuple[str, int, int] | None = None
    lists: list[tuple[int, int]] = []
    for line in text.splitlines(keepends=True):
        content = _unquote_container(line)
        if fence is not None:
            char, length, base = fence
            candidate = content[base:] if content.startswith(" " * base) else content
            if re.match(rf"^ {{0,3}}{re.escape(char)}{{{length},}}[ \t]*(?:\r?\n)?$", candidate):
                fence = None
            masked.append(_blank(line))
            continue

        indent = len(content) - len(content.lstrip(" "))
        item = re.match(r"^( *)(?:[-+*]|\d{1,9}[.)])[ \t]+", content)
        if item and (indent < 4 or (lists and indent >= lists[-1][1])):
            while lists and lists[-1][0] >= indent:
                lists.pop()
            lists.append((indent, item.end()))
            logical, base = content[item.end() :], item.end()
        else:
            if content.strip():
                while lists and indent < lists[-1][1]:
                    lists.pop()
            base = lists[-1][1] if lists and indent >= lists[-1][1] else 0
            logical = content[base:]

        if logical.startswith(("    ", "\t")):
            masked.append(_blank(line))
            continue
        opening = re.match(r"^ {0,3}(`{3,}|~{3,})([^\r\n]*)", logical)
        if opening and not (opening.group(1)[0] == "`" and "`" in opening.group(2)):
            fence = (opening.group(1)[0], len(opening.group(1)), base)
            masked.append(_blank(line))
        else:
            masked.append(line)
    without_code = "".join(masked)
    comment_view = _mask_inline_code(without_code)
    result = list(without_code)
    for comment in re.finditer(r"<!--[\s\S]*?(?:-->|$)", comment_view):
        result[comment.start() : comment.end()] = _blank(without_code[comment.start() : comment.end()])
    html_view = _mask_inline_code("".join(result))
    for block in re.finditer(
        r"<(pre|code|script|style|textarea)(?:\s[^>]*)?>[\s\S]*?(?:</\1\s*>|$)",
        html_view,
        re.IGNORECASE,
    ):
        result[block.start() : block.end()] = _blank(without_code[block.start() : block.end()])
    return "".join(result)


def _escaped(text: str, index: int) -> bool:
    slashes = 0
    index -= 1
    while index >= 0 and text[index] == "\\":
        slashes += 1
        index -= 1
    return bool(slashes % 2)


def _matching_ticks(text: str, start: int) -> tuple[int, int] | None:
    end = start
    while end < len(text) and text[end] == "`":
        end += 1
    width = end - start
    cursor = end
    while cursor < len(text):
        cursor = text.find("`", cursor)
        if cursor < 0:
            return None
        after = cursor
        while after < len(text) and text[after] == "`":
            after += 1
        if after - cursor == width:
            return end, after
        cursor = after
    return None


def _mask_inline_code(text: str) -> str:
    result = list(text)
    cursor = 0
    while cursor < len(text):
        if text[cursor] != "`" or _escaped(text, cursor):
            cursor += 1
            continue
        match = _matching_ticks(text, cursor)
        if match is None:
            cursor += 1
            continue
        _, end = match
        result[cursor:end] = _blank(text[cursor:end])
        cursor = end
    return "".join(result)


def _unescape_markdown(value: str) -> str:
    value = re.sub(r"""\\([!"#$%&'()*+,\-./:;<=>?@\[\\\]^_`{|}~])""", r"\1", value)
    return html.unescape(value)


def _label(value: str) -> str:
    return " ".join(_unescape_markdown(value).split()).casefold()


def _bracket_end(text: str, start: int) -> int | None:
    depth = 1
    for index in range(start + 1, len(text)):
        if _escaped(text, index):
            continue
        if text[index] == "[":
            depth += 1
        elif text[index] == "]":
            depth -= 1
            if not depth:
                return index
    return None


def _inline_destination(text: str, start: int) -> tuple[str, int] | None:
    """Parse an inline destination, including balanced parentheses and titles."""
    index = start + 1
    while index < len(text) and text[index].isspace():
        index += 1
    if index == len(text):
        return None
    if text[index] == "<":
        begin = index + 1
        index = begin
        while index < len(text) and (text[index] != ">" or _escaped(text, index)):
            if text[index] in "\r\n":
                return None
            index += 1
        if index == len(text):
            return None
        destination = text[begin:index]
        index += 1
    else:
        begin = index
        depth = 0
        while index < len(text):
            char = text[index]
            if char == "\\" and index + 1 < len(text):
                index += 2
                continue
            if char == "(":
                depth += 1
            elif char == ")":
                if not depth:
                    return text[begin:index], index + 1
                depth -= 1
            elif char.isspace() and not depth:
                break
            index += 1
        if depth:
            return None
        destination = text[begin:index]

    while index < len(text) and text[index].isspace():
        index += 1
    if index < len(text) and text[index] != ")":
        opener = text[index]
        if opener not in "\"'(":
            return None
        closer = ")" if opener == "(" else opener
        index += 1
        while index < len(text) and (text[index] != closer or _escaped(text, index)):
            index += 1
        if index == len(text):
            return None
        index += 1
        while index < len(text) and text[index].isspace():
            index += 1
    if index == len(text) or text[index] != ")":
        return None
    return destination, index + 1


def _definition_destination(value: str) -> str | None:
    value = value.lstrip()
    if value.startswith("<"):
        for index in range(1, len(value)):
            if value[index] == ">" and not _escaped(value, index):
                return value[1:index]
        return None
    match = re.match(r"(?:\\.|[^\s])+", value)
    return match.group() if match else None


def _definitions(text: str) -> tuple[str, dict[str, tuple[str, int]]]:
    lines = text.splitlines(keepends=True)
    visible_lines = _mask_inline_code(text).splitlines(keepends=True)
    output = list(lines)
    definitions: dict[str, tuple[str, int]] = {}
    offset = 0
    index = 0
    pattern = re.compile(r"^ {0,3}\[((?:\\.|[^\\\]])+)\]:[ \t]*(.*)$")
    while index < len(lines):
        match = pattern.match(visible_lines[index].rstrip("\r\n"))
        if match:
            label = lines[index][match.start(1) : match.end(1)]
            rest = lines[index][match.start(2) : match.end(2)]
            destination = _definition_destination(rest)
            consumed = 1
            if destination is None and not rest.strip() and index + 1 < len(lines) and visible_lines[index + 1].strip():
                destination = _definition_destination(lines[index + 1])
                if destination is not None:
                    consumed = 2
            if destination is not None:
                definitions.setdefault(_label(label), (destination, offset))
                for line_index in range(index, index + consumed):
                    output[line_index] = _blank(lines[line_index])
                offset += sum(len(line) for line in lines[index : index + consumed])
                index += consumed
                continue
        offset += len(lines[index])
        index += 1
    return "".join(output), definitions


def _markdown_links(text: str) -> tuple[list[tuple[str, int]], list[tuple[str, int]]]:
    without_definitions, definitions = _definitions(_mask_blocks(text))
    visible = _mask_inline_code(without_definitions)
    links = list(definitions.values())
    unresolved: list[tuple[str, int]] = []

    def scan(start: int, stop: int) -> None:
        index = start
        while index < stop:
            if visible[index] == "<" and not _escaped(visible, index):
                tag = re.match(r"</?[A-Za-z][A-Za-z0-9:-]*(?:\s+[^>]*?)?/?>", visible[index:stop])
                if tag:
                    index += tag.end()
                    continue
            if visible[index] != "[" or _escaped(visible, index):
                index += 1
                continue
            close = _bracket_end(visible, index)
            if close is None or close >= stop:
                index += 1
                continue
            scan(index + 1, close)
            after = close + 1
            if after < stop and visible[after] == "(":
                parsed = _inline_destination(visible, after)
                if parsed is None or parsed[1] > stop:
                    unresolved.append(("malformed inline link", index))
                    index = after
                    continue
                links.append((parsed[0], index))
                index = parsed[1]
                continue
            ref_start = after
            if ref_start < stop and visible[ref_start] == "[":
                ref_end = _bracket_end(visible, ref_start)
                if ref_end is not None and ref_end < stop:
                    name = visible[ref_start + 1 : ref_end] or visible[index + 1 : close]
                    if _label(name) not in definitions:
                        unresolved.append((f"undefined reference [{name}]", index))
                    index = ref_end + 1
                    continue
            index = after

    scan(0, len(visible))
    return links, unresolved


def _render_heading(value: str, definitions: dict[str, tuple[str, int]]) -> str:
    result: list[str] = []
    index = 0
    while index < len(value):
        if value[index] == "`" and not _escaped(value, index):
            ticks = _matching_ticks(value, index)
            if ticks:
                content_start, end = ticks
                width = content_start - index
                result.append(value[content_start : end - width])
                index = end
                continue
        if value[index] == "[" and not _escaped(value, index):
            close = _bracket_end(value, index)
            if close is not None:
                after = close + 1
                end = None
                if after < len(value) and value[after] == "(":
                    parsed = _inline_destination(value, after)
                    end = parsed[1] if parsed else None
                elif after < len(value) and value[after] == "[":
                    ref_end = _bracket_end(value, after)
                    if ref_end is not None:
                        ref = value[after + 1 : ref_end] or value[index + 1 : close]
                        if _label(ref) in definitions:
                            end = ref_end + 1
                if end is not None:
                    result.append(_render_heading(value[index + 1 : close], definitions))
                    index = end
                    continue
        result.append(value[index])
        index += 1
    return _unescape_markdown(re.sub(r"<[^>]*>", "", "".join(result)))


def _heading_slug(value: str) -> str:
    result = []
    for char in value.lower():
        if char in "-_" or unicodedata.category(char)[0] in "LNM":
            result.append(char)
        elif char.isspace():
            result.append("-")
    return "".join(result)


def _markdown_anchors(text: str) -> set[str]:
    visible, definitions = _definitions(_mask_blocks(text))
    anchors: set[str] = set()
    used: set[str] = set()
    counts: dict[str, int] = {}
    previous = ""
    previous_item_indent: int | None = None
    for original_line in visible.splitlines():
        content = _unquote_container(original_line)
        indent = len(content) - len(content.lstrip(" "))
        item = re.match(r"^ *(?:[-+*]|\d{1,9}[.)])[ \t]+", content)
        line = content[item.end() :] if item else content.lstrip(" ")
        heading = re.match(r"^ {0,3}#{1,6}(?:[ \t]+|$)(.*)$", line)
        if heading:
            title = re.sub(r"[ \t]+#+[ \t]*$", "", heading.group(1))
        elif (
            re.fullmatch(r" {0,3}(?:=+|-+)[ \t]*", line)
            and previous.strip()
            and (previous_item_indent is None or indent >= previous_item_indent)
        ):
            title = previous.strip()
        else:
            previous = line
            previous_item_indent = item.end() if item else None
            continue
        base = _heading_slug(_render_heading(title.strip(), definitions))
        slug = base
        while slug in used:
            counts[base] = counts.get(base, 0) + 1
            slug = f"{base}-{counts[base]}"
        used.add(slug)
        anchors.add(slug)
        previous = ""
        previous_item_indent = None
    for tag in re.findall(r"<[A-Za-z][^>]*>", _mask_inline_code(visible)):
        tag_name = re.match(r"<([A-Za-z][A-Za-z0-9:-]*)", tag).group(1).lower()
        for match in re.finditer(r"""(?:^|\s)(id|name)\s*=\s*(?:"([^"]+)"|'([^']+)'|([^\s>]+))""", tag, re.IGNORECASE):
            if match.group(1).lower() == "name" and tag_name != "a":
                continue
            anchors.add(html.unescape(next(group for group in match.groups()[1:] if group is not None)))
    return anchors


def _check_destination(tree: FileTree, source: Path, destination: str) -> None:
    destination = _unescape_markdown(destination)
    if re.match(r"^[A-Za-z]:", destination) or destination.lower().startswith("file:"):
        raise ConsistencyError(f"absolute local file link is not supported: {destination!r}")
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", destination) or destination.startswith("//"):
        return
    try:
        parsed = urlsplit(destination)
        target_path = unquote(parsed.path, errors="strict")
        fragment = unquote(parsed.fragment, errors="strict")
    except (ValueError, UnicodeError) as error:
        raise ConsistencyError(f"invalid link {destination!r}: {error}") from error
    if "\\" in target_path or "\x00" in target_path:
        raise ConsistencyError(f"invalid local link {destination!r}")
    if not target_path:
        target = source
    elif target_path.startswith("/"):
        target = tree.root / target_path.lstrip("/")
    else:
        target = source.parent / target_path
    requested = Path(os.path.normpath(str(target)))
    target = tree.resolve(requested)
    try:
        target.relative_to(tree.root)
    except ValueError as error:
        raise ConsistencyError(f"local link escapes repository: {destination!r}") from error
    if str(requested).casefold() == str(target).casefold() and str(requested) != str(target):
        raise ConsistencyError(f"local link target has incorrect case: {destination!r}")
    if tree.is_dir(target):
        if not fragment:
            return
        target = target / "README.md"
    if not tree.is_file(target):
        raise ConsistencyError(f"missing local link target: {destination!r}")
    if fragment:
        if target.suffix.lower() not in (".md", ".markdown", ".html", ".htm"):
            raise ConsistencyError(f"cannot verify fragment in non-Markdown/HTML target: {destination!r}")
        if fragment not in _markdown_anchors(tree.read(target)):
            raise ConsistencyError(f"missing fragment #{fragment} in {target}")


def check_markdown(tree: FileTree, paths: list[Path]) -> None:
    errors = []
    for path in paths:
        text = tree.read(path)
        links, unresolved = _markdown_links(text)
        for message, offset in unresolved:
            errors.append(f"{path}:{text.count(chr(10), 0, offset) + 1}: {message}")
        for destination, offset in links:
            try:
                _check_destination(tree, path, destination)
            except ConsistencyError as error:
                errors.append(f"{path}:{text.count(chr(10), 0, offset) + 1}: {error}")
    if errors:
        raise ConsistencyError("\n".join(errors))


def _json_object(text: str, context: str) -> dict:
    def unique_pairs(pairs: list[tuple[str, object]]) -> dict:
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key {key!r}")
            result[key] = value
        return result

    def invalid_constant(value: str) -> None:
        raise ValueError(f"invalid JSON constant {value}")

    try:
        value = json.loads(text, object_pairs_hook=unique_pairs, parse_constant=invalid_constant)
    except (ValueError, RecursionError) as error:
        raise ConsistencyError(f"invalid {context}: {error}") from error
    if not isinstance(value, dict):
        raise ConsistencyError(f"{context} must be a JSON object")
    return value


def parse_marker(text: str, context: str) -> dict:
    starts = list(re.finditer(rf"<!--\s*{re.escape(MARKER_NAME)}(?=\s|-->)", text))
    if len(starts) != 1:
        raise ConsistencyError(f"{context}: expected exactly one {MARKER_NAME} marker")
    start = starts[0].end()
    end = text.find("-->", start)
    if end < 0:
        raise ConsistencyError(f"{context}: unclosed {MARKER_NAME} marker")
    marker = _json_object(text[start:end], f"{context} baseline marker")
    fixed = {
        "marker_version": 1,
        "blender_minimum": "5.2.0",
        "read_only": True,
        "import_operator_count": len(IMPORT_OPERATORS),
        "import_operators": list(IMPORT_OPERATORS),
        "package_members": "in-memory",
        "redistributable_fixtures": "synthetic",
        "exporter": False,
        "native_writer": False,
        "recomp_receipt_consumer": False,
        "receipt_schema_version": 1,
        "visual_gates_passed": False,
        "runtime_gates_passed": False,
    }
    keys = set(fixed) | {"addon_version", "receipt_schema_sha256"}
    if set(marker) != keys:
        raise ConsistencyError(
            f"{context}: baseline marker keys differ; "
            f"missing={sorted(keys - set(marker))}, unexpected={sorted(set(marker) - keys)}"
        )
    for key, expected in fixed.items():
        value = marker[key]
        if type(value) is not type(expected) or value != expected:
            raise ConsistencyError(f"{context}: baseline marker {key} must be {expected!r}")
    version = marker["addon_version"]
    if not isinstance(version, str) or not _SEMVER.fullmatch(version):
        raise ConsistencyError(f"{context}: baseline addon_version must be major.minor.patch")
    digest = marker["receipt_schema_sha256"]
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ConsistencyError(f"{context}: invalid receipt_schema_sha256")
    return marker


def check_schema(tree: FileTree, marker: dict) -> None:
    path = tree.root / SCHEMA_PATH
    schema = _json_object(tree.read(path), str(path))
    properties = schema.get("properties")
    required = schema.get("required")
    version = properties.get("schemaVersion") if isinstance(properties, dict) else None
    if (
        schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema"
        or schema.get("type") != "object"
        or schema.get("additionalProperties") is not False
        or not isinstance(required, list)
        or not all(isinstance(item, str) for item in required)
        or set(required) != {"schemaVersion", "modId", "target", "producer", "exports"}
        or len(required) != 5
        or not isinstance(properties, dict)
        or set(properties) != set(required)
        or not isinstance(version, dict)
        or type(version.get("const")) is not int
        or version["const"] != marker["receipt_schema_version"]
    ):
        raise ConsistencyError(f"{path}: receipt schema must require schemaVersion 1 and the v1 envelope")
    try:
        canonical = json.dumps(
            schema, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    except (TypeError, UnicodeError, ValueError) as error:
        raise ConsistencyError(f"{path}: cannot canonicalize schema: {error}") from error
    digest = hashlib.sha256(canonical).hexdigest()
    if digest != marker["receipt_schema_sha256"]:
        raise ConsistencyError(
            f"{path}: receipt schema fingerprint mismatch "
            f"(marker {marker['receipt_schema_sha256']}, actual {digest})"
        )


def _section(text: str, title: str, context: str) -> str:
    match = re.search(rf"(?m)^##[ \t]+{re.escape(title)}[ \t]*$", text)
    if not match:
        raise ConsistencyError(f"{context}: missing section {title!r}")
    following = re.search(r"(?m)^##[ \t]+", text[match.end() :])
    return text[match.end() : match.end() + following.start()] if following else text[match.end() :]


def check_operator_table(text: str, context: str) -> None:
    lines = text.splitlines()
    header = [
        index
        for index, line in enumerate(lines)
        if re.fullmatch(r"\|\s*Read-only import\s*\|\s*Operator\s*\|\s*", line)
    ]
    if len(header) != 1:
        raise ConsistencyError(f"{context}: expected one read-only operator table")
    index = header[0] + 1
    if index >= len(lines) or not re.fullmatch(r"\|\s*:?-+:?\s*\|\s*:?-+:?\s*\|\s*", lines[index]):
        raise ConsistencyError(f"{context}: malformed operator table header")
    ids = []
    index += 1
    while index < len(lines) and lines[index].lstrip().startswith("|"):
        cells = lines[index].strip().split("|")
        if len(cells) != 4 or not cells[1].strip():
            raise ConsistencyError(f"{context}: malformed operator table row")
        operator = re.fullmatch(r"`([^`]+)`", cells[2].strip())
        if not operator:
            raise ConsistencyError(f"{context}: operator table IDs must be backtick-quoted")
        ids.append(operator.group(1))
        index += 1
    if Counter(ids) != Counter(IMPORT_OPERATORS):
        raise ConsistencyError(
            f"{context}: operator table must list the {len(IMPORT_OPERATORS)} import IDs exactly once"
        )


def _require(pattern: str, value: str, message: str) -> None:
    if not re.search(pattern, " ".join(value.split()), re.IGNORECASE):
        raise ConsistencyError(message)


def _require_paragraph(pattern: str, value: str, message: str) -> None:
    paragraphs = re.split(r"\n[ \t]*\n", value)
    if not any(re.search(pattern, " ".join(part.split()), re.IGNORECASE) for part in paragraphs):
        raise ConsistencyError(message)


def _reject_conflicting_claims(text: str, context: str) -> None:
    prose = " ".join(_mask_blocks(text).split())
    patterns = (
        (r"(?<!no )\b(?:native (?:N3 )?writer|exporter|export operator) "
         r"(?:is|has been) (?:implemented|enabled|registered|available)\b"),
        (r"\b(?:recomp )?stager (?:now |currently |already )?"
         r"(?:consumes|reads|validates|stages) (?:(?:a|an|the|optional|Blender) )*"
         r"`?(?:receipt|n3-blender-export\.json)`?"),
        r"\b(?:optional |Blender )*receipt (?:is|has been) (?:now )?(?:consumed|read|validated|staged)\b",
    )
    if any(re.search(pattern, prose, re.IGNORECASE) for pattern in patterns):
        raise ConsistencyError(f"{context}: conflicting export, writer, or receipt-consumer claim")


def check_claims(documents: dict[str, str], marker: dict) -> None:
    version = re.escape(marker["addon_version"])
    historical = re.escape(HISTORICAL_BASELINE_VERSION)
    if tuple(map(int, marker["addon_version"].split("."))) <= tuple(
        map(int, HISTORICAL_BASELINE_VERSION.split("."))
    ):
        raise ConsistencyError("current candidate must be newer than the historical baseline")
    authoring = _mask_blocks(_section(documents[SCOPED_DOCS[0]], "Status and selected scope", SCOPED_DOCS[0]))
    check_operator_table(authoring, SCOPED_DOCS[0])
    modding_boundary = _mask_blocks(_section(documents[SCOPED_DOCS[1]], "Current boundary", SCOPED_DOCS[1]))
    modding = _mask_blocks(_section(documents[SCOPED_DOCS[1]], "Blender authoring track", SCOPED_DOCS[1]))
    porting = _mask_blocks(_section(documents[SCOPED_DOCS[2]], "Deeper game changes", SCOPED_DOCS[2]))
    status = _mask_blocks(
        _section(
            documents[SCOPED_DOCS[3]],
            f"Blender {HISTORICAL_BASELINE_VERSION} read-only authoring baseline",
            SCOPED_DOCS[3],
        )
    )
    _require_paragraph(
        rf"\b{version}\s+ungated candidate\b.*\bnine read-only imports\b",
        authoring,
        "missing or stale current candidate version or nine-import count",
    )
    _require_paragraph(
        rf"\b{historical}\s+read-only baseline\b.*\beight bounded import operators\b.*"
        r"\bnamed historical baseline\b",
        authoring,
        "missing or stale historical authoring baseline version or eight-import count",
    )
    checks = (
        (authoring, r"\bno exporter or native N3 writer\b", "authoring no-writer claim"),
        (
            authoring,
            r"\bstager does not consume (?:the |optional |Blender )*receipt\b",
            "authoring receipt non-consumption",
        ),
        (modding_boundary, rf"\b{historical}\s+baseline:\s+eight read-only operators\b", "modding capability table"),
        (modding_boundary, r"\bno exporter or receipt consumer\b", "modding receipt table"),
        (modding, r"\bno exporter or native writer exists\b", "modding no-writer claim"),
        (
            modding,
            r"\bstager neither reads nor validates (?:a |the )*`?n3-blender-export\.json`?\b",
            "modding receipt non-consumption",
        ),
        (porting, r"\bno exporter or native writer\b", "porting no-writer claim"),
        (porting, r"\bstager does not consume, validate, or stage a receipt\b", "porting receipt non-consumption"),
        (status, r"\ban exporter, and a native writer are not implemented\b", "status no-writer claim"),
        (status, r"\bdoes not read or validate a receipt\b", "status receipt non-consumption"),
    )
    for section, pattern, description in checks:
        _require(pattern, section, f"missing or stale {description}")
    for section, pattern, description in (
        (modding, rf"\b{historical}\s+baseline\b.*\beight read-only operators\b",
         "modding historical baseline version and operator count"),
        (porting, rf"\b{historical}\s+baseline\b.*\beight read-only import operators\b",
         "porting historical baseline version and operator count"),
        (status, rf"\b{historical}\s+baseline\b.*\beight import operators\b",
         "status historical baseline version and operator count"),
    ):
        _require_paragraph(pattern, section, f"missing or stale {description}")
    for name, section in (
        (SCOPED_DOCS[0], authoring), (SCOPED_DOCS[1], modding_boundary),
        (SCOPED_DOCS[1], modding), (SCOPED_DOCS[2], porting), (SCOPED_DOCS[3], status),
    ):
        _reject_conflicting_claims(section, name)


def check_stager_source(tree: FileTree) -> None:
    # Unknown mod-root reads require review rather than assuming non-consumption.
    path = tree.root / "tools" / "mods.py"
    try:
        module = ast.parse(tree.read(path), filename=str(path))
    except SyntaxError as error:
        raise ConsistencyError(f"{path}: invalid Python: {error}") from error
    for node in ast.walk(module):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str) and
                "n3-blender-export" in node.value.casefold()):
            raise ConsistencyError(
                f"{path}:{node.lineno}: stager references the Blender receipt; "
                "the documented non-consumption claim requires review"
            )
        identifier = (
            node.id if isinstance(node, ast.Name)
            else node.attr if isinstance(node, ast.Attribute)
            else node.name if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            else ""
        )
        if "receipt" in identifier.casefold() or "n3_blender_export" in identifier.casefold():
            raise ConsistencyError(f"{path}:{node.lineno}: stager receipt-related code requires review")
        if isinstance(node, ast.Attribute) and node.attr == "root":
            raise ConsistencyError(f"{path}:{node.lineno}: unverified stager mod-root access")

    functions = [node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == "load_mod"]
    if len(functions) != 1 or not functions[0].args.args or functions[0].args.args[0].arg != "root":
        raise ConsistencyError(f"{path}: cannot verify stager load_mod root access")
    function = functions[0]
    parents = {child: parent for parent in ast.walk(function) for child in ast.iter_child_nodes(parent)}

    def error_message(node: ast.AST) -> bool:
        formatted = parents.get(node)
        joined = parents.get(formatted)
        call = parents.get(joined)
        return (
            isinstance(formatted, ast.FormattedValue)
            and isinstance(joined, ast.JoinedStr)
            and isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id == "ModError"
            and isinstance(parents.get(call), ast.Raise)
        )

    manifest_access = False
    files_access = False
    for node in ast.walk(function):
        if not isinstance(node, ast.Name) or not isinstance(node.ctx, ast.Load):
            continue
        parent = parents.get(node)
        if node.id == "root":
            permitted = error_message(node)
            if isinstance(parent, ast.Attribute) and parent.value is node:
                permitted |= parent.attr == "name" or (
                    parent.attr == "is_dir"
                    and isinstance(parents.get(parent), ast.Call)
                    and parents[parent].func is parent
                )
            elif isinstance(parent, ast.Call) and isinstance(parent.func, ast.Name):
                permitted |= parent.func.id == "_is_link_or_reparse" and parent.args == [node]
                permitted |= parent.func.id == "Mod" and isinstance(parents.get(parent), ast.Return)
            elif (
                isinstance(parent, ast.BinOp)
                and parent.left is node
                and isinstance(parent.op, ast.Div)
                and isinstance(parent.right, ast.Constant)
            ):
                use = parents.get(parent)
                if parent.right.value == "mod.toml" and isinstance(use, ast.Assign):
                    permitted |= (
                        len(use.targets) == 1
                        and isinstance(use.targets[0], ast.Name)
                        and use.targets[0].id == "manifest_path"
                    )
                    manifest_access |= permitted
                elif parent.right.value == "files" and isinstance(use, ast.Call):
                    permitted |= isinstance(use.func, ast.Name) and use.func.id == "_scan_mod_files"
                    files_access |= permitted
            if not permitted:
                raise ConsistencyError(f"{path}:{node.lineno}: unverified stager mod-root access")
        elif node.id == "manifest_path":
            permitted = error_message(node)
            if isinstance(parent, ast.Attribute) and parent.value is node:
                permitted |= parent.attr in {"is_file", "open", "read_text", "read_bytes"}
            elif isinstance(parent, ast.Call) and isinstance(parent.func, ast.Name):
                permitted |= parent.func.id == "_is_link_or_reparse" and parent.args == [node]
            if not permitted:
                raise ConsistencyError(f"{path}:{node.lineno}: unverified stager manifest access")
    if not manifest_access or not files_access:
        raise ConsistencyError(f"{path}: cannot verify stager reads only mod.toml and files/")
    scanners = [node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == "_scan_mod_files"]
    if len(scanners) != 1:
        raise ConsistencyError(f"{path}: cannot verify the stager mod-files scanner")
    for scanner in scanners:
        if any(isinstance(node, ast.Attribute) and node.attr in {"parent", "parents"} for node in ast.walk(scanner)):
            raise ConsistencyError(f"{path}: unverified parent access while scanning mod files")


def check_contract(tree: FileTree) -> None:
    documents = {name: tree.read(tree.root / name) for name in SCOPED_DOCS}
    marker = parse_marker(documents[SCOPED_DOCS[0]], SCOPED_DOCS[0])
    check_claims(documents, marker)
    check_markdown(tree, [tree.root / name for name in SCOPED_DOCS])
    check_schema(tree, marker)
    check_stager_source(tree)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT, help="recomp checkout (default: script's checkout)")
    args = parser.parse_args(argv)
    try:
        check_contract(FileTree(args.root))
    except ConsistencyError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("OK: recomp Blender documents, links, baseline, receipt schema, and non-consumption claims")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
