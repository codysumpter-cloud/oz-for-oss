# Issue #5 — Completed status is lost after restarting the app

## Problem
Marking a todo as completed works at runtime, but the completed state is not persisted to `todos.json`. After restarting the app, every todo appears as not completed.

## Root cause
`src/storage.ts` — the `saveTodos` function passes a custom **replacer** to `JSON.stringify` that explicitly drops the `completed` key:

```ts
const replacer = (key: string, value: unknown): unknown => {
  if (key === "completed") {
    return undefined; // ← omits "completed" from the JSON output
  }
  return value;
};
```

Because `completed` is never written to `todos.json`, `loadTodos` parses objects without that field. In JavaScript, a missing boolean property evaluates as `undefined` (falsy), so the UI renders every todo as incomplete.

## Current-state observations
- `Todo` type (`src/types.ts:3-10`) declares `completed: boolean` as a required field.
- `loadTodos` (`src/storage.ts:7-18`) reads the file and returns `Todo[]` without defaulting any missing fields.
- `completeTodo` (`src/app.ts:41-52`) sets `completed = true` on the in-memory array and calls `saveTodos`, which silently strips the field before writing.

## Proposed changes

### 1. Remove the replacer that strips `completed` (`src/storage.ts`)
Delete the custom `replacer` function (or remove the `completed`-filtering branch) so that `JSON.stringify` serialises all `Todo` fields, including `completed`.

After the fix `saveTodos` should look like:

```ts
export function saveTodos(todos: Todo[]): void {
  const data = JSON.stringify(todos, null, 2);
  fs.writeFileSync(DATA_FILE, data, "utf-8");
}
```

### 2. (Defensive) Default `completed` on load (`src/storage.ts`)
Add a mapping step in `loadTodos` to default `completed` to `false` for any record that is missing the field. This protects against data files written before the fix:

```ts
return todos.map(t => ({ ...t, completed: t.completed ?? false }));
```

### 3. Verify with a manual smoke test
Reproduce the original steps from the issue and confirm `completed` survives a restart.

## Risks and open questions
- **Existing data files**: Users who already have a `todos.json` without `completed` fields will see all items default to incomplete, which matches current (broken) behaviour so there is no regression.
- **Other stripped fields**: No other fields are dropped by the replacer today, so removing it entirely is safe.
- **No automated tests exist** in the repo. Consider adding a unit test for the save/load round-trip in a follow-up issue.
