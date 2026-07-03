---
name: Feature request
about: A language, a lane, or a behavior skim should have
labels: enhancement
---

## The problem

<!-- What are you paying tokens for today that skim should be cutting? -->

## Proposed behavior

<!-- What would the tool call and its result look like? -->

## Constraints to keep in mind

skim's hard line is the airtight contract: lossless, round-trip exact, in-bounds,
deterministic, never-crash, for any input. Features that trade losslessness for ratio
belong behind an explicit opt-in flag, not in the defaults.
