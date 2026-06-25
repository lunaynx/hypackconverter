#!/usr/bin/env -S poetry run python
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import sys
import urllib.error
import urllib.request
import zipfile
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_BASE_URL = "https://skyblock-api-repo.thatgravyboat.tech/1_21_5/"
REPO_USER_AGENT = "Repolib"
REPO_FILES = (
    "items.min.json",
    "enchantments.min.json",
    "pets.min.json",
    "runes.min.json",
    "potions.min.json",
    "attributes.min.json",
)

ITEM_DEFINITION_PREFIX = "assets/hypixel_skyblock/items/"
SKYBLOCK_ITEM_PREFIX = "assets/skyblock/items/"
STATE_SUFFIXES = (
    "_pulling_0",
    "_pulling_1",
    "_pulling_2",
    "_cast",
    "_in_hand",
    "_ability",
    "_animated",
)
FORMAT_CODE_PATTERN = re.compile(r"\u00a7.")
NON_WORD_PATTERN = re.compile(r"[^a-z0-9]+")
APOSTROPHE_PATTERN = re.compile(r"['\u2019]")
FRAGGED_PREFIX = "\u269a"
RESOURCE_PACK_ID_ALIASES = {
    "adaptive_blade": "stone_blade",
    "adaptive_blade_fragged": "starred_stone_blade",
    "arachnes_calling": "arachne_keeper_fragment",
    "arachnes_fang": "arachne_fang",
    "architects_first_draft": "architect_first_draft",
    "bachelors_rose": "bachelor_rose",
    "bigfoots_bola": "giant_fragment_bigfoot",
    "bonemerang": "bone_boomerang",
    "bonzos_staff": "bonzo_staff",
    "bonzos_staff_fragged": "starred_bonzo_staff",
    "bouqet_of_lies": "bouquet_of_lies",
    "cropshot_chip": "cropshot_garden_chip",
    "daedalus_blade": "daedalus_axe",
    "daedalus_blade_fragged": "starred_daedalus_axe",
    "diamantes_handle": "giant_fragment_diamond",
    "divans_alloy": "divan_alloy",
    "divans_drill": "divan_drill",
    "emperors_skull": "diver_fragment",
    "endstone_blade": "end_stone_sword",
    "felthorn_reaper_fragged": "starred_felthorn_reaper",
    "fragranced_brown_mushroom": "fragranced_brown_mushroom_paste",
    "hunters_knife": "hunter_knife",
    "jerrychine_gun": "jerry_staff",
    "lasr_eye": "giant_fragment_laser",
    "magmafish_bronze": "magma_fish",
    "magmafish_diamond": "magma_fish_diamond",
    "magmafish_gold": "magma_fish_gold",
    "magmafish_silver": "magma_fish_silver",
    "midas_sword_fragged": "starred_midas_sword",
    "necromancers_sword": "necromancer_sword",
    "necrons_blade": "necron_blade",
    "prime_huntaxe": "nex_titanum",
    "reinforced_huntaxe": "cursus_ferae",
    "savage_huntaxe": "apex_praedator",
    "shadow_fury_fragged": "starred_shadow_fury",
    "sharpened_huntaxe": "silva_dominus",
    "soulsteeler_bow": "crypt_bow",
    "spirit_sceptre": "bat_wand",
    "spirit_sceptre_fragged": "starred_bat_wand",
    "spirit_shortbow": "item_spirit_bow",
    "super_sharp_and_stabby_steak_stake": "sharp_steak_stake",
    "tacticians_murder_weapon": "tactician_murder_weapon",
    "tacticians_sword": "tactician_sword",
    "tessalated_ender_pearl": "tessellated_ender_pearl",
    "titanboa_shed": "titanoboa_shed",
    "tool_xp_capsule": "tool_exp_capsule",
    "worn_huntaxe": "venator_genesis",
    "yeti_sword_fragged": "starred_yeti_sword",
    "zombie_solider_cutlass": "zombie_soldier_cutlass",
}


class RepoLoadError(RuntimeError):
    pass


@dataclass(frozen=True)
class ResolvedId:
    path: str
    reason: str


@dataclass
class RepoIndex:
    direct: dict[str, str] = field(default_factory=dict)
    names: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))

    def add_direct(self, source_id: object, target: str) -> None:
        source = str(source_id).strip().lower()
        if source:
            self.direct[source] = target

    def add_name(self, name: object, target: str) -> None:
        text = strip_formatting(component_to_text(name)).strip()
        if text.startswith(FRAGGED_PREFIX):
            normalized = normalize_name(text.removeprefix(FRAGGED_PREFIX))
            if normalized:
                self.names[f"{normalized}_fragged"].add(target)
            return

        normalized = normalize_name(text)
        if normalized:
            self.names[normalized].add(target)

    def resolve(self, stem: str) -> ResolvedId | None:
        cleaned = cleanup_state_suffix(stem.lower())
        if cleaned in self.direct:
            return ResolvedId(self.direct[cleaned], "direct")

        name_matches = self.names.get(cleaned, set())
        if len(name_matches) == 1:
            return ResolvedId(next(iter(name_matches)), "display name")
        if len(name_matches) > 1:
            return ResolvedId("", "ambiguous display-name match")
        return None


def cleanup_state_suffix(stem: str) -> str:
    for suffix in STATE_SUFFIXES:
        if stem.endswith(suffix):
            return stem[: -len(suffix)]
    return stem


def strip_formatting(value: str) -> str:
    return FORMAT_CODE_PATTERN.sub("", value)


def normalize_name(value: str) -> str:
    value = APOSTROPHE_PATTERN.sub("", value)
    normalized = NON_WORD_PATTERN.sub("_", value.casefold()).strip("_")
    return re.sub(r"_+", "_", normalized)


def component_to_text(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        text = value.get("text", "")
        output = text if isinstance(text, str) else ""
        extra = value.get("extra")
        if isinstance(extra, Sequence) and not isinstance(extra, str):
            output += "".join(component_to_text(part) for part in extra)
        return output
    return ""


def fetch_repo_json(filename: str, base_url: str = REPO_BASE_URL) -> Any:
    request = urllib.request.Request(
        f"{base_url}{filename}",
        headers={"User-Agent": REPO_USER_AGENT},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RepoLoadError(f"could not download {filename}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise RepoLoadError(f"could not parse {filename}: {exc}") from exc


def load_repo_index(base_url: str = REPO_BASE_URL) -> RepoIndex:
    try:
        repo_data = {filename: fetch_repo_json(filename, base_url) for filename in REPO_FILES}
    except RepoLoadError:
        raise
    except Exception as exc:
        raise RepoLoadError(f"could not load SkyBlockAPI repo data: {exc}") from exc

    index = RepoIndex()
    add_items(index, repo_data["items.min.json"])
    add_keyed_repo(index, repo_data["enchantments.min.json"], "enchantments", name_fields=("name",))
    add_keyed_repo(index, repo_data["pets.min.json"], "pets", name_fields=("name",))
    add_runes(index, repo_data["runes.min.json"])
    add_keyed_repo(index, repo_data["potions.min.json"], "potions", name_fields=("name",))
    add_attributes(index, repo_data["attributes.min.json"])
    add_resource_pack_aliases(index)
    return index


def add_resource_pack_aliases(index: RepoIndex) -> None:
    for resource_pack_id, custom_data_id in RESOURCE_PACK_ID_ALIASES.items():
        index.add_direct(resource_pack_id, custom_data_id)


def add_items(index: RepoIndex, data: Any) -> None:
    if not isinstance(data, list):
        raise RepoLoadError("items.min.json did not contain an item list")

    for item in data:
        if not isinstance(item, Mapping):
            continue
        components = item.get("components")
        if not isinstance(components, Mapping):
            continue
        custom_data = components.get("minecraft:custom_data")
        if not isinstance(custom_data, Mapping):
            continue
        item_id = custom_data.get("id")
        if not isinstance(item_id, str) or not item_id:
            continue

        target = item_id.lower()
        index.add_direct(item_id, target)
        index.add_name(components.get("minecraft:custom_name", ""), target)


def add_keyed_repo(index: RepoIndex, data: Any, path_prefix: str, *, name_fields: Iterable[str]) -> None:
    if not isinstance(data, Mapping):
        raise RepoLoadError(f"{path_prefix}.min.json did not contain an object")

    for key, value in data.items():
        target_id = str(key).lower()
        target = f"{path_prefix}/{target_id}"
        index.add_direct(key, target)
        if isinstance(value, Mapping):
            index.add_direct(value.get("id", ""), target)
            for field_name in name_fields:
                index.add_name(value.get(field_name, ""), target)


def add_runes(index: RepoIndex, data: Any) -> None:
    if not isinstance(data, Mapping):
        raise RepoLoadError("runes.min.json did not contain an object")

    for key, entries in data.items():
        target = f"runes/{str(key).lower()}"
        index.add_direct(key, target)
        if isinstance(entries, Sequence) and not isinstance(entries, str):
            for entry in entries:
                if isinstance(entry, Mapping):
                    index.add_name(entry.get("name", ""), target)


def add_attributes(index: RepoIndex, data: Any) -> None:
    if not isinstance(data, list):
        raise RepoLoadError("attributes.min.json did not contain an attribute list")

    for attribute in data:
        if not isinstance(attribute, Mapping):
            continue
        shard_id = attribute.get("shard_id")
        if not isinstance(shard_id, str) or not shard_id:
            continue
        target = f"attributes/{shard_id.lower()}"
        index.add_direct(shard_id, target)
        index.add_direct(attribute.get("id", ""), target)
        index.add_name(attribute.get("shard_name", ""), target)
        index.add_name(attribute.get("name", ""), target)


def convert_pack(input_path: Path, index: RepoIndex) -> Path:
    output_path = input_path.with_name(f"{input_path.stem}.cats.zip")
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


def normalize_zip_path(path: str) -> str:
    return path.replace("\\", "/").lstrip("/")


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

    output_path = f"{SKYBLOCK_ITEM_PREFIX}{resolved.path}.json"
    inner_files[output_path] = json.dumps(parsed, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


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
