#!/usr/bin/env -S poetry run python
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from utils import ITEM_DEFINITION_PREFIX, RepoIndex, RepoLoadError, load_repo_index, normalize_zip_path


def generate_model_map(input_path: Path, index: RepoIndex) -> dict[str, str]:
    model_map: dict[str, str] = {}
    with zipfile.ZipFile(input_path, "r") as source_zip:
        for info in source_zip.infolist():
            if info.is_dir():
                continue
            path = normalize_zip_path(info.filename)
            if not path.startswith(ITEM_DEFINITION_PREFIX) or not path.endswith(".json"):
                continue

            resolved = index.resolve(Path(path).stem.lower())
            if resolved is None or not resolved.path:
                continue

            try:
                item_definition = json.loads(source_zip.read(info).decode("utf-8"))
            except UnicodeDecodeError, json.JSONDecodeError:
                continue

            item_model = find_first_item_model(item_definition)
            if item_model is not None:
                model_map[custom_data_key(resolved.path)] = item_model

    return dict(sorted(model_map.items()))


def custom_data_key(resolved_path: str) -> str:
    return resolved_path.rsplit("/", 1)[-1].upper()


def find_first_item_model(value: object) -> str | None:
    if isinstance(value, Mapping):
        model = value.get("model")
        if value.get("type") == "minecraft:model" and isinstance(model, str):
            return model
        if isinstance(model, str):
            return model
        for child in value.values():
            item_model = find_first_item_model(child)
            if item_model is not None:
                return item_model
        return None

    if isinstance(value, Sequence) and not isinstance(value, str):
        for child in value:
            item_model = find_first_item_model(child)
            if item_model is not None:
                return item_model

    return None


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a custom data ID to item model JSON map.")
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
        model_map = generate_model_map(input_path, load_repo_index())
    except (RepoLoadError, OSError, zipfile.BadZipFile, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(model_map, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
