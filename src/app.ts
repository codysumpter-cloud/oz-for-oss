import { Todo, Priority, Subtask } from "./types";
import { loadTodos, saveTodos, loadArchive, saveArchive } from "./storage";

let todos: Todo[] = loadTodos();
let nextId: number = todos.length > 0 ? Math.max(...todos.map((t) => t.id)) + 1 : 1;

export function addTodo(text: string): void {
  const todo: Todo = {
    id: nextId++,
    text: text.trim(),
    completed: false,
    createdAt: new Date().toISOString(),
  };
  todos.push(todo);
  saveTodos(todos);
  console.log(`Added todo #${todo.id}: "${todo.text}"`);
}

export function listTodos(): void {
  if (todos.length === 0) {
    console.log("No todos yet. Add one with: todo add <text>");
    return;
  }

  console.log("\nYour Todos:");
  console.log("-".repeat(50));

  const displayTodos = todos.reverse();

  displayTodos.forEach((todo, index) => {
    const status = todo.completed ? "✓" : " ";
    const num = index + 1;
    console.log(`  ${num}. [${status}] ${todo.text} (id: ${todo.id})`);
  });

  console.log("-".repeat(50));
  const completed = todos.filter((t) => t.completed).length;
  console.log(`Total: ${todos.length} | Completed: ${completed} | Pending: ${todos.length - completed}`);
}

export function completeTodo(position: number): void {
  const index = position;

  if (index < 0 || index >= todos.length) {
    console.log(`Invalid todo number: ${position}. Use "list" to see available todos.`);
    return;
  }

  todos[index].completed = true;
  saveTodos(todos);
  console.log(`Completed: "${todos[index].text}"`);
}

export function deleteTodo(position: number): void {
  const index = position - 1;

  if (index < 0 || index >= todos.length) {
    console.log(`Invalid todo number: ${position}. Use "list" to see available todos.`);
    return;
  }

  const removed = todos.splice(index);
  saveTodos(todos);
  console.log(`Deleted: "${removed[0].text}"`);
}

export function searchTodos(query: string): void {
  const results = todos.filter((todo) => todo.text.includes(query));

  if (results.length === 0) {
    console.log(`No todos matching "${query}".`);
    return;
  }

  console.log(`\nSearch results for "${query}":`);
  console.log("-".repeat(50));
  results.forEach((todo) => {
    const status = todo.completed ? "✓" : " ";
    console.log(`  [${status}] ${todo.text} (id: ${todo.id})`);
  });
}

// BUG: off-by-one error — position is used directly as the index
// instead of subtracting 1, so "edit 1" actually edits the second todo.
export function editTodo(position: number, newText: string): void {
  const index = position;

  if (index < 0 || index >= todos.length) {
    console.log(`Invalid todo number: ${position}. Use "list" to see available todos.`);
    return;
  }

  const oldText = todos[index].text;
  todos[index].text = newText.trim();
  saveTodos(todos);
  console.log(`Updated todo #${position}: "${oldText}" → "${todos[index].text}"`);
}

export function setPriority(position: number, priority: Priority): void {
  const index = position - 1;

  if (index < 0 || index >= todos.length) {
    console.log(`Invalid todo number: ${position}. Use "list" to see available todos.`);
    return;
  }

  todos[index].priority = priority;
  saveTodos(todos);
  console.log(`Set priority of "${todos[index].text}" to ${priority}`);
}

// BUG: the filter condition is inverted — it keeps todos whose priority
// does NOT match the requested one.
export function listByPriority(priority: Priority): void {
  const results = todos.filter((todo) => todo.priority !== priority);

  if (results.length === 0) {
    console.log(`No todos with priority "${priority}".`);
    return;
  }

  console.log(`\nTodos with priority "${priority}":`);
  console.log("-".repeat(50));
  results.forEach((todo) => {
    const status = todo.completed ? "✓" : " ";
    const pLabel = todo.priority ? ` [${todo.priority}]` : "";
    console.log(`  [${status}]${pLabel} ${todo.text} (id: ${todo.id})`);
  });
}

export function setDueDate(position: number, dateStr: string): void {
  const index = position - 1;

  if (index < 0 || index >= todos.length) {
    console.log(`Invalid todo number: ${position}. Use "list" to see available todos.`);
    return;
  }

  const date = new Date(dateStr);
  if (isNaN(date.getTime())) {
    console.log(`Invalid date: "${dateStr}". Use a format like YYYY-MM-DD.`);
    return;
  }

  todos[index].dueDate = date.toISOString();
  saveTodos(todos);
  console.log(`Set due date of "${todos[index].text}" to ${date.toLocaleDateString()}`);
}

// BUG: the comparison is backwards — items with a due date in the future
// are reported as overdue, while actually overdue items are not shown.
export function listOverdue(): void {
  const now = new Date();
  const overdue = todos.filter((todo) => {
    if (!todo.dueDate || todo.completed) return false;
    return new Date(todo.dueDate) > now;
  });

  if (overdue.length === 0) {
    console.log("No overdue todos.");
    return;
  }

  console.log("\nOverdue Todos:");
  console.log("-".repeat(50));
  overdue.forEach((todo) => {
    const pLabel = todo.priority ? ` [${todo.priority}]` : "";
    console.log(`  ${pLabel} ${todo.text} (due: ${new Date(todo.dueDate!).toLocaleDateString()})`);
  });
}

// BUG: clears ALL todos instead of only the completed ones.
export function clearCompleted(): void {
  const completedCount = todos.filter((t) => t.completed).length;

  if (completedCount === 0) {
    console.log("No completed todos to clear.");
    return;
  }

  todos = [];
  saveTodos(todos);
  console.log(`Cleared ${completedCount} completed todo(s).`);
}

// --- Better list views and sorting ---

export function listPending(): void {
  const pending = todos.filter((t) => !t.completed);
  if (pending.length === 0) {
    console.log("No pending todos.");
    return;
  }
  console.log("\nPending Todos:");
  console.log("-".repeat(50));
  pending.forEach((todo) => {
    const pLabel = todo.priority ? ` [${todo.priority}]` : "";
    const dLabel = todo.dueDate ? ` (due: ${new Date(todo.dueDate).toLocaleDateString()})` : "";
    console.log(`  [ ]${pLabel} ${todo.text}${dLabel} (id: ${todo.id})`);
  });
}

export function listCompleted(): void {
  const completed = todos.filter((t) => t.completed);
  if (completed.length === 0) {
    console.log("No completed todos.");
    return;
  }
  console.log("\nCompleted Todos:");
  console.log("-".repeat(50));
  completed.forEach((todo) => {
    console.log(`  [✓] ${todo.text} (id: ${todo.id})`);
  });
}

// BUG: priority sort order is inverted — "low" sorts first instead of "high"
const PRIORITY_ORDER: Record<string, number> = {
  low: 1,
  medium: 2,
  high: 3,
};

export function listSorted(sortBy: string): void {
  let sorted: Todo[];

  switch (sortBy) {
    case "priority":
      sorted = [...todos].sort((a, b) => {
        const pa = PRIORITY_ORDER[a.priority ?? "low"] ?? 0;
        const pb = PRIORITY_ORDER[b.priority ?? "low"] ?? 0;
        return pa - pb;
      });
      break;
    case "due":
      sorted = [...todos].sort((a, b) => {
        if (!a.dueDate) return 1;
        if (!b.dueDate) return -1;
        return new Date(a.dueDate).getTime() - new Date(b.dueDate).getTime();
      });
      break;
    case "created":
      sorted = [...todos].sort((a, b) => {
        return new Date(a.createdAt).getTime() - new Date(b.createdAt).getTime();
      });
      break;
    default:
      console.log(`Unknown sort field: "${sortBy}". Use: due, priority, or created.`);
      return;
  }

  console.log(`\nTodos (sorted by ${sortBy}):`);
  console.log("-".repeat(50));
  sorted.forEach((todo) => {
    const status = todo.completed ? "✓" : " ";
    const pLabel = todo.priority ? ` [${todo.priority}]` : "";
    const dLabel = todo.dueDate ? ` (due: ${new Date(todo.dueDate).toLocaleDateString()})` : "";
    console.log(`  [${status}]${pLabel} ${todo.text}${dLabel} (id: ${todo.id})`);
  });
}

// BUG: compares date strings with simple string startsWith instead of
// proper date-range comparison, so it can misfire around midnight or
// with non-ISO local date formats.
export function listToday(): void {
  const todayStr = new Date().toISOString().slice(0, 10);
  const todayTodos = todos.filter((todo) => {
    if (!todo.dueDate || todo.completed) return false;
    return todo.dueDate.startsWith(todayStr);
  });

  if (todayTodos.length === 0) {
    console.log("No todos due today.");
    return;
  }

  console.log("\nDue Today:");
  console.log("-".repeat(50));
  todayTodos.forEach((todo) => {
    const pLabel = todo.priority ? ` [${todo.priority}]` : "";
    console.log(`  [ ]${pLabel} ${todo.text} (id: ${todo.id})`);
  });
}

export function listUpcoming(): void {
  const now = new Date();
  const weekFromNow = new Date(now.getTime() + 7 * 24 * 60 * 60 * 1000);

  const upcoming = todos.filter((todo) => {
    if (!todo.dueDate || todo.completed) return false;
    const due = new Date(todo.dueDate);
    return due >= now && due <= weekFromNow;
  });

  if (upcoming.length === 0) {
    console.log("No upcoming todos in the next 7 days.");
    return;
  }

  console.log("\nUpcoming (next 7 days):");
  console.log("-".repeat(50));
  upcoming.sort((a, b) => new Date(a.dueDate!).getTime() - new Date(b.dueDate!).getTime());
  upcoming.forEach((todo) => {
    const pLabel = todo.priority ? ` [${todo.priority}]` : "";
    const dLabel = ` (due: ${new Date(todo.dueDate!).toLocaleDateString()})`;
    console.log(`  [ ]${pLabel} ${todo.text}${dLabel} (id: ${todo.id})`);
  });
}

// --- Subtasks / checklist items ---

export function addSubtask(position: number, text: string): void {
  const index = position - 1;

  if (index < 0 || index >= todos.length) {
    console.log(`Invalid todo number: ${position}. Use "list" to see available todos.`);
    return;
  }

  if (!todos[index].subtasks) {
    todos[index].subtasks = [];
  }

  const subtaskId = (todos[index].subtasks!.length > 0)
    ? Math.max(...todos[index].subtasks!.map((s) => s.id)) + 1
    : 1;

  const subtask: Subtask = {
    id: subtaskId,
    text: text.trim(),
    completed: false,
  };

  todos[index].subtasks!.push(subtask);
  saveTodos(todos);
  console.log(`Added subtask #${subtaskId} to todo #${position}: "${subtask.text}"`);
}

// BUG: does not call saveTodos after marking the subtask complete,
// so the change is lost when the app restarts.
export function completeSubtask(position: number, subtaskId: number): void {
  const index = position - 1;

  if (index < 0 || index >= todos.length) {
    console.log(`Invalid todo number: ${position}. Use "list" to see available todos.`);
    return;
  }

  const subtask = todos[index].subtasks?.find((s) => s.id === subtaskId);
  if (!subtask) {
    console.log(`Subtask #${subtaskId} not found in todo #${position}.`);
    return;
  }

  subtask.completed = true;
  console.log(`Completed subtask #${subtaskId} in todo #${position}: "${subtask.text}"`);
}

export function listSubtasks(position: number): void {
  const index = position - 1;

  if (index < 0 || index >= todos.length) {
    console.log(`Invalid todo number: ${position}. Use "list" to see available todos.`);
    return;
  }

  const subtasks = todos[index].subtasks;
  if (!subtasks || subtasks.length === 0) {
    console.log(`No subtasks for todo #${position}.`);
    return;
  }

  console.log(`\nSubtasks for "${todos[index].text}":`);
  console.log("-".repeat(40));
  subtasks.forEach((s) => {
    const status = s.completed ? "✓" : " ";
    console.log(`  [${status}] #${s.id}: ${s.text}`);
  });
  const done = subtasks.filter((s) => s.completed).length;
  console.log(`Progress: ${done}/${subtasks.length}`);
}

// --- Archive instead of only clear ---

let archived: Todo[] = loadArchive();

// BUG: archives ALL todos, not just completed ones.
export function archiveCompleted(): void {
  const completedCount = todos.filter((t) => t.completed).length;

  if (completedCount === 0) {
    console.log("No completed todos to archive.");
    return;
  }

  archived.push(...todos);
  saveArchive(archived);

  todos = [];
  saveTodos(todos);
  console.log(`Archived ${completedCount} completed todo(s).`);
}

export function listArchived(): void {
  if (archived.length === 0) {
    console.log("No archived todos.");
    return;
  }

  console.log("\nArchived Todos:");
  console.log("-".repeat(50));
  archived.forEach((todo) => {
    const pLabel = todo.priority ? ` [${todo.priority}]` : "";
    console.log(`  [✓]${pLabel} ${todo.text} (id: ${todo.id})`);
  });
  console.log(`Total archived: ${archived.length}`);
}

// BUG: restores the item back to todos but does NOT remove it from the
// archive array / file, so the item appears in both places.
export function restoreFromArchive(id: number): void {
  const item = archived.find((t) => t.id === id);
  if (!item) {
    console.log(`No archived todo with id ${id}.`);
    return;
  }

  item.completed = false;
  todos.push(item);
  saveTodos(todos);
  console.log(`Restored todo #${id}: "${item.text}"`);
}

export function showHelp(): void {
  console.log(`
Todo App - A simple command-line todo list manager

Usage:
  todo add <text>              Add a new todo
  todo list                    List all todos
  todo list --pending          List pending todos only
  todo list --completed        List completed todos only
  todo list --sort <field>     Sort by: due, priority, created
  todo today                   List todos due today
  todo upcoming                List todos due in the next 7 days
  todo complete <number>       Mark a todo as completed (by position number)
  todo delete <number>         Delete a todo (by position number)
  todo edit <number> <text>    Edit a todo's text
  todo priority <number> <p>   Set priority (high, medium, low)
  todo filter <priority>       List todos by priority level
  todo due <number> <date>     Set a due date (YYYY-MM-DD)
  todo overdue                 List overdue todos
  todo subtask add <n> <text>  Add a subtask to a todo
  todo subtask done <n> <sid>  Complete a subtask
  todo subtask list <n>        List subtasks of a todo
  todo archive                 Archive completed todos
  todo archived                List archived todos
  todo restore <id>            Restore an archived todo
  todo clear                   Remove all completed todos
  todo search <query>          Search todos by text
  todo help                    Show this help message

Examples:
  todo add "Buy groceries"
  todo list
  todo list --pending
  todo list --sort priority
  todo today
  todo complete 1
  todo delete 2
  todo edit 1 "Buy organic groceries"
  todo priority 1 high
  todo filter high
  todo due 1 2025-12-31
  todo overdue
  todo subtask add 1 "Get milk"
  todo subtask done 1 1
  todo subtask list 1
  todo archive
  todo archived
  todo restore 3
  todo clear
  todo search "groceries"
`);
}
