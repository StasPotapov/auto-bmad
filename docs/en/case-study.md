# Case study: an Android app in 10 hours

[Русский](../ru/case-study.md) · [Back to README](../../README.md)

This page shows a real auto-bmad run. A human prepared the plan in BMad, and auto-bmad
wrote the app from scratch: 4 epics, 28 stories, about 10 hours with no human in the loop.
All numbers come from `auto-bmad stats` and the git history.

## The project

The project is an Android party game: pairs guess words on one phone. It has tournaments for many
pairs, timed rounds with scoring, 14 built-in dictionaries and your own dictionaries.
You can type your own dictionary, paste it from the clipboard, load it from a file and
export it. Settings cover the palette, sound, vibration and language.

Stack: Kotlin, Jetpack Compose, Room, DataStore, Koin. Minimum version: Android 10.

## What the human did

1. Prepared the plan in BMad: brief, PRD, UX, architecture, epics and sprint planning.
   The result: 5 epics and 31 stories.
2. Ran `/auto-bmad:setup`. It wrote `.auto-bmad.toml`: level `normal`, parallel waves
   `conservative`, tests `./gradlew test` and an emulator check on API 35 through
   [adbm](https://github.com/StasPotapov/adbm).
3. Ran `/auto-bmad:auto-bmad epic-N` one epic at a time and looked at the result.

The human wrote no code. Epic 5 is the Google Play release: release signing, privacy
policy, swipe smoothness on Android 10. It has not been run yet.

## Result

| | |
|---|---|
| Epics and stories | 4 epics, 28 stories, all `done` |
| Run time | 9 h 57 min (from 14:16 to 02:50 the next day, with breaks between epics) |
| Stops | one: preflight stopped the first story. An extra BMad module broke the engine; the human removed it in 3 minutes |
| Commits | 62: a commit per story, a tracking commit, one fix after a check |
| Kotlin, app code | 16.6k lines, 148 files |
| Kotlin, tests | 10.3k lines, 628 tests |
| Dictionaries and resources | 3.1k lines of dictionaries, 1.1k lines of resources |
| Emulator checks | 25 checks: 24 passed at once, one found a problem |
| Review | 868 findings, no `high`, 31 `medium`; the rest are `low` or false |
| Questions for the human | 93 items in the `epic-<N>-open-questions.md` files |

The check found a problem in story 2-4: the last-word card broke with a large font.
The engine fixed it in one fix run, and the second check passed.

Questions for the human are what the agent does not decide alone. For example, the
requirement to proofread the 14 built-in dictionaries by hand, or what "Back" should do
on a root screen.

## Tokens

| Epic | Stories | Time | Total | Per story | Input + cache write | Cache read | Output ≈ |
|---|---|---|---|---|---|---|---|
| 1 | 8 | 2 h 28 min | 116.3M | 14.5M | 5.9M | 110.1M | 355k |
| 2 | 10 | 4 h 10 min | 176.1M | 17.6M | 8.5M | 167.2M | 496k |
| 3 | 7 | 2 h 36 min | 96.6M | 13.8M | 5.2M | 91.1M | 305k |
| 4 | 3 | 44 min | 32.2M | 10.7M | 1.7M | 30.5M | 104k |
| **Total** | **28** | **9 h 57 min** | **421.4M** | **15.0M** | **21.3M** | **398.8M** | **1.26M** |

- **Cache reads** are 95% of all tokens. They are billed far below regular input.
- **Models:** Opus — 83% of tokens, Sonnet — 14%, Haiku — 2%.
- **Roles:** story runner — 56%, implementer — 25%, emulator check — 11%,
  review layers — 7%, epic context compiler — 1%.
- **Output** is an estimate from the text size; the model's reasoning is not included.
  More in [Statistics](stats.md).

## The human's verdict

The app works as the plan describes; the author found no logic bugs. The author's
subjective score is 99%. The only flaws were in a few animations: part of an element is clipped
while the animation plays. A model sees such defects poorly on still frames, and they
are quick to fix by hand.
