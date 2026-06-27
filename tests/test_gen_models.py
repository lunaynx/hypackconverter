from __future__ import annotations

import io
import json
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import gen_models
import gen_modern_pack as hypackconverter
from tests.test_hypackconverter import item


class GenModelsTests(unittest.TestCase):
    def test_generate_model_map_uses_resolved_custom_data_ids(self) -> None:
        index = hypackconverter.RepoIndex()
        hypackconverter.add_items(
            index,
            [
                item("SQUEAKY_MOUSEMAT", "Squeaky Mousemat"),
                item("LEGEND_ROD", "Rod of Legends"),
            ],
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "pack.zip"
            with zipfile.ZipFile(input_path, "w") as pack:
                pack.writestr(
                    "assets/hypixel_skyblock/items/item/uncategorized/squeaky_mousemat.json",
                    json.dumps(
                        {
                            "model": {
                                "type": "minecraft:model",
                                "model": "hypixel_skyblock:item/uncategorized/squeaky_mousemat",
                            }
                        }
                    ),
                )
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
                    "assets/hypixel_skyblock/items/item/fishing/rod/rod_of_legends_cast.json",
                    json.dumps(
                        {
                            "model": {
                                "type": "minecraft:model",
                                "model": "hypixel_skyblock:item/fishing/rod/rod_of_legends_cast",
                            }
                        }
                    ),
                )
                pack.writestr(
                    "assets/hypixel_skyblock/items/item/fishing/rod/rod_of_legends_ability.json",
                    json.dumps(
                        {
                            "model": {
                                "type": "minecraft:model",
                                "model": "hypixel_skyblock:item/fishing/rod/rod_of_legends_ability",
                            }
                        }
                    ),
                )
                pack.writestr(
                    "assets/hypixel_skyblock/items/item/uncategorized/unknown.json",
                    json.dumps({"model": {"type": "minecraft:model", "model": "hypixel_skyblock:item/unknown"}}),
                )
                pack.writestr("assets/hypixel_skyblock/textures/item/uncategorized/squeaky_mousemat.png", b"png")

            self.assertEqual(
                gen_models.generate_model_map(input_path, index),
                {
                    "LEGEND_ROD": [
                        "hypixel_skyblock:item/fishing/rod/rod_of_legends",
                        "hypixel_skyblock:item/fishing/rod/rod_of_legends_ability",
                        "hypixel_skyblock:item/fishing/rod/rod_of_legends_cast",
                    ],
                    "SQUEAKY_MOUSEMAT": ["hypixel_skyblock:item/uncategorized/squeaky_mousemat"],
                },
            )

    def test_generate_model_map_can_use_display_names(self) -> None:
        index = hypackconverter.RepoIndex()
        hypackconverter.add_items(
            index,
            [
                item("SQUEAKY_MOUSEMAT", "\u00a7aSqueaky Mousemat"),
                item("LEGEND_ROD", "\u00a76Rod of Legends"),
            ],
        )
        index.add_direct("UNKNOWN_NAME", "unknown_name")

        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "pack.zip"
            with zipfile.ZipFile(input_path, "w") as pack:
                pack.writestr(
                    "assets/hypixel_skyblock/items/item/uncategorized/squeaky_mousemat.json",
                    json.dumps(
                        {
                            "model": {
                                "type": "minecraft:model",
                                "model": "hypixel_skyblock:item/uncategorized/squeaky_mousemat",
                            }
                        }
                    ),
                )
                pack.writestr(
                    "assets/hypixel_skyblock/items/item/fishing/rod/rod_of_legends.json",
                    json.dumps(
                        {
                            "model": {
                                "type": "minecraft:model",
                                "model": "hypixel_skyblock:item/fishing/rod/rod_of_legends",
                            }
                        }
                    ),
                )
                pack.writestr(
                    "assets/hypixel_skyblock/items/item/uncategorized/unknown_name.json",
                    json.dumps(
                        {
                            "model": {
                                "type": "minecraft:model",
                                "model": "hypixel_skyblock:item/uncategorized/unknown_name",
                            }
                        }
                    ),
                )

            self.assertEqual(
                gen_models.generate_model_map(input_path, index, use_names=True),
                {
                    "Rod of Legends": ["hypixel_skyblock:item/fishing/rod/rod_of_legends"],
                    "Squeaky Mousemat": ["hypixel_skyblock:item/uncategorized/squeaky_mousemat"],
                    "UNKNOWN_NAME": ["hypixel_skyblock:item/uncategorized/unknown_name"],
                },
            )

    def test_main_prints_pretty_json_to_stdout(self) -> None:
        index = hypackconverter.RepoIndex()
        hypackconverter.add_items(index, [item("SQUEAKY_MOUSEMAT", "Squeaky Mousemat")])

        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "pack.zip"
            with zipfile.ZipFile(input_path, "w") as pack:
                pack.writestr(
                    "assets/hypixel_skyblock/items/item/uncategorized/squeaky_mousemat.json",
                    json.dumps(
                        {
                            "model": {
                                "type": "minecraft:model",
                                "model": "hypixel_skyblock:item/uncategorized/squeaky_mousemat",
                            }
                        }
                    ),
                )

            stdout = io.StringIO()
            with mock.patch("gen_models.load_repo_index", return_value=index), redirect_stdout(stdout):
                exit_code = gen_models.main([str(input_path)])

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            stdout.getvalue(),
            '{\n  "SQUEAKY_MOUSEMAT": [\n    "hypixel_skyblock:item/uncategorized/squeaky_mousemat"\n  ]\n}\n',
        )

    def test_main_names_option_prints_display_names_to_stdout(self) -> None:
        index = hypackconverter.RepoIndex()
        hypackconverter.add_items(index, [item("SQUEAKY_MOUSEMAT", "Squeaky Mousemat")])

        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "pack.zip"
            with zipfile.ZipFile(input_path, "w") as pack:
                pack.writestr(
                    "assets/hypixel_skyblock/items/item/uncategorized/squeaky_mousemat.json",
                    json.dumps(
                        {
                            "model": {
                                "type": "minecraft:model",
                                "model": "hypixel_skyblock:item/uncategorized/squeaky_mousemat",
                            }
                        }
                    ),
                )

            stdout = io.StringIO()
            with mock.patch("gen_models.load_repo_index", return_value=index), redirect_stdout(stdout):
                exit_code = gen_models.main(["--names", str(input_path)])

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            stdout.getvalue(),
            '{\n  "Squeaky Mousemat": [\n    "hypixel_skyblock:item/uncategorized/squeaky_mousemat"\n  ]\n}\n',
        )

    def test_generate_model_map_writes_additional_model_targets(self) -> None:
        index = hypackconverter.RepoIndex()
        hypackconverter.add_resource_pack_aliases(index)

        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "pack.zip"
            with zipfile.ZipFile(input_path, "w") as pack:
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

            self.assertEqual(
                gen_models.generate_model_map(input_path, index),
                {
                    "CROPSHOT_GARDEN_CHIP": ["hypixel_skyblock:item/island_relevant/garden/chips/cropshot_chip"],
                    "TUTORIAL_GARDEN_CHIP": ["hypixel_skyblock:item/island_relevant/garden/chips/cropshot_chip"],
                },
            )

    def test_generate_model_map_keeps_separate_item_ids_out_of_base_array(self) -> None:
        index = hypackconverter.RepoIndex()
        hypackconverter.add_items(
            index,
            [
                item("YETI_SWORD", "Yeti Sword"),
                item("STARRED_YETI_SWORD", "\u269a Yeti Sword"),
            ],
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "pack.zip"
            with zipfile.ZipFile(input_path, "w") as pack:
                pack.writestr(
                    "assets/hypixel_skyblock/items/item/island_relevant/winter/weapons/yeti_sword.json",
                    json.dumps(
                        {
                            "model": {
                                "type": "minecraft:model",
                                "model": "hypixel_skyblock:item/island_relevant/winter/weapons/yeti_sword",
                            }
                        }
                    ),
                )
                pack.writestr(
                    "assets/hypixel_skyblock/items/item/island_relevant/winter/weapons/yeti_sword_fragged.json",
                    json.dumps(
                        {
                            "model": {
                                "type": "minecraft:model",
                                "model": "hypixel_skyblock:item/island_relevant/winter/weapons/yeti_sword_fragged",
                            }
                        }
                    ),
                )

            self.assertEqual(
                gen_models.generate_model_map(input_path, index),
                {
                    "STARRED_YETI_SWORD": ["hypixel_skyblock:item/island_relevant/winter/weapons/yeti_sword_fragged"],
                    "YETI_SWORD": ["hypixel_skyblock:item/island_relevant/winter/weapons/yeti_sword"],
                },
            )

    def test_find_first_item_model_prefers_base_model_over_state_variants(self) -> None:
        self.assertEqual(
            gen_models.find_first_item_model(
                {
                    "model": {
                        "type": "condition",
                        "property": "selected",
                        "on_true": {
                            "type": "range_dispatch",
                            "property": "cooldown",
                            "fallback": {
                                "type": "model",
                                "model": "hypixel_skyblock:item/uncategorized/artisanal_shortbow_pulling_2",
                            },
                            "entries": [
                                {
                                    "model": {
                                        "type": "model",
                                        "model": "hypixel_skyblock:item/uncategorized/artisanal_shortbow_pulling_1",
                                    },
                                    "threshold": 0.2,
                                },
                                {
                                    "model": {
                                        "type": "model",
                                        "model": "hypixel_skyblock:item/uncategorized/artisanal_shortbow",
                                    },
                                    "threshold": 0.8,
                                },
                            ],
                        },
                        "on_false": {
                            "type": "model",
                            "model": "hypixel_skyblock:item/uncategorized/artisanal_shortbow",
                        },
                    }
                }
            ),
            "hypixel_skyblock:item/uncategorized/artisanal_shortbow",
        )

        self.assertEqual(
            gen_models.find_first_item_model(
                {
                    "model": {
                        "type": "condition",
                        "on_false": {
                            "type": "model",
                            "model": "hypixel_skyblock:item/uncategorized/hurricane_bow",
                        },
                        "on_true": {
                            "type": "range_dispatch",
                            "entries": [
                                {
                                    "model": {
                                        "type": "model",
                                        "model": "hypixel_skyblock:item/uncategorized/hurricane_bow_pulling_2",
                                    },
                                    "threshold": 0.9,
                                }
                            ],
                        },
                    }
                }
            ),
            "hypixel_skyblock:item/uncategorized/hurricane_bow",
        )


if __name__ == "__main__":
    unittest.main()
