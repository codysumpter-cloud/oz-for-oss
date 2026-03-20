import { describe, it, expect, vi, beforeEach } from "vitest";

describe("deleteTodo", () => {
  let addTodo: typeof import("../app").addTodo;
  let deleteTodo: typeof import("../app").deleteTodo;
  let saveTodos: ReturnType<typeof vi.fn>;

  beforeEach(async () => {
    vi.resetModules();

    vi.doMock("../storage", () => ({
      loadTodos: vi.fn(() => []),
      saveTodos: vi.fn(),
    }));

    const app = await import("../app");
    const storage = await import("../storage");

    addTodo = app.addTodo;
    deleteTodo = app.deleteTodo;
    saveTodos = storage.saveTodos as ReturnType<typeof vi.fn>;
  });

  /** Returns the todos array from the most recent saveTodos call. */
  function lastSavedTodos() {
    const calls = saveTodos.mock.calls;
    return calls[calls.length - 1][0];
  }

  it("deletes only the middle item, leaving items before and after intact", () => {
    addTodo("Task A");
    addTodo("Task B");
    addTodo("Task C");

    deleteTodo(2);

    const remaining = lastSavedTodos();
    expect(remaining).toHaveLength(2);
    expect(remaining[0].text).toBe("Task A");
    expect(remaining[1].text).toBe("Task C");
  });

  it("deletes the first item", () => {
    addTodo("First");
    addTodo("Second");

    deleteTodo(1);

    const remaining = lastSavedTodos();
    expect(remaining).toHaveLength(1);
    expect(remaining[0].text).toBe("Second");
  });

  it("deletes the last item", () => {
    addTodo("Alpha");
    addTodo("Beta");

    deleteTodo(2);

    const remaining = lastSavedTodos();
    expect(remaining).toHaveLength(1);
    expect(remaining[0].text).toBe("Alpha");
  });

  it("prints an error and does not modify the list for out-of-range position", () => {
    addTodo("Only");

    const consoleSpy = vi.spyOn(console, "log");
    saveTodos.mockClear();

    deleteTodo(5);

    expect(consoleSpy).toHaveBeenCalledWith(
      'Invalid todo number: 5. Use "list" to see available todos.'
    );
    expect(saveTodos).not.toHaveBeenCalled();

    consoleSpy.mockRestore();
  });

  it("prints an error for position 0", () => {
    addTodo("Item");

    const consoleSpy = vi.spyOn(console, "log");
    saveTodos.mockClear();

    deleteTodo(0);

    expect(consoleSpy).toHaveBeenCalledWith(
      'Invalid todo number: 0. Use "list" to see available todos.'
    );
    expect(saveTodos).not.toHaveBeenCalled();

    consoleSpy.mockRestore();
  });
});
