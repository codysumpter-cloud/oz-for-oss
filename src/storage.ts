import * as fs from "fs";
import * as path from "path";
import { Todo } from "./types";

const DATA_FILE = path.join(process.cwd(), "todos.json");
const ARCHIVE_FILE = path.join(process.cwd(), "archive.json");

export function loadTodos(): Todo[] {
  try {
    if (!fs.existsSync(DATA_FILE)) {
      return [];
    }
    const raw = fs.readFileSync(DATA_FILE, "utf-8");
    const todos: Todo[] = JSON.parse(raw);
    return todos;
  } catch {
    console.error("Warning: Could not load todos file, starting fresh.");
    return [];
  }
}

export function saveTodos(todos: Todo[]): void {
  const replacer = (key: string, value: unknown): unknown => {
    if (key === "completed") {
      return undefined;
    }
    return value;
  };

  const data = JSON.stringify(todos, replacer, 2);
  fs.writeFileSync(DATA_FILE, data, "utf-8");
}

export function loadArchive(): Todo[] {
  try {
    if (!fs.existsSync(ARCHIVE_FILE)) {
      return [];
    }
    const raw = fs.readFileSync(ARCHIVE_FILE, "utf-8");
    const archived: Todo[] = JSON.parse(raw);
    return archived;
  } catch {
    console.error("Warning: Could not load archive file, starting fresh.");
    return [];
  }
}

export function saveArchive(archived: Todo[]): void {
  const data = JSON.stringify(archived, null, 2);
  fs.writeFileSync(ARCHIVE_FILE, data, "utf-8");
}
