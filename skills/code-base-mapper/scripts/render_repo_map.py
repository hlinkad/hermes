#!/usr/bin/env python3
"""Render starter .repo-map/map.md and .repo-map/index.md artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


PACKAGE_METADATA_NAMES = {
    "build.gradle",
    "build.gradle.kts",
    "cargo.toml",
    "gemfile",
    "go.mod",
    "package.json",
    "pipfile",
    "pom.xml",
    "pyproject.toml",
    "setup.cfg",
    "setup.py",
}


def insert_path(tree: dict, parts: list[str], record: dict) -> None:
    node = tree
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = record


def describe_dir(name: str, path: str) -> str:
    lower = name.lower()
    if lower in {"src", "source", "app", "lib"}:
        return "Contains runtime source code for this area of the repository."
    if lower in {"test", "tests", "spec", "specs"}:
        return "Contains executable tests that verify repository behavior."
    if lower in {"script", "scripts", "bin"}:
        return "Contains executable helper scripts and command entry points."
    if lower in {"config", ".github"} or "config" in lower:
        return "Contains configuration used by tooling, automation, or runtime setup."
    return f"Contains executable or configuration files for `{path}`."


def describe_file(record: dict) -> str:
    path = record["path"]
    name = Path(path).name.lower()
    kind = record.get("kind", "file")
    if name in PACKAGE_METADATA_NAMES:
        return "Defines package metadata, scripts, dependencies, or build settings."
    if "/tests/" in f"/{path}" or path.startswith("tests/"):
        return "Provides executable test coverage for repository behavior."
    if path.startswith("scripts/") or "/scripts/" in path:
        return "Provides an executable helper used by local development or automation."
    if kind == "config":
        return "Configures repository tooling, automation, or runtime behavior."
    if kind == "executable":
        return "Provides an executable entry point or helper command."
    return "Provides source code used by this repository's runtime or tests."


def render_tree(node: dict, prefix: str = "", path_prefix: str = "") -> list[str]:
    lines: list[str] = []
    keys = sorted(node)
    for index, key in enumerate(keys):
        value = node[key]
        is_last = index == len(keys) - 1
        connector = "`-- " if is_last else "|-- "
        child_prefix = "    " if is_last else "|   "
        current_path = f"{path_prefix}/{key}" if path_prefix else key
        if isinstance(value, dict) and "path" not in value:
            lines.append(f"{prefix}{connector}{key}/ - {describe_dir(key, current_path)}")
            lines.extend(render_tree(value, prefix + child_prefix, current_path))
        else:
            lines.append(f"{prefix}{connector}{key} - {describe_file(value)}")
    return lines


def render_map(manifest: dict) -> str:
    repo_name = Path(manifest.get("repo_root", "repository")).name or "repository"
    tree: dict = {}
    for record in manifest.get("included_files", []):
        insert_path(tree, record["path"].split("/"), record)
    lines = ["root/"]
    lines.extend(render_tree(tree))
    return "\n".join(
        [
            "# Repository Map",
            "",
            f"Generated from executable/code and configuration files in `{repo_name}`.",
            "",
            "```text",
            *lines,
            "```",
            "",
        ]
    )


def render_index(symbols: dict | None) -> str:
    rows = []
    for symbol in (symbols or {}).get("symbols", []):
        source = symbol["path"]
        if symbol.get("line"):
            source = f"{source}:{symbol['line']}"
        rows.append(
            "| `{name}` | {kind} | `{source}` | [map.md](map.md) `{path}` | Seeded symbol; verify and refine. |".format(
                name=symbol["name"],
                kind=symbol["kind"],
                source=source,
                path=symbol["path"],
            )
        )
    if not rows:
        rows.append("| _No symbols detected_ | note | _n/a_ | [map.md](map.md) | Inspect source files and add verified symbols. |")
    return "\n".join(
        [
            "# Repository Index",
            "",
            "Map: [map.md](map.md)",
            "",
            "| Symbol | Kind | Source | Map Reference | Notes |",
            "| --- | --- | --- | --- | --- |",
            *rows,
            "",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="preflight_inventory.json")
    parser.add_argument("--symbols", type=Path, help="symbol_seeds.json")
    parser.add_argument("--output-dir", type=Path, help="defaults beside manifest")
    parser.add_argument("--overwrite", action="store_true", help="replace existing map.md and index.md")
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text())
    symbols = json.loads(args.symbols.read_text()) if args.symbols and args.symbols.exists() else None
    output_dir = args.output_dir or args.manifest.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    outputs = {
        output_dir / "map.md": render_map(manifest),
        output_dir / "index.md": render_index(symbols),
    }
    for path, content in outputs.items():
        if path.exists() and not args.overwrite:
            print(f"kept existing {path}")
            continue
        path.write_text(content)
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
