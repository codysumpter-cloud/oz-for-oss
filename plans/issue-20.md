# Issue #20 — Bug: edit command has off-by-one error

## Problem
`editTodo` in `src/app.ts` uses the user-supplied 1-based `position` directly as the array index (`const index = position;` at line 86). This means `todo edit 1 "text"` modifies `todos[1]` (the **second** item) instead of `todos[0]` (the **first** item).

## Current State
- `editTodo` (line 86): `const index = position;` — **buggy**, no conversion from 1-based to 0-based.
- Other functions that correctly subtract 1: `deleteTodo` (line 55), `setPriority` (line 100), `setDueDate` (line 132).
- `completeTodo` (line 42) has the **same off-by-one bug** (`const index = position;`). This is out of scope for this issue but worth noting.

## Proposed Changes
**File:** `src/app.ts`

1. **`editTodo` function (line 86):** Change `const index = position;` to `const index = position - 1;` so the 1-based user input maps to the correct 0-based array index. No other lines in the function need to change — the existing bounds check and array access already use `index`.

## Risks / Notes
- `completeTodo` has the identical off-by-one bug but is not part of this issue. A follow-up issue should be filed for it.
- The fix is a single-character change with no risk of side effects.
