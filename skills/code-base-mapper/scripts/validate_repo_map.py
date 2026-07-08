#!/usr/bin/env python3
"""Validate generated .repo-map artifacts for code-base-mapper."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def validate(repo: Path, manifest_path: Path | None = None, work_plan_path: Path | None = None) -> dict:
    repo = repo.resolve()
    repo_map = repo / ".repo-map"
    manifest_path = manifest_path or repo_map / "preflight_inventory.json"
    work_plan_path = work_plan_path or repo_map / "work_plan.json"
    manifest = load_json(manifest_path)
    work_plan = load_json(work_plan_path)

    errors: list[str] = []
    warnings: list[str] = []

    map_md = repo_map / "map.md"
    root_index = repo_map / "index.md"
    if not repo_map.exists():
        errors.append(".repo-map/ directory is missing")
    if not map_md.exists():
        errors.append(".repo-map/map.md is missing")
    if not root_index.exists():
        errors.append(".repo-map/index.md is missing")

    map_text = map_md.read_text() if map_md.exists() else ""
    index_paths = sorted(repo_map.rglob("index.md")) if repo_map.exists() else []
    for index_path in index_paths:
        rel = index_path.relative_to(repo_map)
        if len(rel.parent.parts) > 2:
            errors.append(f"index exceeds second-level depth: {rel.as_posix()}")
        text = index_path.read_text()
        if "map.md" not in text:
            errors.append(f"index does not link to map.md: {rel.as_posix()}")

    for support in manifest.get("supporting_evidence", []):
        path = support.get("path", "")
        if path and path in map_text:
            warnings.append(f"supporting evidence appears in map.md tree text: {path}")

    for candidate in manifest.get("included_files", []):
        path = candidate.get("path", "")
        basename = Path(path).name
        if basename and basename not in map_text:
            warnings.append(f"included file basename not found in map.md: {path}")

    assigned = []
    for assignment in work_plan.get("assignments", []):
        assigned.extend(assignment.get("files", []))
    duplicates = sorted({path for path in assigned if assigned.count(path) > 1})
    if duplicates:
        errors.append(f"duplicate file assignments: {', '.join(duplicates)}")
    if work_plan and work_plan.get("totals", {}).get("duplicate_assignments", 0):
        errors.append("work_plan.json reports duplicate_assignments > 0")

    return {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "warnings": warnings,
        "summary": {
            "indexes_checked": len(index_paths),
            "included_files": len(manifest.get("included_files", [])),
            "assigned_files": len(assigned),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", nargs="?", default=".", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--work-plan", type=Path)
    parser.add_argument("--output", type=Path, help="optional JSON report path")
    args = parser.parse_args()

    report = validate(args.repo, args.manifest, args.work_plan)
    text = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text)
    print(text, end="")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
