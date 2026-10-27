# Levels

[Русский](../ru/levels.md) · [Back to README](../../README.md)

A level sets how deep each story is reviewed and checked. Pick it per run with
`--fast`, `--normal` or `--deep`, or set a default in `[run] level` of your config.
Without either, the level is `normal`.

## What each level turns on

BMad's engine reviews the diff with parallel review layers. auto-bmad decides which layers
run, on which model, how many review passes are allowed, and how many fixes the checks
may ask for.

| | `fast` | `normal` (default) | `deep` |
|---|---|---|---|
| Edge Case Hunter | Sonnet, medium | Sonnet, medium | Sonnet, high |
| Blind Hunter | off | Sonnet, medium | Sonnet, high |
| Intent Alignment Auditor | Haiku, high | Haiku, high | Sonnet, high |
| Verification Gap Reviewer | off | off | Sonnet, high |
| Review layers | 2 | 3 | 4 |
| Review passes per story | 1 (no repeat) | up to 2 | up to 3 |
| Repair loops (`bad_spec`) per pass | 1 | 2 | 3 |
| Checks after a story (tests, device) | none | yes, up to 2 fixes | yes, up to 3 fixes |

"Sonnet, medium" means the model and its reasoning effort.

**Review pass.** The engine fixed a `high` finding and asks for another look. The story
runner calls the engine again on the finished spec, up to the level's limit. If the limit
is used up and the engine still asks, the risk goes to "needs attention" — no extra
passes are taken. A repeat pass starts only after a fixed `high` finding, on every level.

**Repair loop.** The diff was rejected at the root: the code is rolled back, the spec is
corrected and the story is redone. If this happens more often than the limit in one pass,
the story is `blocked`.

**Fixes after checks.** See [Checks](checks.md). The limits live in `[verify_limits]`
and can be changed.

## When to pick which

| Level | Use it for |
|---|---|
| `fast` | mechanical work: configs, tests, renames, small fixes. Cheapest and quickest; nothing is checked after the story beyond what the engine itself runs |
| `normal` | everyday work |
| `deep` | when a mistake is expensive: money, data migrations, public contracts. Slowest and most expensive |

Why the layers are set this way: in a measurement over 15 finished stories, Edge Case
Hunter and Blind Hunter found 20 of 22 `high` findings, so they are never downgraded.
Verification Gap found no `high` findings and is the most expensive layer (it walks the
whole repository and its tests), so it runs only on `deep`. Intent Alignment compares two
texts (intent and diff) without walking the code, so it runs on Haiku below `deep`.

## Models

Models are fixed per level in this version: the level picks them, there is no setting
for models. Each role is a subagent type that ships with the plugin.

| Role | Agent type | Model, effort |
|---|---|---|
| Orchestrator (the `/auto-bmad:auto-bmad` skill) | — | Opus (1M context), medium |
| Story runner (runs the engine for one story) | `auto-bmad:bmad-story-runner` | Opus (1M context), medium |
| Implementer (writes code from the spec) | `auto-bmad:bmad-implementer` | Opus (1M context), medium |
| Review layers on `deep` | `auto-bmad:bmad-reviewer` | Sonnet, high |
| Review layers on `normal` and `fast` (except Intent Alignment) | `auto-bmad:bmad-reviewer-mid` | Sonnet, medium |
| Intent Alignment on `normal` and `fast` | `auto-bmad:bmad-reviewer-lite` | Haiku, high |
| Epic context compiler on `normal` and `fast` | `auto-bmad:bmad-compiler-lite` | Haiku, high |
| Checks after a story | `auto-bmad:bmad-verifier` | Sonnet, medium |

On `deep`, the epic context (`epic-<N>-context.md`, read by every story of the epic) is
compiled by the session model instead of the cheaper compiler.

Reviewers run on a different model than the implementer on purpose: a different model has
different blind spots.

## The level profile

The level reaches BMad's engine through the level profile,
`_bmad/custom/bmad-build-auto.user.toml`: rules ("facts") the engine follows for the run and
the review layers it turns off. What each fact changes and why — [Under the hood](engine.md).
