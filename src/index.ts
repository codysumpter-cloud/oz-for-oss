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
  listPending,
  listCompleted,
  listSorted,
  listToday,
  listUpcoming,
  addSubtask,
  completeSubtask,
  listSubtasks,
  archiveCompleted,
  listArchived,
  restoreFromArchive,
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
  case "ls": {
    if (args.includes("--pending")) {
      listPending();
    } else if (args.includes("--completed")) {
      listCompleted();
    } else if (args.includes("--sort")) {
      const sortIdx = args.indexOf("--sort");
      const sortField = args[sortIdx + 1];
      if (!sortField) {
        console.log("Please provide a sort field: due, priority, or created.");
        process.exit(1);
      }
      listSorted(sortField);
    } else {
      listTodos();
    }
    break;
  }

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

  case "today":
    listToday();
    break;

  case "upcoming":
    listUpcoming();
    break;

  case "subtask": {
    const subCmd = args[1]?.toLowerCase();
    switch (subCmd) {
      case "add": {
        const num = parseInt(args[2], 10);
        const text = args.slice(3).join(" ");
        if (isNaN(num) || !text) {
          console.log('Usage: todo subtask add <number> <text>');
          process.exit(1);
        }
        addSubtask(num, text);
        break;
      }
      case "done": {
        const num = parseInt(args[2], 10);
        const sid = parseInt(args[3], 10);
        if (isNaN(num) || isNaN(sid)) {
          console.log('Usage: todo subtask done <number> <subtask_id>');
          process.exit(1);
        }
        completeSubtask(num, sid);
        break;
      }
      case "list": {
        const num = parseInt(args[2], 10);
        if (isNaN(num)) {
          console.log('Usage: todo subtask list <number>');
          process.exit(1);
        }
        listSubtasks(num);
        break;
      }
      default:
        console.log('Usage: todo subtask <add|done|list> ...');
        break;
    }
    break;
  }

  case "archive":
    archiveCompleted();
    break;

  case "archived":
    listArchived();
    break;

  case "restore": {
    const id = parseInt(args[1], 10);
    if (isNaN(id)) {
      console.log("Please provide an archived todo id. Example: todo restore 3");
      process.exit(1);
    }
    restoreFromArchive(id);
    break;
  }

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
