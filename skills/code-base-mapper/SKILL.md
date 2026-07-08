---
name: code-base-mapper
description: Create .repo-map/ repository maps and searchable symbol indexes for AI agents. Use when Codex is asked to map a codebase, summarize executable/config repository structure, build map.md or index.md files, prepare codebase context for another skill, or analyze a large repository with optional multi-agent partitioning.
disable-model-invocation: true
---

# Code Base Mapper

Create a `.repo-map/` directory for a target repository containing an ASCII structure map and searchable symbol indexes. Keep every generated artifact inside `.repo-map/`; leave the source tree unchanged.

## Inputs

Accept these parameters from the user when provided, and use the defaults otherwise:

- `repository_path`: current working directory.
- `large_repo`: `false`.
- `agent_count`: `auto`.
- `max_agents`: `4`.
- `target_context_window_tokens`: `256000`.
- `max_context_usage_ratio`: `0.40`.
- `revision_iterations`: `1`.

When `large_repo: true`, use `agent_count: auto` by default, capped by `max_agents: 4`. Assign each source/config file to exactly one owner.

## Workflow

1. Read `references/output-contract.md` before producing `.repo-map/map.md` or any `.repo-map/**/index.md` file.
2. Run preflight inventory:

   ```bash
   python3 <skill-dir>/scripts/preflight_inventory.py <repository_path>
   ```

   Use the resulting `.repo-map/preflight_inventory.json` as the source of candidate files. It includes code, executable, and configuration files; it records README files as supporting evidence; it records uncommon text files as review candidates for manual promotion; it skips docs, generated artifacts, vendor folders, binary assets, lockfiles, and `.repo-map/`.

3. Run work planning:

   ```bash
   python3 <skill-dir>/scripts/plan_work_division.py <repository_path>/.repo-map/preflight_inventory.json
   ```

   Add `--large-repo`, `--agent-count`, `--max-agents`, `--target-context-window-tokens`, and `--max-context-usage-ratio` when those parameters differ from defaults.

4. Run symbol seeding:

   ```bash
   python3 <skill-dir>/scripts/extract_symbol_seeds.py <repository_path>/.repo-map/preflight_inventory.json
   ```

   Treat `.repo-map/symbol_seeds.json` as a starting point. Inspect source files to verify important classes, functions, methods, exported constants, route handlers, CLI commands, and test entry points before finalizing indexes.

5. Render starter artifacts:

   ```bash
   python3 <skill-dir>/scripts/render_repo_map.py <repository_path>/.repo-map/preflight_inventory.json --symbols <repository_path>/.repo-map/symbol_seeds.json
   ```

   Use `--overwrite` only when intentionally regenerating starter `map.md` and `index.md` before manual refinement.

6. Inspect files listed in `included_files`, `supporting_evidence`, and relevant `review_candidates`. Promote review candidates only when they are executable/code/config files. Use README files and package metadata as supporting evidence for high-level descriptions. Base final map and index entries on implementation files and configuration files.

7. For normal repositories, analyze files directly. For `large_repo: true`, use the work plan assignments:

   - When subagent tools are available, spawn one subagent per assignment and pass only that assignment's file list plus the output contract. Ask each subagent for compact structured facts, not final prose.
   - When subagent tools are unavailable, process assignments sequentially and mention the verification limitation in the final response.
   - For oversized single files, keep one owner and use selective reading, local symbol extraction, and targeted searches.

8. Refine `.repo-map/map.md`, `.repo-map/index.md`, and optional per-directory indexes up to depth two under `.repo-map/<top-level>/index.md` and `.repo-map/<top-level>/<second-level>/index.md`.

9. Run `revision_iterations` passes over the generated artifacts. In each pass, check for excluded paths, missing important executable/config files, unclear descriptions, broken links, duplicate symbol entries, and indexes deeper than the second level. When subagent tools are available and `revision_iterations` is greater than 1 or `large_repo: true`, use a reviewer subagent for one pass against the output contract, then apply concise refinements.

10. Run final validation:

   ```bash
   python3 <skill-dir>/scripts/validate_repo_map.py <repository_path> --output <repository_path>/.repo-map/validation.json
   ```

   Resolve validation errors before completion. Treat warnings as prompts for one more focused review.

11. Verify before completion:

   - `.repo-map/` is the only output location.
   - `map.md` contains executable/code/config structure only.
   - README and docs are absent from the mapped tree.
   - indexes link back to `map.md`.
   - per-directory indexes stop at depth two.
   - whole-file assignments have no duplicate owners when `large_repo: true`.

## Output Style

Use positive, factual descriptions. Prefer "Contains request handlers and service wiring" over absence-focused phrasing. Keep each directory or file description to one or two concise sentences.

## Resources

- `scripts/preflight_inventory.py`: metadata inventory and exclusion policy.
- `scripts/plan_work_division.py`: token-budgeted whole-file ownership plan.
- `scripts/extract_symbol_seeds.py`: best-effort symbol seed extraction.
- `scripts/render_repo_map.py`: starter ASCII map and root index rendering.
- `scripts/validate_repo_map.py`: final output validation for `.repo-map/`.
- `references/output-contract.md`: exact output structure, examples, fallback behavior, and revision checklist.
