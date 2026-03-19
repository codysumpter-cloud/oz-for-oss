import { Todo } from "./types";
import { loadTodos, saveTodos } from "./storage";

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

  const displayTodos = todos;

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
  const index = position - 1;

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

export function showHelp(): void {
  console.log(`
Todo App - A simple command-line todo list manager

Usage:
  todo add <text>          Add a new todo
  todo list                List all todos
  todo complete <number>   Mark a todo as completed (by position number)
  todo delete <number>     Delete a todo (by position number)
  todo search <query>      Search todos by text
  todo help                Show this help message

Examples:
  todo add "Buy groceries"
  todo list
  todo complete 1
  todo delete 2
  todo search "groceries"
`);
}
