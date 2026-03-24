export type Priority = "high" | "medium" | "low";

export interface Subtask {
  id: number;
  text: string;
  completed: boolean;
}

export interface Todo {
  id: number;
  text: string;
  completed: boolean;
  createdAt: string;
  priority?: Priority;
  dueDate?: string;
  subtasks?: Subtask[];
}
