from __future__ import annotations

import gzip
import io
import json
import tempfile
import unittest
import urllib.error
import urllib.request
import zipfile
from contextlib import redirect_stderr
from pathlib import Path
from typing import Any
from unittest import mock

import hypackconverter


def repo_payloads(items: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "items.min.json": (
            items
            if items is not None
            else [
                item("CACTUS_KNIFE_3", "\u00a7aCactus Knife"),
                item("THEORETICAL_HOE_WARTS_3", "\u00a76Newton Nether Warts Hoe"),
                item("LEGEND_ROD", "\u00a76Rod of Legends"),
                item("TREECAPITATOR_AXE", "\u00a76Treecapitator"),
                item("GOBLIN_EGG_BLUE", "\u00a79Blue Goblin Egg"),
            ]
        ),
        "enchantments.min.json": {"ABSORB": {"id": "ABSORB", "name": "Absorb"}},
        "pets.min.json": {"AMMONITE": {"id": "AMMONITE", "name": "Ammonite"}},
        "runes.min.json": {"ANTLERS": [{"name": "\u00a76\u25c6 Antlers Rune III"}]},
        "potions.min.json": {"POTION_ABSORPTION": {"name": "Absorption"}},
        "attributes.min.json": [
            {
                "id": "ACCESSORY_SIZE",
                "shard_id": "SHARD_HIDEONRING",
                "shard_name": "Hideonring Shard",
                "name": "Accessory Size",
            }
        ],
    }


def item(item_id: str, name: str) -> dict[str, Any]:
    return {
        "id": "minecraft:player_head",
        "components": {
            "minecraft:custom_data": {"id": item_id},
            "minecraft:custom_name": {"text": name},
        },
    }


class FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.payload


def mocked_urlopen(payloads: dict[str, Any]) -> mock.Mock:
    def open_request(request: urllib.request.Request, timeout: int = 0) -> FakeResponse:
        assert timeout == 30
        assert request.get_header("User-agent") == hypackconverter.REPO_USER_AGENT
        filename = request.full_url.rsplit("/", 1)[-1]
        return FakeResponse(json.dumps(payloads[filename]).encode("utf-8"))

    return mock.Mock(side_effect=open_request)


def parse_cats(data: bytes) -> tuple[dict[str, bytes], dict[str, tuple[int, int, int]]]:
    stream = io.BytesIO(data)
    assert stream.read(4) == b"CATS"
    assert read_u8(stream) == 1
    entries: dict[str, tuple[int, int, int]] = {}
    files: dict[str, bytes] = {}
    read_entries(stream, "", read_u16(stream), entries)
    data_section = stream.read()
    for path, (offset, size, compression) in entries.items():
        payload = data_section[offset : offset + size]
        files[path] = gzip.decompress(payload) if compression == 0xFE else payload
    return files, entries


def read_entries(stream: io.BytesIO, prefix: str, count: int, entries: dict[str, tuple[int, int, int]]) -> None:
    for _ in range(count):
        entry_type = read_u8(stream)
        name = stream.read(read_u8(stream)).decode("ascii")
        path = f"{prefix}{name}"
        if entry_type == 1:
            read_entries(stream, f"{path}/", read_u16(stream), entries)
        else:
            entries[path] = (read_u32(stream), read_u32(stream), read_u8(stream))


def read_u8(stream: io.BytesIO) -> int:
    return int.from_bytes(stream.read(1), "big")


def read_u16(stream: io.BytesIO) -> int:
    return int.from_bytes(stream.read(2), "big")


def read_u32(stream: io.BytesIO) -> int:
    return int.from_bytes(stream.read(4), "big")


class RepoLoadingTests(unittest.TestCase):
    def test_load_repo_sends_user_agent_and_parses_all_shapes(self) -> None:
        opener = mocked_urlopen(repo_payloads())
        with mock.patch("urllib.request.urlopen", opener):
            index = hypackconverter.load_repo_index("https://example.test/")

        self.assertEqual(opener.call_count, len(hypackconverter.REPO_FILES))
        self.assertEqual(index.direct["cactus_knife_3"], "cactus_knife_3")
        self.assertEqual(index.direct["absorb"], "enchantments/absorb")
        self.assertEqual(index.direct["ammonite"], "pets/ammonite")
        self.assertEqual(index.direct["antlers"], "runes/antlers")
        self.assertEqual(index.direct["potion_absorption"], "potions/potion_absorption")
        self.assertEqual(index.direct["shard_hideonring"], "attributes/shard_hideonring")

    def test_load_repo_fails_cleanly_on_http_error(self) -> None:
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("offline")):
            with self.assertRaisesRegex(hypackconverter.RepoLoadError, "could not download items.min.json"):
                hypackconverter.load_repo_index("https://example.test/")

    def test_load_repo_fails_cleanly_on_json_error(self) -> None:
        with mock.patch("urllib.request.urlopen", return_value=FakeResponse(b"{")):
            with self.assertRaisesRegex(hypackconverter.RepoLoadError, "could not parse items.min.json"):
                hypackconverter.load_repo_index("https://example.test/")


class IdResolutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.index = hypackconverter.RepoIndex()
        hypackconverter.add_items(self.index, repo_payloads()["items.min.json"])

    def test_direct_ids(self) -> None:
        self.assertEqual(self.index.resolve("cactus_knife_3"), hypackconverter.ResolvedId("cactus_knife_3", "direct"))
        self.assertEqual(
            self.index.resolve("theoretical_hoe_warts_3"),
            hypackconverter.ResolvedId("theoretical_hoe_warts_3", "direct"),
        )

    def test_display_name_fallbacks(self) -> None:
        self.assertEqual(self.index.resolve("rod_of_legends"), hypackconverter.ResolvedId("legend_rod", "display name"))
        self.assertEqual(
            self.index.resolve("treecapitator"),
            hypackconverter.ResolvedId("treecapitator_axe", "display name"),
        )
        self.assertEqual(
            self.index.resolve("blue_goblin_egg"),
            hypackconverter.ResolvedId("goblin_egg_blue", "display name"),
        )

    def test_ambiguous_names_skip_instead_of_guessing(self) -> None:
        index = hypackconverter.RepoIndex()
        hypackconverter.add_items(index, [item("FIRST_ID", "Same Name"), item("SECOND_ID", "Same Name")])

        self.assertEqual(index.resolve("same_name"), hypackconverter.ResolvedId("", "ambiguous display-name match"))

    def test_state_suffix_stripping_does_not_corrupt_numeric_ids(self) -> None:
        self.assertEqual(self.index.resolve("cactus_knife_3"), hypackconverter.ResolvedId("cactus_knife_3", "direct"))
        self.assertEqual(
            self.index.resolve("rod_of_legends_cast"),
            hypackconverter.ResolvedId("legend_rod", "display name"),
        )


class ConversionTests(unittest.TestCase):
    def test_conversion_archive_output_and_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "84.zip"
            with zipfile.ZipFile(input_path, "w") as pack:
                pack.writestr("pack.mcmeta", json.dumps({"pack": {"pack_format": 84, "description": "Original"}}))
                pack.writestr(
                    "assets/hypixel_skyblock/items/item/jacob/cactus_knife_3.json",
                    json.dumps({"model": {"type": "minecraft:model", "model": "hypixel_skyblock:item/a"}}),
                )
                pack.writestr(
                    "assets/hypixel_skyblock/items/item/fishing/rod/rod_of_legends.json",
                    json.dumps({"model": {"type": "minecraft:model", "model": "hypixel_skyblock:item/shared"}}),
                )
                pack.writestr(
                    "assets/hypixel_skyblock/items/item/fishing/rod/unknown.json",
                    json.dumps({"model": {"type": "minecraft:model", "model": "hypixel_skyblock:item/unknown"}}),
                )
                pack.writestr("assets/hypixel_skyblock/models/item/a.json", b"same-payload")
                pack.writestr("assets/hypixel_skyblock/textures/item/a.png", b"same-payload")
                pack.writestr("assets/minecraft/lang/en_us.json", b'{"hello":"world"}')

            index = hypackconverter.RepoIndex()
            hypackconverter.add_items(index, repo_payloads()["items.min.json"])

            stderr = io.StringIO()
            with redirect_stderr(stderr):
                output_path = hypackconverter.convert_pack(input_path, index)

            self.assertEqual(output_path, Path(temp_dir) / "84.cats.zip")
            self.assertIn(
                "Warning: could not map assets/hypixel_skyblock/items/item/fishing/rod/unknown.json (missing mapping)",
                stderr.getvalue(),
            )

            with zipfile.ZipFile(output_path, "r") as output_zip:
                self.assertEqual(set(output_zip.namelist()), {"pack.cats", "pack.mcmeta"})
                outer_mcmeta = json.loads(output_zip.read("pack.mcmeta"))
                cats_data = output_zip.read("pack.cats")

            self.assertEqual(outer_mcmeta["pack"]["description"], "Hypixel SkyBlock Alpha converted for Catharsis")
            self.assertEqual(outer_mcmeta["catharsis:pack/v1"]["version"], "84")
            self.assertEqual(outer_mcmeta["catharsis:pack/v1"]["dependencies"]["catharsis"], ">=1.0.0-beta.17")

            files, entries = parse_cats(cats_data)
            self.assertEqual(json.loads(files["pack.mcmeta"]), outer_mcmeta)
            self.assertEqual(files["assets/hypixel_skyblock/models/item/a.json"], b"same-payload")
            self.assertEqual(files["assets/hypixel_skyblock/textures/item/a.png"], b"same-payload")
            self.assertEqual(files["assets/minecraft/lang/en_us.json"], b'{"hello":"world"}')
            self.assertEqual(
                json.loads(files["assets/skyblock/items/cactus_knife_3.json"]),
                {"type": "minecraft:model", "model": "hypixel_skyblock:item/a"},
            )
            self.assertEqual(
                json.loads(files["assets/skyblock/items/legend_rod.json"]),
                {"type": "minecraft:model", "model": "hypixel_skyblock:item/shared"},
            )
            self.assertNotIn("assets/skyblock/items/unknown.json", files)
            self.assertEqual(
                entries["assets/hypixel_skyblock/models/item/a.json"][0],
                entries["assets/hypixel_skyblock/textures/item/a.png"][0],
            )


if __name__ == "__main__":
    unittest.main()
