# Levels

[Русский](../ru/levels.md) · [Back to README](../../README.md)

A level sets how deep each story is reviewed and checked. Pick it per run with
`--fast`, `--normal` or `--deep`, or set a default in `[run] level` of your config.
Without either, the level is `normal`.

## What each level turns on

BMad's engine reviews the diff with parallel review layers. auto-bmad decides which layers
run, how many review passes are allowed, and how many fixes the checks may ask for.
Each layer is a separately configured subagent; the level does not change its identity.

| | `fast` | `normal` (default) | `deep` |
|---|---|---|---|
| Edge Case Hunter (`edge-case-hunter`) | on | on | on |
| Blind Hunter (`blind-hunter`) | off | on | on |
| Intent Alignment Auditor (`intent-alignment`) | on | on | on |
| Verification Gap Reviewer (`verification-gap`) | off | off | on |
| Review layers | 2 | 3 | 4 |
| Review passes per story | 1 (no repeat) | up to 2 | up to 3 |
| Story repair budgets: spec / review / tests | 2 / 5 / 10 | 2 / 5 / 10 | 2 / 5 / 10 |
| Checks after a story (tests, device) | none | yes, independent budgets | yes, independent budgets |

Models and reasoning effort are configured per subagent in the current client namespace;
client defaults may differ by level (see Claude defaults below), and explicit settings
override them without changing the subagent's identity.

**Review pass.** The first independent review is required. Repeat it only when cumulative
changes since that review are extensive or risky, within the level's pass limit. For localized
fixes the orchestrator checks closure evidence and affected tests, then records targeted
revalidation. Neither finding severity nor count alone triggers another pass. If a necessary
repeat exceeds the limit, preserve the concrete unreviewed risk under "needs attention".

**Repair cycles.** [`repair_limits`](config.md#repair_limits) gives independent budgets:
2 for actual spec errors, 5 for review fixes and 10 for failed tests. Follow-up passes do
not reset them. Tests are fixed in place without spec rewrites or review on every small
iteration; fix the complete known failure set before rerunning. Final configured checks
remain required; independent repeats follow the scope/risk rule above. Three test attempts
without progress block the story and preserve work. Post-story checks use the same
categories; `[verify_limits]` is deprecated.

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
texts (intent and diff) without walking the code. These measurements informed the Claude
defaults below; each layer still has its own model and effort settings.

## Models

Each row is one semantic subagent with independent `model` and `effort` settings.
Use `[executors.codex.roles.<id>]` or `[executors.claude.roles.<id>]`; an optional
`[executors.<client>.levels.<level>.roles.<id>]` changes only that agent at that level.
See [configuration](config.md#compact-codex-models). The main chat is the orchestrator;
you select its model in the host, outside auto-bmad's role config.

| Subagent ID | Responsibility | Codex default | Claude default |
|---|---|---|---|
| `story-runner` | Coordinates one story's engine and reports its state | Sol, high | Opus 1M, medium |
| `implementer` | Implements the spec and repairs the complete known issue batch | Sol, high | Opus 1M, medium |
| `context-compiler` | Extracts the epic context from planning documents when no cache exists | Sol, high | Haiku, high |
| `blind-hunter` | Independently searches the diff for defects | Astra, high | Sonnet, medium; deep: high |
| `edge-case-hunter` | Checks edge cases and failure paths | Astra, high | Sonnet, medium; deep: high |
| `intent-alignment` | Compares the change with its requirements and intended behavior | Astra, high | Haiku, high; deep: Sonnet, high |
| `verification-gap` | Finds missing verification and test coverage | Astra, high | Sonnet, medium; deep: high |
| `triager` | Validates, deduplicates and classifies findings when `triage_subagent = true` | Sol, high | Opus, high |
| `verifier` | Runs the configured agent checks after a story | Sol, high | Sonnet, medium |

Codex model IDs are `gpt-6.1-sol` and `gpt-6-astra`. Claude wrappers use
`auto-bmad:bmad-<id>`. The context compiler is used on every level, including `deep`;
a valid existing epic context avoids another compile. Review layers keep their individual
IDs at every level. The Claude defaults preserve the earlier model choices; a per-role
setting overrides those defaults, and a per-level role setting is the most specific override.

## The level profile

The level reaches BMad's engine through the level profile,
`_bmad/custom/bmad-build-auto.user.toml`: rules ("facts") the engine follows for the run and
the review layers it turns off. What each fact changes and why — [Under the hood](engine.md).
