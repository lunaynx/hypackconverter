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
import hypackconverter
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
                    "assets/hypixel_skyblock/items/item/uncategorized/unknown.json",
                    json.dumps({"model": {"type": "minecraft:model", "model": "hypixel_skyblock:item/unknown"}}),
                )
                pack.writestr("assets/hypixel_skyblock/textures/item/uncategorized/squeaky_mousemat.png", b"png")

            self.assertEqual(
                gen_models.generate_model_map(input_path, index),
                {
                    "LEGEND_ROD": "hypixel_skyblock:item/fishing/rod/rod_of_legends",
                    "SQUEAKY_MOUSEMAT": "hypixel_skyblock:item/uncategorized/squeaky_mousemat",
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
            '{\n  "SQUEAKY_MOUSEMAT": "hypixel_skyblock:item/uncategorized/squeaky_mousemat"\n}\n',
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
