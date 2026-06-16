# Skills

This directory is the centralized home for project-scoped skill specs/modules that are developed alongside Hermes-related code but target separate project repositories.

## Layout

```text
skills/
  <project>/
    <skill>/
      SKILL.md
      references/
      scripts/
      templates/
```

Use this directory when a skill belongs to a specific external project and should not be promoted yet as a global Hermes skill.

Global/promoted reusable Hermes skills continue to live under `skills-source/<skill>/SKILL.md` unless the repository convention is intentionally changed later.

## Boundaries

- Keep project code in its own repository unless a task explicitly approves vendoring.
- Do not subtree, submodule, or hand-copy standalone project repositories into this repo just to author skills.
- Skills may reference external project paths and commands, but the external project remains the source of truth for its own code, tests, fixtures, and runtime contracts.
