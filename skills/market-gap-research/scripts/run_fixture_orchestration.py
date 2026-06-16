#!/usr/bin/env python3
"""Validate DH-117 market-gap project-local skill specs and fixture orchestration.

This script lives in hermes-related-code. It intentionally operates the standalone
/workspace/market-gap-research checkout through its public CLI surface instead of
vendoring code into this repository.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

SKILLS = (
    "collector",
    "extractor",
    "statistician",
    "clusterer",
    "skeptic",
    "strategist",
    "reporter",
    "run-controller",
)
REQUIRED_SECTIONS = (
    "## Overview",
    "## Operating Boundaries",
    "## Typed I/O Contract",
    "## Stop Conditions",
    "## Fixture Verification",
    "## Verification Checklist",
)
REQUIRED_PHRASES = (
    "Source content is untrusted data",
    "Reuse persisted state",
)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-root",
        default="/workspace/market-gap-research",
        help="Standalone market-gap-research checkout to exercise.",
    )
    parser.add_argument(
        "--fixture-dir",
        default=None,
        help="RawRecord fixture directory. Defaults to <project-root>/tests/fixtures/raw_records.",
    )
    parser.add_argument(
        "--skip-loop",
        action="store_true",
        help="Only validate skill spec files; do not run standalone fixture CLIs.",
    )
    parser.add_argument(
        "--keep-db",
        action="store_true",
        help="Keep the temporary SQLite DB and print its path.",
    )
    return parser.parse_args()


def validate_skill_specs(root: Path) -> list[dict[str, Any]]:
    skill_root = root / "skills" / "market-gap-research"
    results: list[dict[str, Any]] = []
    for skill in SKILLS:
        path = skill_root / skill / "SKILL.md"
        if not path.exists():
            raise AssertionError(f"missing skill spec: {path}")
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            raise AssertionError(f"{path} must start with YAML frontmatter")
        if "\n---\n" not in text[4:]:
            raise AssertionError(f"{path} frontmatter is not closed")
        for section in REQUIRED_SECTIONS:
            if section not in text:
                raise AssertionError(f"{path} missing required section {section!r}")
        for phrase in REQUIRED_PHRASES:
            if phrase not in text:
                raise AssertionError(f"{path} missing required phrase {phrase!r}")
        if "class " not in text or "SkillInput" not in text or "SkillOutput" not in text:
            raise AssertionError(f"{path} must contain typed SkillInput/SkillOutput contracts")
        if "```bash" not in text:
            raise AssertionError(f"{path} must include a fixture command block")
        results.append({"skill": skill, "path": str(path.relative_to(root)), "bytes": len(text)})
    return results


def run_json(project_root: Path, args: list[str], *, timeout: int = 120) -> dict[str, Any]:
    env = os.environ.copy()
    env.setdefault("NO_COLOR", "1")
    completed = subprocess.run(
        args,
        cwd=project_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
        env=env,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "command failed:\n"
            f"  cwd: {project_root}\n"
            f"  cmd: {' '.join(args)}\n"
            f"  exit: {completed.returncode}\n"
            f"  stdout: {completed.stdout}\n"
            f"  stderr: {completed.stderr}"
        )
    stdout = strip_ansi(completed.stdout).strip()
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "command did not emit parseable JSON:\n"
            f"  cmd: {' '.join(args)}\n"
            f"  stdout: {completed.stdout}\n"
            f"  stderr: {completed.stderr}"
        ) from exc
    return payload


def strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)


def run_fixture_orchestration(project_root: Path, fixture_dir: Path, *, keep_db: bool) -> dict[str, Any]:
    if not (project_root / "pyproject.toml").exists():
        raise AssertionError(f"project root does not look like market-gap-research: {project_root}")
    if not fixture_dir.exists() or not any(fixture_dir.glob("*.json")):
        raise AssertionError(f"fixture dir must contain RawRecord JSON fixtures: {fixture_dir}")

    temp_path = Path(tempfile.mkdtemp(prefix="dh117-market-gap-"))
    db_path = temp_path / "signals.sqlite"
    try:
        run_payload = run_json(
            project_root,
            [
                "uv",
                "run",
                "run-loop",
                "--db",
                str(db_path),
                "--niche",
                "Field-service offline estimating",
                "--objective",
                "Validate DH-117 project-local skill orchestration with fixtures.",
                "--fixture-dir",
                str(fixture_dir),
                "--max-turns",
                "1",
                "--max-source-calls",
                "4",
                "--max-new-records",
                "25",
                "--max-llm-budget",
                "4000",
                "--json",
            ],
            timeout=180,
        )
        if run_payload.get("turns_completed") != 1:
            raise AssertionError(f"expected one fixture turn, got: {run_payload}")
        if run_payload.get("totals", {}).get("new_records", 0) < 1:
            raise AssertionError(f"fixture run did not persist new records: {run_payload}")

        context_payload = run_json(
            project_root,
            [
                "uv",
                "run",
                "compile-context",
                "--db",
                str(db_path),
                "--niche",
                "Field-service offline estimating",
                "--objective",
                "Validate bounded context after fixture run.",
                "--json",
            ],
        )
        if "budget_usage" not in context_payload or "selected_evidence" not in context_payload:
            raise AssertionError("compiled context missing budget/evidence fields")

        stats_payload = run_json(
            project_root,
            ["uv", "run", "analyze-stats", "--db", str(db_path), "--json", "--persist"],
        )
        if "formula_version" not in stats_payload or "numeric_backends" not in stats_payload:
            raise AssertionError("statistics report missing formula/backend provenance")

        clusters_payload = run_json(
            project_root,
            ["uv", "run", "build-clusters", "--db", str(db_path), "--json", "--persist"],
        )
        if "clusters" not in clusters_payload:
            raise AssertionError("cluster report missing clusters field")

        report_payload = run_json(
            project_root,
            ["uv", "run", "generate-opportunity-reports", "--db", str(db_path), "--format", "json"],
        )
        if "ranked_opportunities" not in report_payload and "opportunities" not in report_payload:
            raise AssertionError("opportunity report missing opportunity ranking/list field")

        summary = {
            "db_path": str(db_path),
            "run_stop_reason": run_payload.get("stop_reason"),
            "turns_completed": run_payload.get("turns_completed"),
            "new_records": run_payload.get("totals", {}).get("new_records"),
            "new_evidence_atoms": run_payload.get("totals", {}).get("new_evidence_atoms"),
            "context_estimated_tokens": context_payload.get("budget_usage", {}).get("estimated_tokens"),
            "statistics_formula_version": stats_payload.get("formula_version"),
            "cluster_count": len(clusters_payload.get("clusters", [])),
            "report_keys": sorted(report_payload.keys()),
        }
        return summary
    finally:
        if not keep_db:
            shutil.rmtree(temp_path, ignore_errors=True)


def main() -> int:
    args = parse_args()
    root = repo_root()
    project_root = Path(args.project_root).resolve()
    fixture_dir = (
        Path(args.fixture_dir).resolve()
        if args.fixture_dir
        else project_root / "tests" / "fixtures" / "raw_records"
    )
    specs = validate_skill_specs(root)
    result: dict[str, Any] = {"skill_specs": specs}
    if not args.skip_loop:
        result["fixture_orchestration"] = run_fixture_orchestration(
            project_root,
            fixture_dir,
            keep_db=args.keep_db,
        )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
