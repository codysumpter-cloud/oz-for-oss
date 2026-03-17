# Todo App

A simple command-line todo list application built with TypeScript. All data is stored locally in a `todos.json` file — no external databases or services required.

## Setup

```bash
npm install
npm run build
```

## Usage

```bash
# Add a todo
node dist/index.js add "Buy groceries"

# List all todos
node dist/index.js list

# Mark a todo as completed (by position number)
node dist/index.js complete 1

# Delete a todo (by position number)
node dist/index.js delete 2

# Search todos
node dist/index.js search "groceries"

# Show help
node dist/index.js help
```

## Development

```bash
# Run directly with ts-node
npm run dev -- add "Buy groceries"

# Build
npm run build
```
