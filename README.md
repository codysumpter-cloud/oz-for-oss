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

# Edit a todo's text
node dist/index.js edit 1 "Buy organic groceries"

# Set priority (high, medium, low)
node dist/index.js priority 1 high

# Filter todos by priority
node dist/index.js filter high

# Set a due date
node dist/index.js due 1 2025-12-31

# List overdue todos
node dist/index.js overdue

# Remove all completed todos
node dist/index.js clear

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
