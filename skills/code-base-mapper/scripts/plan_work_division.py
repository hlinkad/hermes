#!/usr/bin/env python3
"""Plan whole-file analysis assignments from a preflight inventory."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def choose_agent_count(total_tokens: int, budget: int, large_repo: bool, mode: str, max_agents: int) -> int:
    if not large_repo:
        return 1
    if mode == "auto":
        return min(max_agents, max(1, math.ceil(total_tokens / max(1, budget))))
    return min(max_agents, max(1, int(mode)))


def assign_files(files: list[dict], agent_count: int) -> list[dict]:
    assignments = [
        {"agent_id": f"agent-{index + 1}", "estimated_tokens": 0, "bytes": 0, "files": []}
        for index in range(agent_count)
    ]
    for item in sorted(files, key=lambda file: file.get("estimated_tokens", 0), reverse=True):
        target = min(assignments, key=lambda bucket: bucket["estimated_tokens"])
        target["files"].append(item["path"])
        target["estimated_tokens"] += int(item.get("estimated_tokens", 0))
        target["bytes"] += int(item.get("bytes", 0))
    for assignment in assignments:
        assignment["files"].sort()
        assignment["file_count"] = len(assignment["files"])
    return assignments


def build_plan(manifest: dict, args: argparse.Namespace) -> dict:
    files = list(manifest.get("included_files", []))
    total_tokens = sum(int(item.get("estimated_tokens", 0)) for item in files)
    total_bytes = sum(int(item.get("bytes", 0)) for item in files)
    per_agent_budget = max(1, int(args.target_context_window_tokens * args.max_context_usage_ratio))
    agent_count = choose_agent_count(
        total_tokens=total_tokens,
        budget=per_agent_budget,
        large_repo=args.large_repo,
        mode=args.agent_count,
        max_agents=args.max_agents,
    )
    assignments = assign_files(files, agent_count)

    oversized = [
        {
            "path": item["path"],
            "estimated_tokens": int(item.get("estimated_tokens", 0)),
            "budget": per_agent_budget,
        }
        for item in files
        if int(item.get("estimated_tokens", 0)) > per_agent_budget
    ]

    warnings = []
    if total_tokens > per_agent_budget * agent_count:
        warnings.append(
            "Estimated content exceeds the configured per-agent budget; keep whole-file ownership and use selective reading."
        )
    if oversized:
        warnings.append(
            "One or more files exceed the per-agent budget alone; assign each oversized file to one owner only."
        )

    for assignment in assignments:
        assignment["budget_status"] = (
            "within_budget"
            if assignment["estimated_tokens"] <= per_agent_budget
            else "over_budget"
        )

    all_paths = [path for assignment in assignments for path in assignment["files"]]
    duplicate_paths = sorted({path for path in all_paths if all_paths.count(path) > 1})

    return {
        "schema_version": 1,
        "source_manifest": args.manifest.as_posix(),
        "repo_root": manifest.get("repo_root"),
        "configuration": {
            "large_repo": args.large_repo,
            "agent_count_mode": args.agent_count,
            "agent_count": agent_count,
            "max_agents": args.max_agents,
            "target_context_window_tokens": args.target_context_window_tokens,
            "max_context_usage_ratio": args.max_context_usage_ratio,
            "per_agent_budget_tokens": per_agent_budget,
            "split_files_between_agents": False,
        },
        "totals": {
            "files": len(files),
            "bytes": total_bytes,
            "estimated_tokens": total_tokens,
            "assigned_files": len(all_paths),
            "duplicate_assignments": len(duplicate_paths),
        },
        "assignments": assignments,
        "oversized_single_files": oversized,
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="preflight_inventory.json")
    parser.add_argument("--output", type=Path, help="output path; defaults beside manifest")
    parser.add_argument("--large-repo", action="store_true", help="enable multi-agent planning")
    parser.add_argument(
        "--agent-count",
        default="auto",
        help="'auto' or an explicit positive integer; capped by --max-agents",
    )
    parser.add_argument("--max-agents", type=positive_int, default=4)
    parser.add_argument("--target-context-window-tokens", type=positive_int, default=256000)
    parser.add_argument("--max-context-usage-ratio", type=float, default=0.40)
    args = parser.parse_args()

    if args.agent_count != "auto":
        positive_int(args.agent_count)
    if not 0 < args.max_context_usage_ratio <= 1:
        raise SystemExit("--max-context-usage-ratio must be between 0 and 1")

    manifest = json.loads(args.manifest.read_text())
    output = args.output or args.manifest.parent / "work_plan.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(build_plan(manifest, args), indent=2) + "\n")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
