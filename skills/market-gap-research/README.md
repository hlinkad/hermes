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

Future skills for the market-gap analysis/research-loop tooling should live here and refer to the standalone project by path and command, for example:

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
