# market-gap-research skills

Canonical home for market-gap-research project-scoped skills:

```text
hermes-related-code/skills/market-gap-research/<skill>/SKILL.md
```

The `market-gap-research` project itself remains a standalone repository. Do **not** vendor it into `hermes-related-code` as a subtree, submodule, copied directory, or nested sub-repository.

Current local project path:

```text
/workspace/market-gap-research
```

## Implemented research-loop skills

DH-117 implements these project-local skills/spec modules in this repo:

```text
skills/market-gap-research/collector/SKILL.md
skills/market-gap-research/extractor/SKILL.md
skills/market-gap-research/statistician/SKILL.md
skills/market-gap-research/clusterer/SKILL.md
skills/market-gap-research/skeptic/SKILL.md
skills/market-gap-research/strategist/SKILL.md
skills/market-gap-research/reporter/SKILL.md
skills/market-gap-research/run-controller/SKILL.md
```

Each spec defines:

- explicit typed inputs and outputs;
- stop conditions;
- persisted-state boundaries;
- source-content-as-untrusted-data handling;
- fixture verification commands.

## How Hermes should use these

These files are **project-local agent skill specs**, not global Hermes-native skills. By default they are not copied into `~/.hermes/skills`, not installed through `skill_manage`, and not promoted to `skills-source/`.

When Hermes is working on the market-gap research loop, load/read the relevant file from this repository as project context and operate the standalone project through its documented CLI surface. Promote any skill globally only through a separate approved task.

## Fixture orchestration check

From `hermes-related-code`, validate the skill specs and run the standalone project against deterministic fixtures:

```bash
python3 skills/market-gap-research/scripts/run_fixture_orchestration.py   --project-root /workspace/market-gap-research
```

The script checks all eight `SKILL.md` files for required sections, then runs a one-turn fixture loop and downstream context/statistics/cluster/report commands against a temporary SQLite DB.

## Project command surface

Run these from the standalone project checkout, not from inside this repository:

```bash
cd /workspace/market-gap-research
uv sync --dev
uv run init-state
uv run market-gap-doctor
uv run pytest -q
uv run ruff check .
```

Equivalent `make` targets in the standalone repo:

```bash
make doctor
make test
make lint
```

## Source-of-truth rule

- Project code, fixtures, schema/table contracts, and runtime docs remain in `/workspace/market-gap-research`.
- Project-scoped agent skills/specs for DH-117 and related research-loop work live in `hermes-related-code/skills/market-gap-research/`.
- If a market-gap skill becomes generally reusable across projects, promote it separately to `skills-source/<skill>/SKILL.md` with an explicit follow-up.
