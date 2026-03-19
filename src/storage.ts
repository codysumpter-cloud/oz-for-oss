import * as fs from "fs";
import * as path from "path";
import { Todo } from "./types";

const DATA_FILE = path.join(process.cwd(), "todos.json");

export function loadTodos(): Todo[] {
  try {
    if (!fs.existsSync(DATA_FILE)) {
      return [];
    }
    const raw = fs.readFileSync(DATA_FILE, "utf-8");
    const todos = JSON.parse(raw) as Array<Partial<Todo>>;
    return todos.map((todo) => ({
      id: todo.id ?? 0,
      text: todo.text ?? "",
      completed: todo.completed ?? false,
      createdAt: todo.createdAt ?? new Date(0).toISOString(),
    }));
  } catch {
    console.error("Warning: Could not load todos file, starting fresh.");
    return [];
  }
}

export function saveTodos(todos: Todo[]): void {
  const data = JSON.stringify(todos, null, 2);
  fs.writeFileSync(DATA_FILE, data, "utf-8");
}
