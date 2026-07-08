# Code Base Mapper Output Contract

Read this reference before writing `.repo-map/map.md` or `.repo-map/**/index.md`.

## Artifact Layout

Create artifacts only inside the target repository's `.repo-map/` directory:

```text
.repo-map/
|-- map.md
|-- index.md
|-- preflight_inventory.json
|-- work_plan.json
|-- symbol_seeds.json
|-- <top-level-dir>/
|   `-- index.md
`-- <top-level-dir>/
    `-- <second-level-dir>/
        `-- index.md
```

Per-directory indexes are optional and useful only when that area contains indexed symbols. Create them at root, first level, and second level only.

## Inclusion Policy

`map.md` includes executable/code files and configuration files. It skips documentation files and documentation directories, generated artifacts, vendor folders, ignored build outputs, binary assets, lockfiles, and `.repo-map/`.

README files and package metadata may support high-level descriptions. README files are supporting evidence, not mapped files. Package metadata can be both configuration and supporting evidence when it is included by the preflight inventory.

Uncommon text files may appear in `review_candidates`. Promote a review candidate into the final map/index only after inspection confirms it is executable/code/config material.

## `map.md` Format

Use a compact heading, then an ASCII tree. Give each included directory and file a one- or two-sentence high-level description.

~~~markdown
# Repository Map

Generated from executable/code and configuration files in `<repo-name>`.

```text
root/
|-- pyproject.toml - Defines Python package metadata, dependencies, and CLI entry points used by the application.
|-- src/ - Contains runtime code for command parsing and task execution.
|   |-- app.py - Provides the CLI entry point and orchestration for repository analysis.
|   `-- symbols.py - Extracts indexable classes, functions, methods, route handlers, and constants from source files.
`-- tests/ - Contains executable test coverage for the runtime modules.
    `-- test_app.py - Verifies CLI behavior and repository analysis outcomes.
```
~~~

Keep the ASCII tree as the primary representation. If a directory has many included files, group by meaningful subdirectory instead of writing long prose outside the tree.

## `index.md` Format

The root `.repo-map/index.md` is the main repository-wide symbol index. Per-directory indexes contain symbols for that directory subtree and link back to the nearest relative `map.md`.

Use a concise table:

~~~markdown
# Repository Index

Map: [map.md](map.md)

| Symbol | Kind | Source | Map Reference | Notes |
| --- | --- | --- | --- | --- |
| `main` | function | `src/app.py:42` | [map.md](map.md) `src/app.py` | CLI entry point. |
| `Runner.run` | method | `src/app.py:18` | [map.md](map.md) `src/app.py` | Coordinates inventory and output writing. |
| `npm script:build` | CLI command | `package.json` | [map.md](map.md) `package.json` | Builds distributable application assets. |
```
~~~

Index these symbol kinds when detectable:

- top-level classes
- top-level functions
- methods
- exported constants
- framework routes and handlers
- CLI commands
- test entry points
- public dependency boundaries when imports reveal an important interface

Use `symbol_seeds.json` as a seed list, then verify important entries from source. Keep routine imports out of indexes.

## Large Repository Planning

Large repository mode is explicitly requested through `large_repo: true`.

Use this default configuration:

```yaml
large_repo: true
agent_count: auto
max_agents: 4
target_context_window_tokens: 256000
max_context_usage_ratio: 0.40
split_files_between_agents: false
```

Run `preflight_inventory.py` first, then `plan_work_division.py`. The planner estimates tokens from metadata, chooses `agent_count` when set to `auto`, caps it at `max_agents`, and assigns whole files by token-budgeted bin packing.

Each file has exactly one owner. When one file exceeds the per-agent budget alone, keep that file with one owner and mark it as an oversized single file. The owner should use selective reads and symbol-focused searches.

## Fallbacks

- If the repository is not a git repo, the inventory script uses a filesystem walk with the same exclusion policy.
- If an uncommon text file appears in `review_candidates`, inspect it when its path or nearby configuration suggests executable/code/config behavior.
- If a language is not supported by the symbol seed extractor, inspect inventoried files directly and record verified symbols manually.
- If subagent tools are unavailable in `large_repo` mode, stop immediately and report the missing tools. Only multiple agents are supported for `large_repo` mode.
- If generated or documentation files appear in the inventory, remove them from final map/index outputs and refine the exclusion decision in the revision pass.
- If a source file has unclear purpose, use nearby code, package metadata, and README overview as supporting evidence, then write a concise factual description.

## Revision Checklist

For each revision iteration:

1. Confirm every output path is under `.repo-map/`.
2. Confirm `map.md` excludes docs, README files, generated artifacts, vendor folders, lockfiles, binary assets, and `.repo-map/`.
3. Confirm included files are executable/code/config files from the preflight inventory.
4. Confirm directory and file descriptions are concise and factual.
5. Confirm root and per-directory indexes link back to `map.md` with correct relative paths.
6. Confirm per-directory indexes stop at depth two.
7. Confirm important symbol kinds are present and routine imports stay out.
8. Confirm `large_repo` work assignments contain no duplicate file owners.
9. Run `validate_repo_map.py` and resolve errors before delivery.
