from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

import gen_legacy_pack
from tests.test_hypackconverter import parse_cats


def repo_item(custom_data_id: str, item_id: str, name: str, item_model: str | None = None) -> dict[str, object]:
    components: dict[str, object] = {
        "minecraft:custom_data": {"id": custom_data_id},
        "minecraft:custom_name": {"text": name},
    }
    if item_model is not None:
        components["minecraft:item_model"] = item_model
    return {
        "id": item_id,
        "components": components,
    }


class GenLegacyPackTests(unittest.TestCase):
    def test_build_vanilla_item_models_prefers_item_model_component(self) -> None:
        self.assertEqual(
            gen_legacy_pack.build_vanilla_item_models(
                [
                    repo_item("CUSTOM_GOAT", "minecraft:paper", "Custom Goat", "minecraft:goat_horn"),
                    repo_item("CUSTOM_SWORD", "minecraft:diamond_sword", "Custom Sword"),
                ]
            ),
            {
                "custom_goat": "minecraft:goat_horn",
                "custom_sword": "minecraft:diamond_sword",
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
                            "model": "minecraft:fishing_rod",
                        },
                        "on_true": {
                            "type": "minecraft:model",
                            "model": "minecraft:fishing_rod",
                        },
                    }
                },
            )
            self.assertEqual(
                json.loads(files["assets/skyblock/items/goat_paper.json"]),
                {
                    "model": {
                        "type": "minecraft:model",
                        "model": "minecraft:goat_horn",
                    }
                },
            )
            self.assertNotIn("assets/hypixel_skyblock/models/item/unused.json", files)


if __name__ == "__main__":
    unittest.main()
