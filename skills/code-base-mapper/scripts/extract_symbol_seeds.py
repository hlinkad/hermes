#!/usr/bin/env python3
"""Extract best-effort symbol seeds for .repo-map/index.md generation."""

from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11 fallback
    tomllib = None


JS_TS_EXTENSIONS = {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"}


def add(symbols: list[dict], path: str, kind: str, name: str, line: int | None = None) -> None:
    if not name:
        return
    record = {"path": path, "kind": kind, "name": name}
    if line:
        record["line"] = line
    symbols.append(record)


def python_symbols(path: Path, rel: str) -> list[dict]:
    symbols: list[dict] = []
    try:
        tree = ast.parse(path.read_text(errors="ignore"))
    except SyntaxError:
        return symbols
    except OSError:
        return symbols

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            add(symbols, rel, "class", node.name, node.lineno)
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    add(symbols, rel, "method", f"{node.name}.{child.name}", child.lineno)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            decorators = [getattr(decorator, "attr", "") for decorator in node.decorator_list]
            route_like = any(name in {"route", "get", "post", "put", "patch", "delete"} for name in decorators)
            add(symbols, rel, "route-handler" if route_like else "function", node.name, node.lineno)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    add(symbols, rel, "exported-constant", target.id, node.lineno)
    return symbols


def regex_symbols(path: Path, rel: str) -> list[dict]:
    symbols: list[dict] = []
    try:
        lines = path.read_text(errors="ignore").splitlines()
    except OSError:
        return symbols

    suffix = path.suffix.lower()
    patterns: list[tuple[str, str]] = []
    if suffix in JS_TS_EXTENSIONS:
        patterns = [
            ("class", r"\bexport\s+(?:default\s+)?class\s+([A-Za-z_$][\w$]*)|\bclass\s+([A-Za-z_$][\w$]*)"),
            ("function", r"\bexport\s+(?:async\s+)?function\s+([A-Za-z_$][\w$]*)|\bfunction\s+([A-Za-z_$][\w$]*)"),
            ("function", r"\bexport\s+const\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\(?[^=]*=>"),
            ("exported-constant", r"\bexport\s+const\s+([A-Za-z_$][\w$]*)\s*="),
            ("route-handler", r"\b(?:router|app)\.(get|post|put|patch|delete)\s*\("),
        ]
    elif suffix == ".go":
        patterns = [
            ("function", r"^func\s+([A-Z_a-z]\w*)\s*\("),
            ("method", r"^func\s+\([^)]+\)\s+([A-Z_a-z]\w*)\s*\("),
            ("type", r"^type\s+([A-Z_a-z]\w*)\s+(?:struct|interface)\b"),
        ]
    elif suffix == ".rs":
        patterns = [
            ("function", r"\b(?:pub\s+)?fn\s+([A-Z_a-z]\w*)\s*\("),
            ("type", r"\b(?:pub\s+)?(?:struct|enum|trait)\s+([A-Z_a-z]\w*)\b"),
        ]
    elif suffix in {".java", ".kt", ".kts", ".cs", ".scala"}:
        patterns = [
            ("class", r"\b(?:public\s+)?(?:class|interface|enum|object)\s+([A-Z_a-z]\w*)\b"),
            ("method", r"\b(?:public|private|protected|internal|static|\s)+[\w<>\[\]?]+\s+([A-Z_a-z]\w*)\s*\([^;]*\)\s*\{?"),
        ]
    elif suffix == ".rb":
        patterns = [
            ("class", r"^\s*class\s+([A-Z]\w*)"),
            ("module", r"^\s*module\s+([A-Z]\w*)"),
            ("function", r"^\s*def\s+([A-Z_a-z]\w*[!?=]?)"),
        ]
    elif suffix == ".php":
        patterns = [
            ("class", r"\bclass\s+([A-Z_a-z]\w*)\b"),
            ("function", r"\bfunction\s+([A-Z_a-z]\w*)\s*\("),
        ]
    elif suffix in {".sh", ".bash", ".zsh", ".fish"}:
        patterns = [
            ("function", r"^\s*(?:function\s+)?([A-Z_a-z][\w-]*)\s*\(\s*\)"),
            ("function", r"^\s*function\s+([A-Z_a-z][\w-]*)\b"),
        ]

    for line_number, line in enumerate(lines, start=1):
        for kind, pattern in patterns:
            match = re.search(pattern, line)
            if not match:
                continue
            groups = [group for group in match.groups() if group]
            name = groups[-1] if groups else match.group(0)
            if kind == "route-handler":
                name = f"{name.upper()} route"
            add(symbols, rel, kind, name, line_number)
    return symbols


def package_symbols(path: Path, rel: str) -> list[dict]:
    if path.name.lower() == "pyproject.toml":
        return pyproject_symbols(path, rel)
    if path.name.lower() != "package.json":
        return []
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    symbols: list[dict] = []
    scripts = data.get("scripts", {})
    if isinstance(scripts, dict):
        for name in sorted(scripts):
            add(symbols, rel, "cli-command", f"npm script:{name}")
    return symbols


def pyproject_symbols(path: Path, rel: str) -> list[dict]:
    if tomllib is None:
        return []
    try:
        data = tomllib.loads(path.read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return []
    symbols: list[dict] = []
    project = data.get("project", {})
    scripts = project.get("scripts", {}) if isinstance(project, dict) else {}
    if isinstance(scripts, dict):
        for name in sorted(scripts):
            add(symbols, rel, "cli-command", f"python script:{name}")
    return symbols


def extract(manifest: dict) -> dict:
    repo = Path(manifest["repo_root"])
    symbols: list[dict] = []
    for item in manifest.get("included_files", []):
        rel = item["path"]
        path = repo / rel
        suffix = path.suffix.lower()
        symbols.extend(package_symbols(path, rel))
        if suffix == ".py":
            symbols.extend(python_symbols(path, rel))
        else:
            symbols.extend(regex_symbols(path, rel))
    symbols.sort(key=lambda item: (item["path"], item.get("line", 0), item["kind"], item["name"]))
    return {
        "schema_version": 1,
        "repo_root": manifest.get("repo_root"),
        "source_manifest": "preflight_inventory.json",
        "symbols": symbols,
        "totals": {"symbols": len(symbols)},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="preflight_inventory.json")
    parser.add_argument("--output", type=Path, help="output path; defaults beside manifest")
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text())
    output = args.output or args.manifest.parent / "symbol_seeds.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(extract(manifest), indent=2) + "\n")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
