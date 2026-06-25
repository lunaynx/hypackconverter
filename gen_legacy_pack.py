#!/usr/bin/env -S poetry run python
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from gen_modern_pack import read_input_pack_mcmeta, warn_unmapped, write_cats
from utils import ITEM_DEFINITION_PREFIX, RepoIndex, RepoLoadError, add_items, fetch_repo_json, normalize_zip_path

LEGACY_REPO_BASE_URL = (
    "https://raw.githubusercontent.com/SkyblockAPI/Repo/" "09706d22700d034907f2b3a37034bbe49edd7030/cloudflare/1_21_5/"
)
SKYBLOCK_ITEM_PREFIX = "assets/skyblock/items/"


def load_legacy_repo(base_url: str = LEGACY_REPO_BASE_URL) -> tuple[RepoIndex, dict[str, str]]:
    items = fetch_repo_json("items.min.json", base_url)
    return load_legacy_repo_from_items(items)


def load_legacy_repo_from_items(items: object) -> tuple[RepoIndex, dict[str, str]]:
    if not isinstance(items, list):
        raise RepoLoadError("items.min.json did not contain an item list")

    index = RepoIndex()
    add_items(index, items)
    return index, build_vanilla_item_models(items)


def build_vanilla_item_models(items: Sequence[object]) -> dict[str, str]:
    vanilla_item_models: dict[str, str] = {}
    for item in items:
        if not isinstance(item, Mapping):
            continue

        components = item.get("components")
        if not isinstance(components, Mapping):
            continue

        custom_data = components.get("minecraft:custom_data")
        if not isinstance(custom_data, Mapping):
            continue

        custom_data_id = custom_data.get("id")
        if not isinstance(custom_data_id, str) or not custom_data_id:
            continue

        vanilla_item_model = components.get("minecraft:item_model")
        if not isinstance(vanilla_item_model, str):
            vanilla_item_model = item.get("id")
        if isinstance(vanilla_item_model, str) and vanilla_item_model.startswith("minecraft:"):
            vanilla_item_models[custom_data_id.lower()] = vanilla_item_model

    return vanilla_item_models


def convert_pack(input_path: Path, index: RepoIndex, vanilla_item_models: Mapping[str, str]) -> Path:
    output_path = input_path.with_name(f"{input_path.stem}.legacy.cats.zip")
    pack_mcmeta = build_pack_mcmeta(read_input_pack_mcmeta(input_path), input_path.stem)
    inner_files: dict[str, bytes] = {"pack.mcmeta": pack_mcmeta}

    with zipfile.ZipFile(input_path, "r") as source_zip:
        for info in source_zip.infolist():
            if info.is_dir():
                continue

            path = normalize_zip_path(info.filename)
            if not path.startswith(ITEM_DEFINITION_PREFIX) or not path.endswith(".json"):
                continue

            convert_item_definition(path, source_zip.read(info), index, vanilla_item_models, inner_files)

    cats_data = write_cats(inner_files)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as output_zip:
        output_zip.writestr("pack.cats", cats_data)
        output_zip.writestr("pack.mcmeta", pack_mcmeta)

    return output_path


def convert_item_definition(
    path: str,
    data: bytes,
    index: RepoIndex,
    vanilla_item_models: Mapping[str, str],
    inner_files: dict[str, bytes],
) -> None:
    resolved = index.resolve(Path(path).stem.lower())
    if resolved is None:
        warn_unmapped(path, "missing mapping")
        return
    if not resolved.path:
        warn_unmapped(path, resolved.reason)
        return

    vanilla_item_model = vanilla_item_models.get(resolved.path)
    if vanilla_item_model is None:
        warn_unmapped(path, "missing vanilla item model")
        return

    try:
        parsed = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        warn_unmapped(path, f"invalid JSON: {exc}")
        return

    legacy_definition = replace_hypixel_identifiers(parsed, vanilla_item_model)
    output_path = f"{SKYBLOCK_ITEM_PREFIX}{resolved.path}.json"
    inner_files[output_path] = json.dumps(legacy_definition, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def replace_hypixel_identifiers(value: object, replacement: str) -> object:
    if isinstance(value, str):
        return replacement if value.startswith("hypixel_skyblock:") else value
    if isinstance(value, list):
        return [replace_hypixel_identifiers(item, replacement) for item in value]
    if isinstance(value, dict):
        return {key: replace_hypixel_identifiers(item, replacement) for key, item in value.items()}
    return value


def build_pack_mcmeta(existing: Mapping[str, Any], version: str) -> bytes:
    pack = existing.get("pack", {})
    pack_object = dict(pack) if isinstance(pack, Mapping) else {}
    pack_object.setdefault("pack_format", 84)
    pack_object["description"] = "Hypixel SkyBlock Alpha legacy item models for Catharsis"

    metadata = dict(existing)
    metadata["pack"] = pack_object
    metadata["catharsis:pack/v1"] = {
        "id": "hypixel_alpha_legacy",
        "version": version,
        "dependencies": {
            "catharsis": ">=1.0.0-beta.17",
        },
    }
    return json.dumps(metadata, indent=2, ensure_ascii=False).encode("utf-8")


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert a Hypixel SkyBlock Alpha resource pack to legacy models.")
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
        index, vanilla_item_models = load_legacy_repo()
        output_path = convert_pack(input_path, index, vanilla_item_models)
    except (RepoLoadError, OSError, zipfile.BadZipFile, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"Wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
