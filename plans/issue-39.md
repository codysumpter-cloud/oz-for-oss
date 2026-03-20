# Issue #39 — Completed status is lost after restarting the app

## Problem
After marking a todo as completed, the completed status is not persisted to disk. Restarting the app causes all todos to appear as not completed.

## Root cause
In `src/storage.ts` (lines 22–27), the `saveTodos` function passes a custom `replacer` to `JSON.stringify` that explicitly excludes the `completed` key:

```ts
const replacer = (key: string, value: unknown): unknown => {
  if (key === "completed") {
    return undefined;
  }
  return value;
};
```

Returning `undefined` from a JSON replacer causes the property to be omitted from the serialized output. When `loadTodos` later parses the file, the `completed` field is absent, so it becomes `undefined` (falsy), and every todo appears incomplete.

## Current state
- `src/types.ts` — defines `Todo` with a `completed: boolean` field.
- `src/storage.ts` — `loadTodos` reads `todos.json`; `saveTodos` writes it but drops `completed` via the replacer.
- `src/app.ts` — `completeTodo` sets `completed = true` and calls `saveTodos`, but the flag is never actually written.

## Proposed changes
1. **Remove the custom replacer in `saveTodos`** (`src/storage.ts`).
   Replace the current `JSON.stringify(todos, replacer, 2)` call with `JSON.stringify(todos, null, 2)` (or remove the `replacer` function entirely). This ensures all `Todo` fields — including `completed` — are written to `todos.json`.

No other files need to change; the `Todo` interface already declares `completed: boolean`, and `loadTodos` already parses the full object. Once the field is persisted, the round-trip will work correctly.

## Risks and considerations
- **Existing `todos.json` files** — Any `todos.json` written before the fix will lack the `completed` field. When loaded, `completed` will be `undefined`. The app already treats falsy as "not completed", so existing data will behave the same as before (no migration needed), but previously-completed items cannot be recovered.
- **Test coverage** — There are currently no tests in the repository. Adding a unit test for the save/load round-trip of the `completed` field would prevent this regression from recurring. This is recommended but may be tracked separately.

## Open questions
None — the fix is straightforward.
