---
name: check-impl-against-plan
description: Compare a pull request's implementation against plan context in implementation_plan_context.md and feed any material mismatches into review.json. Use during PR review when approved or repository plan context is available.
---

# Check implementation against plan

Use this skill only when `implementation_plan_context.md` exists during PR review.

## Goal

Determine whether the implementation in the checked-out PR materially matches the approved plan context. This is a supplement to the normal code review, not a separate output.

## Inputs

- `implementation_plan_context.md` contains the plan context to compare against.
- `pr_diff.txt` contains the annotated diff for the PR.
- `pr_description.txt` may contain additional scope or rationale.
- The working tree contains the PR branch contents.

## How to evaluate plan alignment

1. Read `implementation_plan_context.md` and extract the concrete commitments it makes:
   - required behaviors
   - required files or subsystems to change
   - stated constraints
   - required follow-up steps, validation, or migrations
2. Compare those commitments against the actual implementation in `pr_diff.txt` and the checked-out files.
3. Treat small implementation-level adjustments as acceptable when they preserve the plan's intent. Do not flag harmless differences in naming, structure, or low-level technique.
4. Flag a mismatch only when it is material, such as:
   - required behavior in the plan is missing
   - the implementation contradicts a plan decision
   - the change introduces significant unplanned scope
   - a required validation, migration, or compatibility step from the plan is absent

## How to report mismatches

- Do not create a separate report file.
- Fold plan-alignment findings into `review.json`.
- Put broad plan-drift concerns in the review summary.
- Add inline comments only when the mismatch can be tied to changed lines in the diff.
- Treat material plan drift as at least an important concern.
- If the implementation matches the plan closely enough, do not add comments just to mention alignment.

## Boundaries

- Do not require literal one-to-one implementation of the plan when the PR achieves the same outcome safely.
- Do not speculate about plan details that are not actually present in `implementation_plan_context.md`.
- Do not post to GitHub directly.
