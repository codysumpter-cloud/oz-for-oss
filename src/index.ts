import {
  addTodo,
  listTodos,
  completeTodo,
  deleteTodo,
  searchTodos,
  editTodo,
  setPriority,
  listByPriority,
  setDueDate,
  listOverdue,
  clearCompleted,
  showHelp,
} from "./app";
import { Priority } from "./types";

const args = process.argv.slice(2);
const command = args[0]?.toLowerCase();

const VALID_PRIORITIES: Priority[] = ["high", "medium", "low"];

switch (command) {
  case "add": {
    const text = args.slice(1).join(" ");
    if (!text) {
      console.log('Please provide a todo text. Example: todo add "Buy groceries"');
      process.exit(1);
    }
    addTodo(text);
    break;
  }

  case "list":
  case "ls":
    listTodos();
    break;

  case "complete":
  case "done": {
    const num = parseInt(args[1], 10);
    if (isNaN(num)) {
      console.log("Please provide a valid todo number. Example: todo complete 1");
      process.exit(1);
    }
    completeTodo(num);
    break;
  }

  case "delete":
  case "rm": {
    const num = parseInt(args[1], 10);
    if (isNaN(num)) {
      console.log("Please provide a valid todo number. Example: todo delete 1");
      process.exit(1);
    }
    deleteTodo(num);
    break;
  }

  case "edit": {
    const num = parseInt(args[1], 10);
    const newText = args.slice(2).join(" ");
    if (isNaN(num) || !newText) {
      console.log('Please provide a todo number and new text. Example: todo edit 1 "New text"');
      process.exit(1);
    }
    editTodo(num, newText);
    break;
  }

  case "priority": {
    const num = parseInt(args[1], 10);
    const priority = args[2]?.toLowerCase() as Priority;
    if (isNaN(num) || !VALID_PRIORITIES.includes(priority)) {
      console.log("Please provide a todo number and priority (high, medium, low). Example: todo priority 1 high");
      process.exit(1);
    }
    setPriority(num, priority);
    break;
  }

  case "filter": {
    const priority = args[1]?.toLowerCase() as Priority;
    if (!VALID_PRIORITIES.includes(priority)) {
      console.log("Please provide a priority level (high, medium, low). Example: todo filter high");
      process.exit(1);
    }
    listByPriority(priority);
    break;
  }

  case "due": {
    const num = parseInt(args[1], 10);
    const dateStr = args[2];
    if (isNaN(num) || !dateStr) {
      console.log("Please provide a todo number and date. Example: todo due 1 2025-12-31");
      process.exit(1);
    }
    setDueDate(num, dateStr);
    break;
  }

  case "overdue":
    listOverdue();
    break;

  case "clear":
    clearCompleted();
    break;

  case "search":
  case "find": {
    const query = args.slice(1).join(" ");
    if (!query) {
      console.log("Please provide a search query. Example: todo search groceries");
      process.exit(1);
    }
    searchTodos(query);
    break;
  }

  case "help":
  case "--help":
  case "-h":
    showHelp();
    break;

  default:
    if (command) {
      console.log(`Unknown command: "${command}"`);
    }
    showHelp();
    break;
}
