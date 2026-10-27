# Run levels — what is on and why

Read when you need to explain the choice of level to the human, understand how the review behaves
or change the layout. The run itself needs only the table in `SKILL.md`: the engine profile
is built by `auto-bmad profile`, and the setting texts do not get into the context.

## Layout

| | `--fast` | `--normal` (default) | `--deep` |
|---|---|---|---|
| Edge Case Hunter | Sonnet 5.5 / `medium` | Sonnet 5.5 / `medium` | Sonnet 5.5 / `high` |
| Blind Hunter | off | Sonnet 5.5 / `medium` | Sonnet 5.5 / `high` |
| Intent Alignment Auditor | **Haiku 5.5** / `high` | **Haiku 5.5** / `high` | Sonnet 5.5 / `high` |
| Verification Gap Reviewer | off | **off** | Sonnet 5.5 / `high` |
| Review passes per story | 1 (no extra ones) | 2 (one extra) | 3 (up to two extra) |
| `bad_spec` cycle limit per pass | 1 | 2 | 3 |
| Checks after a story (project tests, device) | no | yes, up to 2 fixes | yes, up to 3 fixes |
| When to use | mechanical work: configs, tests, renames, a small edit | normal work | the cost of a mistake is high: money, migrations, a public contract |

Agent types: `bmad-reviewer` — Sonnet 5.5 / `high`, `bmad-reviewer-mid` — Sonnet 5.5 / `medium`,
`bmad-reviewer-lite` — Haiku 5.5 / `high`. One more type, `bmad-compiler-lite` (Haiku 5.5 / `high`),
is not a reviewer: on `fast` and `normal` it builds `epic-<N>-context.md` when there is no cache (fact G).
On `deep` the context is built by the session model: all stories of the epic read the file, and the engine's check
looks only at the heading, so a dropped constraint is not caught at this level.

## Why so

A measurement on 15 finished stories gave this attribution of `high` findings: Edge Case — 12 of 22,
Blind Hunter — 8, Intent Alignment — 1, Verification Gap — 0. Everything else follows from this.

- **Verification Gap is off on `normal`.** Zero `high` over 15 stories, and its contribution is
  34 `medium` about gaps in tests. At the same time it is the most expensive of the four: the only layer
  that walks the whole repository, reads tests and follows calls for 1–3 hops.
  Turning it off cuts both the review input and the triage load — that is, the most expensive part of the run.
  On `deep` it runs.
- **Edge Case and Blind Hunter do not get a lower tier on any level.** Together they give
  20 `high` of 22. Cutting them is not a saving, it is giving up the review.
- **Intent Alignment on `fast` and `normal` goes to Haiku 5.5 / `high`.** The only layer whose work
  is closed: two texts as input (the intent and the diff), no walking the repository, no
  bug hunting, a descriptive answer. The cost of a miss is minimal — 1 `high` over 15 stories.
  On `fast` the layer is on since 2026-10-13: on Haiku 5.5 it costs pennies ($0.10 / $0.50 per
  1M tokens with a prompt up to 100K, per the Anthropic documentation as of October 2026; Haiku 4.5 — $1 / $5), and without it `fast` does not compare the diff with the intent at all. Effort `high`, not
  the default `medium`: Anthropic recommends `high` for strict instruction following,
  and the input (the diff) does not get more expensive with effort.
- **Haiku gets neither Verification Gap, nor Blind Hunter, nor Edge Case.** The first breaks
  on the search volume and starts writing "there is no test" with confidence without searching to the end — and every such
  finding is then verified by the Opus session, and the saving comes back as a bill for triage.
  The second is an open question without a method, a genre where a weak model gives general words
  instead of findings. The third is too valuable.
- **`high` → `medium` is about speed, not tokens.** For reviewers the input (the diff)
  dominates the output, and effort does not affect the input at all. Lowering effort shortens
  thinking and time, but the bill is cut by a layer turned off and a tier change.

## Two limits, and they are about different things

**A `bad_spec` cycle** — the diff is rejected at the root: the code is rolled back, the spec is edited, the story
is redone from scratch. The limit `1` / `2` / `3` lives in the profile (fact C) and is enforced by the engine.
It counts **per pass**: the engine resets `review_loop_iteration` to zero on each extra
pass (`step-01-clarify-and-route.md`). Left so on purpose — over 15 stories the counter
never went above zero.

**An extra review pass** — the code stays, but the engine patched a `high` and says the review
did not converge. The limit `1` / `2` / `3` is enforced by the `auto-bmad:bmad-story-runner` subagent, calling
the engine again on the `done` spec.

The threshold for the extra pass itself is the same on all levels: it runs only if the engine
fixed a finding with the `high` verdict (fact A). The level sets not the threshold but how many such
passes are allowed at all.

## What goes into the engine profile

`auto-bmad profile` writes `_bmad/custom/bmad-build-auto.user.toml` — the top layer
of the merge (`_bmad/scripts/config_utils.py`), which overrides both the skill's `customize.toml`
and the project's `bmad-build-auto.toml`. The file is excluded in `.git/info/exclude`, it does not dirty the tree.

Eight facts. A–F and H — on any level, the text of C and E depends on the level; G — only on `fast`
and `normal`:

| | Fact | Why |
|---|---|---|
| A | follow-up only on `high` | the second review pass stops being triggered by a couple of medium findings |
| B | two-stage triage | cosmetics are filtered by the finding text, without going into the code |
| C | fix cycle limit | `1` / `2` / `3` by level |
| D | Blind Hunter without a findings floor | the layer stops inventing findings to reach N |
| E | reviewers and implementer on agent types | review on a different model in any project; the tier is set by the level |
| F | subagents are asynchronous | lifts the engine's ban on ending the turn, otherwise the run goes into an idle loop |
| G | the epic context is built by `bmad-compiler-lite` | a cheap model for a closed extract from the planning documents |
| H | context economy | a diff under 30 000 characters is read whole; a larger one is not (reviewers read it); no re-reads of the spec, the epic context and `workflow.md`; targeted reads for triage stay unlimited, and a finding routed `reject` or graded `false` / `low` names the code read (except one screened out by fact B) |

The merge rules everything rests on, and which the script follows: `persistent_facts`
are appended to the project ones (the project's routing and settings stay), `review_layers`
are merged **by `id`** — so a layer is turned off with an entry with the same `id` and an empty
`instruction`, not by rewriting its text.

E and F are not about the level but about the environment: they make the run the same in any BMad project,
without project settings. Before, they had to be put into the `bmad-build-auto.toml` of every
project.

## Checks after a story

Step 3.5 of `SKILL.md`: after the engine's commit come the checks from the config (`[[verify]]`) —
the project's whole test suite (`project-tests`) and the check on an Android device through adbm
(`adbm`, only if the diff touches the UI) or in a browser through mockmatch (`mockmatch`, only if
the diff touches the web UI). A check found a problem — the engine fixes it, the check
repeats. The limit is the number of fixes per story: `[verify_limits]` in the config, by default
`fast` 0, `normal` 2, `deep` 3. After each fix — a repeated check: so the last
fix is confirmed too. Did not converge — an item in "Needs attention"; tests broken with a
green baseline — `blocked`.
