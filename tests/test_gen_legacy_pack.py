from __future__ import annotations

import base64
import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

import gen_legacy_pack
from tests.test_hypackconverter import hypixel_item as api_item
from tests.test_hypackconverter import hypixel_payload, parse_cats
from utils import ResolvedId

PNG_BYTES = b"\x89PNG\r\n\x1a\nfake"


def repo_item(
    custom_data_id: str,
    item_id: str,
    name: str,
    item_model: str | None = None,
    profile: object | None = None,
) -> dict[str, object]:
    components: dict[str, object] = {
        "minecraft:custom_data": {"id": custom_data_id},
        "minecraft:custom_name": {"text": name},
    }
    if item_model is not None:
        components["minecraft:item_model"] = item_model
    if profile is not None:
        components["minecraft:profile"] = profile
    return {
        "id": item_id,
        "components": components,
    }


def texture_profile(url: str) -> dict[str, object]:
    texture_data = {"textures": {"SKIN": {"url": url}}}
    encoded = base64.b64encode(json.dumps(texture_data).encode("utf-8")).decode("ascii")
    return {"properties": [{"name": "textures", "value": encoded}]}


class GenLegacyPackTests(unittest.TestCase):
    def test_load_legacy_repo_adds_resource_pack_aliases(self) -> None:
        index, vanilla_item_models = gen_legacy_pack.load_legacy_repo_from_items(
            [
                repo_item("CROPSHOT_GARDEN_CHIP", "minecraft:paper", "Cropshot", "minecraft:paper"),
                repo_item("TUTORIAL_GARDEN_CHIP", "minecraft:paper", "Tutorial Garden Chip", "minecraft:paper"),
                repo_item("MAGMA_FISH_SILVER", "minecraft:cod", "Magmafish Silver"),
                repo_item("BOUQUET_OF_LIES", "minecraft:diamond_sword", "Bouquet of Lies"),
                repo_item("OTHER_CROPSHOT", "minecraft:paper", "Cropshot Chip"),
            ]
        )

        self.assertEqual(index.resolve("cropshot_chip"), ResolvedId("cropshot_garden_chip", "direct"))
        self.assertEqual(index.resolve("magmafish_silver"), ResolvedId("magma_fish_silver", "direct"))
        self.assertEqual(index.resolve("bouqet_of_lies"), ResolvedId("bouquet_of_lies", "direct"))
        self.assertIn("cropshot_garden_chip", vanilla_item_models)
        self.assertIn("tutorial_garden_chip", vanilla_item_models)
        self.assertIn("magma_fish_silver", vanilla_item_models)
        self.assertIn("bouquet_of_lies", vanilla_item_models)

    def test_build_vanilla_item_models_prefers_item_model_component(self) -> None:
        self.assertEqual(
            gen_legacy_pack.build_vanilla_item_models(
                [
                    repo_item("CUSTOM_GOAT", "minecraft:paper", "Custom Goat", "minecraft:goat_horn"),
                    repo_item("CUSTOM_SWORD", "minecraft:diamond_sword", "Custom Sword"),
                    repo_item("CUSTOM_STICK", "minecraft:paper", "Custom Stick", "minecraft:item/stick"),
                    repo_item("PRISMAPUMP", "minecraft:dark_prismarine", "Prismapump"),
                ]
            ),
            {
                "custom_goat": gen_legacy_pack.LegacyItemModel("minecraft:item/goat_horn"),
                "custom_sword": gen_legacy_pack.LegacyItemModel("minecraft:item/diamond_sword"),
                "custom_stick": gen_legacy_pack.LegacyItemModel("minecraft:item/stick"),
                "prismapump": gen_legacy_pack.LegacyItemModel("minecraft:block/dark_prismarine"),
            },
        )

    def test_load_legacy_repo_uses_hypixel_fallback_items(self) -> None:
        index, vanilla_item_models = gen_legacy_pack.load_legacy_repo_from_items(
            [],
            hypixel_payload(
                [
                    api_item("PROMISING_HOE", "Promising Hoe", "IRON_HOE"),
                    api_item("ZOOM_PICKAXE", "Zoom", "WOOD_PICKAXE"),
                    api_item("SWEEP_AXE", "Sweep Axe", "IRON_AXE"),
                    api_item("RAYGUN", "Raygun", "BOW"),
                ]
            ),
        )

        self.assertEqual(index.resolve("promising_hoe"), ResolvedId("promising_hoe", "direct"))
        self.assertEqual(index.resolve("zoom"), ResolvedId("zoom_pickaxe", "display name"))
        self.assertEqual(index.resolve("sweep_axe"), ResolvedId("sweep_axe", "direct"))
        self.assertEqual(index.resolve("ray_gun"), ResolvedId("raygun", "direct"))
        self.assertEqual(
            vanilla_item_models["promising_hoe"], gen_legacy_pack.LegacyItemModel("minecraft:item/iron_hoe")
        )
        self.assertEqual(
            vanilla_item_models["zoom_pickaxe"], gen_legacy_pack.LegacyItemModel("minecraft:item/wooden_pickaxe")
        )
        self.assertEqual(vanilla_item_models["sweep_axe"], gen_legacy_pack.LegacyItemModel("minecraft:item/iron_axe"))
        self.assertEqual(vanilla_item_models["raygun"], gen_legacy_pack.LegacyItemModel("minecraft:item/bow"))

    def test_build_vanilla_item_models_decodes_player_head_textures(self) -> None:
        texture_url = "http://textures.minecraft.net/texture/abc123"

        self.assertEqual(
            gen_legacy_pack.build_vanilla_item_models(
                [
                    repo_item("HEAD_ITEM", "minecraft:player_head", "Head Item", profile=texture_profile(texture_url)),
                ]
            ),
            {
                "head_item": gen_legacy_pack.LegacyItemModel(
                    "minecraft:item/template_skull",
                    gen_legacy_pack.HeadTexture(
                        url=texture_url,
                        texture_id=f"minecraft:skyblock/heads/{hashlib.sha1(b'abc123').hexdigest()}",
                        pack_path=f"assets/minecraft/textures/entity/skyblock/heads/{hashlib.sha1(b'abc123').hexdigest()}.png",
                    ),
                    True,
                )
            },
        )

    def test_convert_pack_writes_legacy_item_definitions(self) -> None:
        index, vanilla_item_models = gen_legacy_pack.load_legacy_repo_from_items(
            [
                repo_item("LEGEND_ROD", "minecraft:fishing_rod", "Rod of Legends"),
                repo_item("GOAT_PAPER", "minecraft:paper", "Goat Paper", "minecraft:goat_horn"),
            ]
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "84.zip"
            with zipfile.ZipFile(input_path, "w") as pack:
                pack.writestr("pack.mcmeta", json.dumps({"pack": {"pack_format": 84, "description": "Original"}}))
                pack.writestr(
                    "assets/hypixel_skyblock/items/item/fishing/rod/rod_of_legends.json",
                    json.dumps(
                        {
                            "model": {
                                "type": "minecraft:condition",
                                "on_false": {
                                    "type": "minecraft:model",
                                    "model": "hypixel_skyblock:item/fishing/rod/rod_of_legends",
                                },
                                "on_true": {
                                    "type": "minecraft:model",
                                    "model": "hypixel_skyblock:item/fishing/rod/rod_of_legends_cast",
                                },
                            }
                        }
                    ),
                )
                pack.writestr(
                    "assets/hypixel_skyblock/items/item/uncategorized/goat_paper.json",
                    json.dumps(
                        {
                            "model": {
                                "type": "minecraft:model",
                                "model": "hypixel_skyblock:item/uncategorized/goat_paper",
                            }
                        }
                    ),
                )
                pack.writestr("assets/hypixel_skyblock/models/item/unused.json", "{}")

            output_path = gen_legacy_pack.convert_pack(input_path, index, vanilla_item_models)

            self.assertEqual(output_path, Path(temp_dir) / "84.legacy.cats.zip")
            with zipfile.ZipFile(output_path, "r") as output_zip:
                self.assertEqual(set(output_zip.namelist()), {"pack.cats", "pack.mcmeta"})
                files, _entries = parse_cats(output_zip.read("pack.cats"))

            self.assertEqual(
                json.loads(files["assets/skyblock/items/legend_rod.json"]),
                {
                    "model": {
                        "type": "minecraft:condition",
                        "on_false": {
                            "type": "minecraft:model",
                            "model": "minecraft:item/fishing_rod",
                        },
                        "on_true": {
                            "type": "minecraft:model",
                            "model": "minecraft:item/fishing_rod",
                        },
                    }
                },
            )
            self.assertEqual(
                json.loads(files["assets/skyblock/items/goat_paper.json"]),
                {
                    "model": {
                        "type": "minecraft:model",
                        "model": "minecraft:item/goat_horn",
                    }
                },
            )
            self.assertNotIn("assets/hypixel_skyblock/models/item/unused.json", files)

    def test_convert_pack_uses_block_models_for_vanilla_block_items(self) -> None:
        index, vanilla_item_models = gen_legacy_pack.load_legacy_repo_from_items(
            [
                repo_item("PRISMAPUMP", "minecraft:dark_prismarine", "Prismapump"),
            ]
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "84.zip"
            with zipfile.ZipFile(input_path, "w") as pack:
                pack.writestr("pack.mcmeta", json.dumps({"pack": {"pack_format": 84, "description": "Original"}}))
                pack.writestr(
                    "assets/hypixel_skyblock/items/item/uncategorized/prismapump.json",
                    json.dumps(
                        {
                            "model": {
                                "type": "minecraft:model",
                                "model": "hypixel_skyblock:item/uncategorized/prismapump",
                            }
                        }
                    ),
                )

            output_path = gen_legacy_pack.convert_pack(input_path, index, vanilla_item_models)

            with zipfile.ZipFile(output_path, "r") as output_zip:
                files, _entries = parse_cats(output_zip.read("pack.cats"))

            self.assertEqual(
                json.loads(files["assets/skyblock/items/prismapump.json"]),
                {
                    "model": {
                        "type": "minecraft:model",
                        "model": "minecraft:block/dark_prismarine",
                    }
                },
            )

    def test_convert_pack_writes_additional_model_targets(self) -> None:
        index, vanilla_item_models = gen_legacy_pack.load_legacy_repo_from_items(
            [
                repo_item("CROPSHOT_GARDEN_CHIP", "minecraft:paper", "Cropshot", "minecraft:paper"),
                repo_item("TUTORIAL_GARDEN_CHIP", "minecraft:paper", "Tutorial Garden Chip", "minecraft:paper"),
            ]
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "84.zip"
            with zipfile.ZipFile(input_path, "w") as pack:
                pack.writestr("pack.mcmeta", json.dumps({"pack": {"pack_format": 84, "description": "Original"}}))
                pack.writestr(
                    "assets/hypixel_skyblock/items/item/island_relevant/garden/chips/cropshot_chip.json",
                    json.dumps(
                        {
                            "model": {
                                "type": "minecraft:model",
                                "model": "hypixel_skyblock:item/island_relevant/garden/chips/cropshot_chip",
                            }
                        }
                    ),
                )

            output_path = gen_legacy_pack.convert_pack(input_path, index, vanilla_item_models)

            with zipfile.ZipFile(output_path, "r") as output_zip:
                files, _entries = parse_cats(output_zip.read("pack.cats"))

            expected = {"model": {"type": "minecraft:model", "model": "minecraft:item/paper"}}
            self.assertEqual(json.loads(files["assets/skyblock/items/cropshot_garden_chip.json"]), expected)
            self.assertEqual(json.loads(files["assets/skyblock/items/tutorial_garden_chip.json"]), expected)

    def test_convert_pack_writes_player_head_item_definitions_and_textures(self) -> None:
        texture_url = "http://textures.minecraft.net/texture/abc123"
        index, vanilla_item_models = gen_legacy_pack.load_legacy_repo_from_items(
            [
                repo_item("HEAD_ITEM", "minecraft:player_head", "Head Item", profile=texture_profile(texture_url)),
            ]
        )
        fetched_urls: list[str] = []

        def fetch_texture(url: str) -> bytes:
            fetched_urls.append(url)
            return PNG_BYTES

        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "84.zip"
            with zipfile.ZipFile(input_path, "w") as pack:
                pack.writestr("pack.mcmeta", json.dumps({"pack": {"pack_format": 84, "description": "Original"}}))
                pack.writestr(
                    "assets/hypixel_skyblock/items/item/uncategorized/head_item.json",
                    json.dumps(
                        {
                            "model": {
                                "type": "minecraft:model",
                                "model": "hypixel_skyblock:item/uncategorized/head_item",
                            }
                        }
                    ),
                )

            output_path = gen_legacy_pack.convert_pack(input_path, index, vanilla_item_models, fetch_texture)

            with zipfile.ZipFile(output_path, "r") as output_zip:
                files, _entries = parse_cats(output_zip.read("pack.cats"))

            texture_hash = hashlib.sha1(b"abc123").hexdigest()
            texture_path = f"assets/minecraft/textures/entity/skyblock/heads/{texture_hash}.png"
            self.assertEqual(fetched_urls, [texture_url])
            self.assertEqual(files[texture_path], PNG_BYTES)
            self.assertEqual(
                json.loads(files["assets/skyblock/items/head_item.json"]),
                gen_legacy_pack.player_head_item_definition(
                    gen_legacy_pack.HeadTexture(
                        url=texture_url,
                        texture_id=f"minecraft:skyblock/heads/{texture_hash}",
                        pack_path=texture_path,
                    )
                ),
            )

    def test_convert_pack_uses_player_head_model_without_texture_data(self) -> None:
        index, vanilla_item_models = gen_legacy_pack.load_legacy_repo_from_items(
            [
                repo_item("HEAD_ITEM", "minecraft:player_head", "Head Item"),
            ]
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "84.zip"
            with zipfile.ZipFile(input_path, "w") as pack:
                pack.writestr("pack.mcmeta", json.dumps({"pack": {"pack_format": 84, "description": "Original"}}))
                pack.writestr(
                    "assets/hypixel_skyblock/items/item/uncategorized/head_item.json",
                    json.dumps(
                        {
                            "model": {
                                "type": "minecraft:model",
                                "model": "hypixel_skyblock:item/uncategorized/head_item",
                            }
                        }
                    ),
                )

            output_path = gen_legacy_pack.convert_pack(input_path, index, vanilla_item_models, lambda _url: PNG_BYTES)

            with zipfile.ZipFile(output_path, "r") as output_zip:
                files, _entries = parse_cats(output_zip.read("pack.cats"))

            self.assertEqual(
                json.loads(files["assets/skyblock/items/head_item.json"]),
                gen_legacy_pack.player_head_item_definition(),
            )
            self.assertFalse(any(path.startswith("assets/minecraft/textures/entity/skyblock/heads/") for path in files))


if __name__ == "__main__":
    unittest.main()
