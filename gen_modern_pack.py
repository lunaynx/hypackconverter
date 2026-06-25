#!/usr/bin/env -S poetry run python
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from utils import (
    APOSTROPHE_PATTERN,
    FORMAT_CODE_PATTERN,
    FRAGGED_PREFIX,
    ITEM_DEFINITION_PREFIX,
    NON_WORD_PATTERN,
    REPO_BASE_URL,
    REPO_FILES,
    REPO_USER_AGENT,
    RESOURCE_PACK_ID_ALIASES,
    SKYBLOCK_ITEM_PREFIX,
    STATE_SUFFIXES,
    RepoIndex,
    RepoLoadError,
    ResolvedId,
    add_attributes,
    add_items,
    add_keyed_repo,
    add_resource_pack_aliases,
    add_runes,
    cleanup_state_suffix,
    component_to_text,
    direct_id_candidates,
    drop_possessive_s_variants,
    expand_resolved_paths,
    fetch_repo_json,
    load_repo_index,
    normalize_name,
    normalize_zip_path,
    strip_formatting,
)


def convert_pack(input_path: Path, index: RepoIndex) -> Path:
    output_path = input_path.with_name(f"{input_path.stem}.modern.cats.zip")
    pack_mcmeta = build_pack_mcmeta(read_input_pack_mcmeta(input_path), input_path.stem)
    inner_files: dict[str, bytes] = {"pack.mcmeta": pack_mcmeta}

    with zipfile.ZipFile(input_path, "r") as source_zip:
        for info in source_zip.infolist():
            if info.is_dir():
                continue
            path = normalize_zip_path(info.filename)
            if not path or path == "pack.mcmeta":
                continue
            data = source_zip.read(info)
            if path.startswith(ITEM_DEFINITION_PREFIX):
                convert_item_definition(path, data, index, inner_files)
            else:
                inner_files[path] = data

    cats_data = write_cats(inner_files)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as output_zip:
        output_zip.writestr("pack.cats", cats_data)
        output_zip.writestr("pack.mcmeta", pack_mcmeta)

    return output_path


def convert_item_definition(path: str, data: bytes, index: RepoIndex, inner_files: dict[str, bytes]) -> None:
    stem = Path(path).stem.lower()
    resolved = index.resolve(stem)
    if resolved is None:
        warn_unmapped(path, "missing mapping")
        return
    if not resolved.path:
        warn_unmapped(path, resolved.reason)
        return

    try:
        parsed = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        warn_unmapped(path, f"invalid JSON: {exc}")
        return

    encoded = json.dumps(parsed, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    for output_id in expand_resolved_paths(resolved.path):
        output_path = f"{SKYBLOCK_ITEM_PREFIX}{output_id}.json"
        inner_files[output_path] = encoded


def warn_unmapped(path: str, reason: str) -> None:
    print(f"Warning: could not map {path} ({reason})", file=sys.stderr)


def read_input_pack_mcmeta(input_path: Path) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(input_path, "r") as source_zip:
            raw = source_zip.read("pack.mcmeta")
    except KeyError, zipfile.BadZipFile:
        return {}

    try:
        parsed = json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError, json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def build_pack_mcmeta(existing: Mapping[str, Any], version: str) -> bytes:
    pack = existing.get("pack", {})
    pack_object = dict(pack) if isinstance(pack, Mapping) else {}
    pack_object.setdefault("pack_format", 84)
    pack_object["description"] = "Hypixel SkyBlock Alpha converted for Catharsis"

    metadata = dict(existing)
    metadata["pack"] = pack_object
    metadata["catharsis:pack/v1"] = {
        "id": "hypixel_alpha_converted",
        "version": version,
        "dependencies": {
            "catharsis": ">=1.0.0-beta.17",
        },
    }
    return json.dumps(metadata, indent=2, ensure_ascii=False).encode("utf-8")


@dataclass
class CatsFile:
    name: str
    payload: bytes
    offset: int = 0
    size: int = 0


@dataclass
class CatsDirectory:
    name: str
    entries: dict[str, CatsEntry] = field(default_factory=dict)


CatsEntry = CatsDirectory | CatsFile


def write_cats(files: Mapping[str, bytes]) -> bytes:
    root = CatsDirectory("")
    for path, payload in files.items():
        add_cats_file(root, path, payload)

    data_section = bytearray()
    seen_payloads: dict[bytes, tuple[int, int]] = {}
    assign_payload_offsets(root, data_section, seen_payloads)

    header = bytearray(b"CATS")
    header.append(1)
    write_u16(header, len(root.entries))
    for entry in sorted(root.entries.values(), key=lambda item: item.name):
        serialize_cats_entry(header, entry)
    return bytes(header + data_section)


def add_cats_file(root: CatsDirectory, path: str, payload: bytes) -> None:
    normalized = normalize_zip_path(path)
    parts = normalized.split("/")
    if any(part == "" for part in parts):
        raise ValueError(f"invalid CATS path: {path}")

    directory = root
    for part in parts[:-1]:
        validate_cats_name(part)
        existing = directory.entries.get(part)
        if existing is None:
            next_directory = CatsDirectory(part)
            directory.entries[part] = next_directory
            directory = next_directory
        elif isinstance(existing, CatsDirectory):
            directory = existing
        else:
            raise ValueError(f"file path conflicts with directory: {path}")

    filename = parts[-1]
    validate_cats_name(filename)
    directory.entries[filename] = CatsFile(filename, payload)


def validate_cats_name(name: str) -> None:
    encoded = name.encode("ascii")
    if not encoded or len(encoded) > 255 or name == "..":
        raise ValueError(f"invalid CATS filename: {name!r}")
    if any(byte < 0x21 or byte > 0x7E or byte in (ord("/"), ord("\\")) for byte in encoded):
        raise ValueError(f"invalid CATS filename: {name!r}")


def assign_payload_offsets(
    directory: CatsDirectory,
    data_section: bytearray,
    seen_payloads: dict[bytes, tuple[int, int]],
) -> None:
    for entry in sorted(directory.entries.values(), key=lambda item: item.name):
        if isinstance(entry, CatsDirectory):
            assign_payload_offsets(entry, data_section, seen_payloads)
            continue

        digest = hashlib.sha256(entry.payload).digest()
        if digest in seen_payloads:
            entry.offset, entry.size = seen_payloads[digest]
            continue

        compressed = gzip.compress(entry.payload, compresslevel=9, mtime=0)
        entry.offset = len(data_section)
        entry.size = len(compressed)
        data_section.extend(compressed)
        seen_payloads[digest] = (entry.offset, entry.size)


def serialize_cats_entry(output: bytearray, entry: CatsEntry) -> None:
    if isinstance(entry, CatsDirectory):
        output.append(1)
        write_cats_name(output, entry.name)
        write_u16(output, len(entry.entries))
        for child in sorted(entry.entries.values(), key=lambda item: item.name):
            serialize_cats_entry(output, child)
        return

    output.append(0)
    write_cats_name(output, entry.name)
    write_u32(output, entry.offset)
    write_u32(output, entry.size)
    output.append(0xFE)


def write_cats_name(output: bytearray, name: str) -> None:
    validate_cats_name(name)
    encoded = name.encode("ascii")
    output.append(len(encoded))
    output.extend(encoded)


def write_u16(output: bytearray, value: int) -> None:
    if value > 0xFFFF:
        raise ValueError("CATS directory contains too many entries")
    output.extend(value.to_bytes(2, "big"))


def write_u32(output: bytearray, value: int) -> None:
    if value > 0xFFFFFFFF:
        raise ValueError("CATS archive is too large")
    output.extend(value.to_bytes(4, "big"))


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert a Hypixel SkyBlock Alpha resource pack to Catharsis.")
    parser.add_argument("zip_path", type=Path, nargs=1, metavar="pack.zip")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    input_path = args.zip_path[0]
    if input_path.suffix.lower() != ".zip":
        print(f"error: expected a .zip input, got {input_path}", file=sys.stderr)
        return 2
    if not input_path.is_file():
        print(f"error: input file does not exist: {input_path}", file=sys.stderr)
        return 2

    try:
        index = load_repo_index()
        output_path = convert_pack(input_path, index)
    except (RepoLoadError, OSError, zipfile.BadZipFile, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"Wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
