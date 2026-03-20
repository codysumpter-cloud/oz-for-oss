import { describe, it, expect, vi, beforeEach } from "vitest";
import type { Todo } from "./types";

// We need to reset modules between tests because `todos` is module-level state
// initialized by `loadTodos()` at import time.

function makeTodo(overrides: Partial<Todo> & { id: number; text: string }): Todo {
  return {
    completed: false,
    createdAt: new Date().toISOString(),
    ...overrides,
  };
}

describe("clearCompleted", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.restoreAllMocks();
  });

  it("removes only completed todos and leaves pending ones intact", async () => {
    const pending1 = makeTodo({ id: 1, text: "Pending task" });
    const done1 = makeTodo({ id: 2, text: "Done task", completed: true });
    const pending2 = makeTodo({ id: 3, text: "Another pending" });

    const saveMock = vi.fn();
    vi.doMock("./storage", () => ({
      loadTodos: () => [pending1, done1, pending2],
      saveTodos: saveMock,
    }));

    const { clearCompleted } = await import("./app");
    clearCompleted();

    expect(saveMock).toHaveBeenCalledOnce();
    const saved: Todo[] = saveMock.mock.calls[0][0];
    expect(saved).toHaveLength(2);
    expect(saved.map((t) => t.id)).toEqual([1, 3]);
  });

  it("is a no-op and prints a message when no todos are completed", async () => {
    const todo1 = makeTodo({ id: 1, text: "Task A" });
    const todo2 = makeTodo({ id: 2, text: "Task B" });

    const saveMock = vi.fn();
    vi.doMock("./storage", () => ({
      loadTodos: () => [todo1, todo2],
      saveTodos: saveMock,
    }));

    const consoleSpy = vi.spyOn(console, "log");
    const { clearCompleted } = await import("./app");
    clearCompleted();

    expect(saveMock).not.toHaveBeenCalled();
    expect(consoleSpy).toHaveBeenCalledWith("No completed todos to clear.");
  });

  it("results in an empty list when all todos are completed", async () => {
    const done1 = makeTodo({ id: 1, text: "Done A", completed: true });
    const done2 = makeTodo({ id: 2, text: "Done B", completed: true });

    const saveMock = vi.fn();
    vi.doMock("./storage", () => ({
      loadTodos: () => [done1, done2],
      saveTodos: saveMock,
    }));

    const { clearCompleted } = await import("./app");
    clearCompleted();

    expect(saveMock).toHaveBeenCalledOnce();
    const saved: Todo[] = saveMock.mock.calls[0][0];
    expect(saved).toHaveLength(0);
  });
});
