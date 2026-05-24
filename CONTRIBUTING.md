# Contributing to EDP

Thanks for looking. EDP is in v0.1 alpha — the most valuable contributions right now are:

## Spec-shaping feedback

The specification is the load-bearing artifact. Read `SPEC.md` and `EXAMPLE.md` end-to-end, then open an issue with:

- Concrete pain you have or anticipate with the current model
- Concrete proposal — what changes, why
- Use-case context — what kind of agent / task

The five open questions in `SPEC.md` §11 are the most active areas.

## Reference SDK contributions

Once `sdk-python/edp/` has its first commits, contributions to the SDK should:

- Track the spec exactly (do not extend the spec by SDK fiat)
- Stay dependency-light. Stdlib + FastMCP + Pydantic + Typer. Adding a dependency requires discussion in an issue first.
- Cover new code with tests.

## New adapters

If you want to write an adapter for a harness not listed in the roadmap:

1. Open an issue first describing the harness's extension point and how you plan to inject the active block.
2. Match the file layout of existing adapters under `adapters/`.
3. Document known limitations of the harness's injection mechanism.

## Style

- Markdown: GFM, no trailing whitespace, no smart quotes.
- Python: ruff defaults from `pyproject.toml`. Type-annotated public surface.
- Commit messages: imperative mood, scoped prefix (`spec:`, `sdk-python:`, `adapter/claude-code:`, `docs:`).

## Maintenance pace

EDP is maintained by a single author on best-effort cadence. v0.1 → v1.0 is a multi-month arc, not a sprint. Issues and PRs are reviewed in batches, typically weekly. If a thread goes quiet for more than two weeks, ping with `@maintainer` — that is fair signal, not pressure.

If you find EDP useful and want to share the maintenance load — protocols benefit hugely from a second voice on spec decisions — open a discussion. Co-maintainer interest is welcome and explicitly invited.

## Code of conduct

Be kind, be specific, be patient. This is alpha, things will change.
