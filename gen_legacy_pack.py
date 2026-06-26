#!/usr/bin/env -S poetry run python
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gen_modern_pack import read_input_pack_mcmeta, warn_unmapped, write_cats
from utils import (
    ITEM_DEFINITION_PREFIX,
    REPO_USER_AGENT,
    RepoIndex,
    RepoLoadError,
    add_items,
    add_resource_pack_aliases,
    expand_resolved_paths,
    fetch_repo_json,
    normalize_zip_path,
)

LEGACY_REPO_BASE_URL = (
    "https://raw.githubusercontent.com/SkyblockAPI/Repo/" "09706d22700d034907f2b3a37034bbe49edd7030/cloudflare/1_21_5/"
)
SKYBLOCK_ITEM_PREFIX = "assets/skyblock/items/"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
VANILLA_BLOCK_MODEL_ITEMS = {
    "minecraft:dark_prismarine",
}


@dataclass(frozen=True)
class HeadTexture:
    url: str
    texture_id: str
    pack_path: str


@dataclass(frozen=True)
class LegacyItemModel:
    model_reference: str
    head_texture: HeadTexture | None = None
    is_player_head: bool = False


def load_legacy_repo(base_url: str = LEGACY_REPO_BASE_URL) -> tuple[RepoIndex, dict[str, LegacyItemModel]]:
    items = fetch_repo_json("items.min.json", base_url)
    return load_legacy_repo_from_items(items)


def load_legacy_repo_from_items(items: object) -> tuple[RepoIndex, dict[str, LegacyItemModel]]:
    if not isinstance(items, list):
        raise RepoLoadError("items.min.json did not contain an item list")

    index = RepoIndex()
    add_items(index, items)
    add_resource_pack_aliases(index)
    return index, build_vanilla_item_models(items)


def build_vanilla_item_models(items: Sequence[object]) -> dict[str, LegacyItemModel]:
    vanilla_item_models: dict[str, LegacyItemModel] = {}
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

        item_id = item.get("id")
        if item_id == "minecraft:player_head":
            head_texture = decode_head_texture(components.get("minecraft:profile"))
            vanilla_item_models[custom_data_id.lower()] = LegacyItemModel(
                "minecraft:item/template_skull", head_texture, True
            )
            continue

        vanilla_item_model = components.get("minecraft:item_model")
        if not isinstance(vanilla_item_model, str):
            vanilla_item_model = item_id
        if isinstance(vanilla_item_model, str):
            vanilla_model_reference = vanilla_item_model_reference(vanilla_item_model)
            if vanilla_model_reference is not None:
                vanilla_item_models[custom_data_id.lower()] = LegacyItemModel(vanilla_model_reference)

    return vanilla_item_models


def vanilla_item_model_reference(identifier: str) -> str | None:
    if not identifier.startswith("minecraft:"):
        return None

    namespace, path = identifier.split(":", 1)
    if identifier in VANILLA_BLOCK_MODEL_ITEMS:
        return f"{namespace}:block/{path}"
    if path.startswith("item/"):
        return identifier
    return f"{namespace}:item/{path}"


def decode_head_texture(profile: object) -> HeadTexture | None:
    if not isinstance(profile, Mapping):
        return None

    properties = profile.get("properties")
    if not isinstance(properties, Sequence) or isinstance(properties, str):
        return None

    for property_value in properties:
        if not isinstance(property_value, Mapping):
            continue
        if property_value.get("name") != "textures":
            continue

        encoded_texture = property_value.get("value")
        if not isinstance(encoded_texture, str):
            continue

        try:
            decoded = base64.b64decode(encoded_texture, validate=True)
            texture_data = json.loads(decoded.decode("utf-8"))
        except ValueError, UnicodeDecodeError, json.JSONDecodeError:
            return None

        skin = texture_data.get("textures", {}).get("SKIN") if isinstance(texture_data, Mapping) else None
        url = skin.get("url") if isinstance(skin, Mapping) else None
        if not isinstance(url, str) or not url:
            return None

        texture_hash = texture_hash_from_url(url)
        texture_id = f"minecraft:skyblock/heads/{hashlib.sha1(texture_hash.encode('utf-8')).hexdigest()}"
        texture_path = texture_id.split(":", 1)[1]
        return HeadTexture(
            url=url, texture_id=texture_id, pack_path=f"assets/minecraft/textures/entity/{texture_path}.png"
        )

    return None


def texture_hash_from_url(url: str) -> str:
    path = urllib.parse.urlparse(url).path.rstrip("/")
    texture_hash = path.rsplit("/", 1)[-1]
    if texture_hash:
        return texture_hash
    return hashlib.sha1(url.encode("utf-8")).hexdigest()


def fetch_texture_png(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": REPO_USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = response.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RepoLoadError(f"could not download head texture {url}: {exc}") from exc

    if not data.startswith(PNG_SIGNATURE):
        raise RepoLoadError(f"downloaded head texture was not a PNG: {url}")
    return data


def convert_pack(
    input_path: Path,
    index: RepoIndex,
    vanilla_item_models: Mapping[str, LegacyItemModel],
    texture_fetcher: Callable[[str], bytes] = fetch_texture_png,
) -> Path:
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

            convert_item_definition(
                path, source_zip.read(info), index, vanilla_item_models, inner_files, texture_fetcher
            )

    cats_data = write_cats(inner_files)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as output_zip:
        output_zip.writestr("pack.cats", cats_data)
        output_zip.writestr("pack.mcmeta", pack_mcmeta)

    return output_path


def convert_item_definition(
    path: str,
    data: bytes,
    index: RepoIndex,
    vanilla_item_models: Mapping[str, LegacyItemModel],
    inner_files: dict[str, bytes],
    texture_fetcher: Callable[[str], bytes] = fetch_texture_png,
) -> None:
    resolved = index.resolve(Path(path).stem.lower())
    if resolved is None:
        warn_unmapped(path, "missing mapping")
        return
    if not resolved.path:
        warn_unmapped(path, resolved.reason)
        return

    legacy_item_model = vanilla_item_models.get(resolved.path)
    if legacy_item_model is None:
        warn_unmapped(path, "missing vanilla item model")
        return

    try:
        parsed = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        warn_unmapped(path, f"invalid JSON: {exc}")
        return

    if legacy_item_model.is_player_head:
        if legacy_item_model.head_texture is not None:
            add_head_texture(inner_files, legacy_item_model.head_texture, texture_fetcher)
        legacy_definition = player_head_item_definition(legacy_item_model.head_texture)
    else:
        legacy_definition = replace_hypixel_identifiers(parsed, legacy_item_model.model_reference)

    encoded = json.dumps(legacy_definition, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    for output_id in expand_resolved_paths(resolved.path):
        output_path = f"{SKYBLOCK_ITEM_PREFIX}{output_id}.json"
        inner_files[output_path] = encoded


def add_head_texture(
    inner_files: dict[str, bytes], head_texture: HeadTexture, texture_fetcher: Callable[[str], bytes]
) -> None:
    if head_texture.pack_path not in inner_files:
        inner_files[head_texture.pack_path] = texture_fetcher(head_texture.url)


def player_head_item_definition(head_texture: HeadTexture | None = None) -> dict[str, object]:
    model = (
        {
            "type": "minecraft:head",
            "kind": "player",
            "texture": head_texture.texture_id,
        }
        if head_texture is not None
        else {
            "type": "minecraft:player_head",
        }
    )
    return {
        "model": {
            "type": "minecraft:special",
            "base": "minecraft:item/template_skull",
            "model": model,
            "transformation": {
                "left_rotation": [1.0, 0.0, 0.0, -0.0],
                "right_rotation": [0.0, 0.0, 0.0, 1.0],
                "scale": [1.0, 1.0, 1.0],
                "translation": [0.5, 0.0, 0.5],
            },
        }
    }


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
