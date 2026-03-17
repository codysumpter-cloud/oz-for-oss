import { addTodo, listTodos, completeTodo, deleteTodo, searchTodos, showHelp } from "./app";

const args = process.argv.slice(2);
const command = args[0]?.toLowerCase();

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
