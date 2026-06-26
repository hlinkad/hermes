# Skills

This directory is the centralized home for Hermes-related skills and project-scoped skill specs/modules developed alongside Hermes-related code.

## Layout

```text
skills/
  <skill>/
    SKILL.md
    references/
    scripts/
    templates/
  <project>/
    <skill>/
      SKILL.md
      references/
      scripts/
      templates/
```

Use top-level `skills/<skill>/SKILL.md` for global/promoted reusable Hermes skills.
Use `skills/<project>/<skill>/SKILL.md` when a skill belongs to a specific external project and should not be promoted yet as a global Hermes skill.

## Boundaries

- Keep project code in its own repository unless a task explicitly approves vendoring.
- Do not subtree, submodule, or hand-copy standalone project repositories into this repo just to author skills.
- Skills may reference external project paths and commands, but the external project remains the source of truth for its own code, tests, fixtures, and runtime contracts.
