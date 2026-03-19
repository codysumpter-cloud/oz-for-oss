const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { execFileSync } = require("node:child_process");

const repoRoot = path.resolve(__dirname, "..");
const cliPath = path.join(repoRoot, "dist", "index.js");

function runCli(args, cwd) {
  return execFileSync(process.execPath, [cliPath, ...args], {
    cwd,
    encoding: "utf8",
  });
}

test("complete marks the first listed todo", () => {
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "todo-app-"));

  runCli(["add", "First task"], tempDir);
  runCli(["add", "Second task"], tempDir);

  const beforeComplete = runCli(["list"], tempDir);
  assert.match(beforeComplete, /1\. \[ \] First task/);
  assert.match(beforeComplete, /2\. \[ \] Second task/);

  runCli(["complete", "1"], tempDir);

  const afterComplete = runCli(["list"], tempDir);
  assert.match(afterComplete, /1\. \[✓\] First task/);
  assert.match(afterComplete, /2\. \[ \] Second task/);

  const todos = JSON.parse(fs.readFileSync(path.join(tempDir, "todos.json"), "utf8"));
  assert.equal(todos[0].text, "First task");
  assert.equal(todos[0].completed, true);
  assert.equal(todos[1].text, "Second task");
  assert.equal(todos[1].completed, false);
});
