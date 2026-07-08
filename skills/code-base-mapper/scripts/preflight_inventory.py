#!/usr/bin/env python3
"""Create a metadata-only inventory for code-base-mapper.

The script reads filesystem metadata and streams files for line counts, but it
does not print source contents. Its JSON output is safe to load into an agent
context for partitioning and planning.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import stat
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


GENERATED_DIR_NAMES = {
    ".cache",
    ".git",
    ".hg",
    ".mypy_cache",
    ".next",
    ".nuxt",
    ".pytest_cache",
    ".repo-map",
    ".ruff_cache",
    ".svn",
    ".svelte-kit",
    ".tox",
    ".turbo",
    ".venv",
    "__pycache__",
    "bower_components",
    "build",
    "coverage",
    "dist",
    "env",
    "node_modules",
    "out",
    "target",
    "vendor",
    "venv",
}

DOC_DIR_NAMES = {
    "doc",
    "docs",
    "documentation",
    "guide",
    "guides",
    "manual",
    "manuals",
    "wiki",
}

DOC_EXTENSIONS = {
    ".adoc",
    ".md",
    ".mdx",
    ".rst",
    ".txt",
}

SOURCE_EXTENSIONS = {
    ".astro",
    ".bash",
    ".c",
    ".cc",
    ".cljs",
    ".clj",
    ".cpp",
    ".cs",
    ".csh",
    ".cxx",
    ".dart",
    ".erl",
    ".ex",
    ".exs",
    ".fish",
    ".fs",
    ".fsx",
    ".go",
    ".h",
    ".hpp",
    ".hrl",
    ".html",
    ".java",
    ".js",
    ".jsx",
    ".kt",
    ".kts",
    ".lua",
    ".m",
    ".mjs",
    ".mm",
    ".php",
    ".pl",
    ".pm",
    ".ps1",
    ".py",
    ".r",
    ".rb",
    ".rs",
    ".scala",
    ".scss",
    ".sh",
    ".sql",
    ".svelte",
    ".swift",
    ".tsx",
    ".ts",
    ".vue",
    ".zsh",
}

CONFIG_EXTENSIONS = {
    ".cfg",
    ".conf",
    ".editorconfig",
    ".env",
    ".example",
    ".ini",
    ".json",
    ".properties",
    ".toml",
    ".xml",
    ".yaml",
    ".yml",
}

CONFIG_FILE_NAMES = {
    ".dockerignore",
    ".editorconfig",
    ".env.example",
    ".eslintignore",
    ".eslintrc",
    ".eslintrc.cjs",
    ".eslintrc.js",
    ".eslintrc.json",
    ".gitignore",
    ".prettierrc",
    ".prettierrc.json",
    "build.gradle",
    "build.gradle.kts",
    "cargo.toml",
    "cmakelists.txt",
    "compose.yaml",
    "compose.yml",
    "containerfile",
    "docker-compose.yaml",
    "docker-compose.yml",
    "dockerfile",
    "gemfile",
    "go.mod",
    "gradle.properties",
    "makefile",
    "package.json",
    "pipfile",
    "pom.xml",
    "procfile",
    "pyproject.toml",
    "requirements-dev.txt",
    "requirements.txt",
    "setup.cfg",
    "setup.py",
    "taskfile.yaml",
    "taskfile.yml",
    "tox.ini",
}

LOCK_OR_GENERATED_FILE_NAMES = {
    "cargo.lock",
    "composer.lock",
    "gemfile.lock",
    "go.sum",
    "npm-shrinkwrap.json",
    "package-lock.json",
    "pipfile.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "yarn.lock",
}

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

README_NAMES = {
    "readme",
    "readme.md",
    "readme.mdx",
    "readme.rst",
    "readme.txt",
}

BINARY_EXTENSIONS = {
    ".a",
    ".avif",
    ".bin",
    ".bmp",
    ".class",
    ".dll",
    ".dylib",
    ".exe",
    ".gif",
    ".ico",
    ".jar",
    ".jpeg",
    ".jpg",
    ".o",
    ".pdf",
    ".png",
    ".pyc",
    ".so",
    ".wasm",
    ".webp",
    ".zip",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def run_git_inventory(repo: Path) -> list[Path] | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), "ls-files", "-co", "--exclude-standard", "-z"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    paths = []
    for raw in result.stdout.split(b"\0"):
        if not raw:
            continue
        try:
            rel = raw.decode()
        except UnicodeDecodeError:
            continue
        path = repo / rel
        if path.is_file():
            paths.append(path)
    return sorted(paths)


def walk_inventory(repo: Path) -> list[Path]:
    paths: list[Path] = []
    for root, dirs, files in os.walk(repo):
        root_path = Path(root)
        kept_dirs = []
        for dirname in dirs:
            lower = dirname.lower()
            if lower in GENERATED_DIR_NAMES or lower in DOC_DIR_NAMES:
                continue
            kept_dirs.append(dirname)
        dirs[:] = kept_dirs
        for filename in files:
            paths.append(root_path / filename)
    return sorted(paths)


def rel_parts(path: Path, repo: Path) -> list[str]:
    return list(path.relative_to(repo).parts)


def is_under_named_dir(parts: list[str], names: set[str]) -> bool:
    return any(part.lower() in names for part in parts[:-1])


def is_readme(path: Path) -> bool:
    return path.name.lower() in README_NAMES


def is_package_metadata(path: Path) -> bool:
    return path.name.lower() in PACKAGE_METADATA_NAMES


def is_config(path: Path) -> bool:
    name = path.name.lower()
    suffix = path.suffix.lower()
    if name in CONFIG_FILE_NAMES:
        return True
    if suffix in CONFIG_EXTENSIONS:
        return True
    if ".config." in name or name.endswith("rc"):
        return True
    return False


def is_source(path: Path) -> bool:
    return path.suffix.lower() in SOURCE_EXTENSIONS


def is_executable(path: Path) -> bool:
    try:
        mode = path.stat().st_mode
    except OSError:
        return False
    return bool(mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))


def skip_reason(path: Path, repo: Path) -> str | None:
    parts = rel_parts(path, repo)
    lower_name = path.name.lower()
    suffix = path.suffix.lower()
    if is_under_named_dir(parts, GENERATED_DIR_NAMES):
        return "generated_or_vendor_directory"
    if is_under_named_dir(parts, DOC_DIR_NAMES):
        return "documentation_directory"
    if lower_name in LOCK_OR_GENERATED_FILE_NAMES:
        return "generated_lock_or_sum_file"
    if suffix in BINARY_EXTENSIONS:
        return "binary_asset"
    if suffix == ".map" or lower_name.endswith(".min.js") or lower_name.endswith(".min.css"):
        return "generated_minified_or_map_file"
    return None


def classify(path: Path, repo: Path) -> tuple[str | None, str | None]:
    reason = skip_reason(path, repo)
    if reason:
        return None, reason
    if is_readme(path) and not is_under_named_dir(rel_parts(path, repo), DOC_DIR_NAMES):
        return "support_readme", None
    if is_source(path):
        return "code", None
    if is_config(path):
        return "config", None
    if is_executable(path) and path.suffix.lower() not in BINARY_EXTENSIONS:
        return "executable", None
    if path.suffix.lower() in DOC_EXTENSIONS:
        return None, "documentation_file"
    return None, "not_code_or_config"


def count_lines(path: Path) -> int | None:
    try:
        total = 0
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                total += chunk.count(b"\n")
        return total
    except OSError:
        return None


def looks_textual(path: Path, sample_size: int = 4096) -> bool:
    try:
        sample = path.read_bytes()[:sample_size]
    except OSError:
        return False
    if not sample:
        return True
    if b"\0" in sample:
        return False
    textish = sum(1 for byte in sample if byte in b"\n\r\t" or 32 <= byte <= 126)
    return textish / len(sample) >= 0.85


def file_record(path: Path, repo: Path, kind: str) -> dict:
    size = path.stat().st_size
    return {
        "path": path.relative_to(repo).as_posix(),
        "kind": kind,
        "extension": path.suffix.lower(),
        "bytes": size,
        "lines": count_lines(path),
        "estimated_tokens": max(1, math.ceil(size / 4)),
        "executable": is_executable(path),
    }


def build_inventory(repo: Path) -> dict:
    repo = repo.resolve()
    paths = run_git_inventory(repo)
    inventory_source = "git_ls_files"
    if paths is None:
        paths = walk_inventory(repo)
        inventory_source = "filesystem_walk"

    included = []
    support = []
    review_candidates = []
    skipped = Counter()

    for path in paths:
        if not path.is_file():
            continue
        try:
            kind, reason = classify(path, repo)
        except OSError:
            skipped["unreadable_file"] += 1
            continue
        if reason:
            if reason == "not_code_or_config" and looks_textual(path):
                review_candidates.append(file_record(path, repo, "review_candidate"))
                continue
            skipped[reason] += 1
            continue
        if kind == "support_readme":
            support.append(file_record(path, repo, "readme"))
            continue
        record = file_record(path, repo, kind or "unknown")
        if is_package_metadata(path):
            record["supporting_evidence"] = "package_metadata"
        included.append(record)

    included.sort(key=lambda item: item["path"])
    support.sort(key=lambda item: item["path"])
    review_candidates.sort(key=lambda item: item["path"])

    total_bytes = sum(item["bytes"] for item in included)
    total_tokens = sum(item["estimated_tokens"] for item in included)

    return {
        "schema_version": 1,
        "generated_at": utc_now(),
        "repo_root": repo.as_posix(),
        "inventory_source": inventory_source,
        "policy": {
            "output_directory": ".repo-map",
            "map_includes": ["code", "executable", "config"],
            "supporting_evidence": ["readme", "package_metadata"],
            "review_candidates": "uncommon text files requiring manual promotion before mapping",
            "excluded": [
                "generated_or_vendor_directory",
                "documentation_directory",
                "documentation_file",
                "binary_asset",
                "generated_lock_or_sum_file",
            ],
        },
        "totals": {
            "included_files": len(included),
            "included_bytes": total_bytes,
            "estimated_tokens": total_tokens,
            "support_files": len(support),
            "review_candidates": len(review_candidates),
            "skipped_files": sum(skipped.values()),
        },
        "included_files": included,
        "supporting_evidence": support,
        "review_candidates": review_candidates,
        "skipped_summary": [
            {"reason": reason, "count": count}
            for reason, count in sorted(skipped.items())
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", nargs="?", default=".", help="repository root")
    parser.add_argument(
        "--output",
        help="output JSON path; defaults to <repo>/.repo-map/preflight_inventory.json",
    )
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    output = Path(args.output) if args.output else repo / ".repo-map" / "preflight_inventory.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(build_inventory(repo), indent=2) + "\n")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
