from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
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
RISING_SUN_SUFFIX = " of the Rising Sun"
RESOURCE_PACK_ID_ALIASES = {
    "bouqet_of_lies": "bouquet_of_lies",
    "cropshot_chip": "cropshot_garden_chip",
    "endstone_blade": "end_stone_sword",
    "fragranced_brown_mushroom": "fragranced_brown_mushroom_paste",
    "jerrychine_gun": "jerry_staff",
    "lasr_eye": "giant_fragment_laser",
    "magmafish_bronze": "magma_fish",
    "magmafish_diamond": "magma_fish_diamond",
    "magmafish_gold": "magma_fish_gold",
    "magmafish_silver": "magma_fish_silver",
    "prime_huntaxe": "nex_titanum",
    "reinforced_huntaxe": "cursus_ferae",
    "savage_huntaxe": "apex_praedator",
    "sharpened_huntaxe": "silva_dominus",
    "soulsteeler_bow": "crypt_bow",
    "super_sharp_and_stabby_steak_stake": "sharp_steak_stake",
    "tessalated_ender_pearl": "tessellated_ender_pearl",
    "titanboa_shed": "titanoboa_shed",
    "tool_xp_capsule": "tool_exp_capsule",
    "worn_huntaxe": "venator_genesis",
    "zombie_solider_cutlass": "zombie_soldier_cutlass",
}
ADDITIONAL_MODEL_TARGETS = {
    "cropshot_garden_chip": ("tutorial_garden_chip",),
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
        for direct_candidate in direct_id_candidates(cleaned):
            if direct_candidate in self.direct:
                return ResolvedId(self.direct[direct_candidate], "direct")

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


def direct_id_candidates(stem: str) -> Iterable[str]:
    seen: set[str] = set()
    for candidate in (stem, *drop_possessive_s_variants(stem)):
        if candidate not in seen:
            seen.add(candidate)
            yield candidate

    if not stem.endswith("_fragged"):
        return

    base = stem[: -len("_fragged")]
    for candidate in (base, *drop_possessive_s_variants(base)):
        starred_candidate = f"starred_{candidate}"
        if starred_candidate not in seen:
            seen.add(starred_candidate)
            yield starred_candidate


def drop_possessive_s_variants(stem: str) -> Iterable[str]:
    parts = stem.split("_")
    for index, part in enumerate(parts):
        if len(part) <= 2 or not part.endswith("s"):
            continue
        variant_parts = [*parts]
        variant_parts[index] = part[:-1]
        yield "_".join(variant_parts)


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


def expand_resolved_paths(path: str) -> tuple[str, ...]:
    return (path, *ADDITIONAL_MODEL_TARGETS.get(path, ()))


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
        custom_name = components.get("minecraft:custom_name", "")
        index.add_name(custom_name, target)
        add_rising_sun_alias(index, item_id, custom_name, target)


def add_rising_sun_alias(index: RepoIndex, item_id: str, name: object, target: str) -> None:
    text = strip_formatting(component_to_text(name)).strip()
    if not text.endswith(RISING_SUN_SUFFIX):
        return

    normalized = normalize_name(text)
    if not normalized:
        return

    if item_id.startswith("GENERALS_"):
        index.add_direct(f"{normalized}_2", target)
    else:
        index.add_direct(normalized, target)


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


def normalize_zip_path(path: str) -> str:
    return path.replace("\\", "/").lstrip("/")
