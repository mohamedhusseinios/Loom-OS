"use client";

import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

type TaskStatus =
  | "todo"
  | "ready"
  | "running"
  | "blocked"
  | "done";

const COLUMNS: { status: TaskStatus; label: string; color: string }[] = [
  { status: "todo", label: "To Do", color: "text-zinc-400" },
  { status: "ready", label: "Ready", color: "text-blue-400" },
  { status: "running", label: "Running", color: "text-amber-400" },
  { status: "blocked", label: "Blocked", color: "text-red-400" },
  { status: "done", label: "Done", color: "text-emerald-400" },
];

export interface AgentTask {
  id: string;
  title: string;
  status: TaskStatus;
  assignee: string | null;
  priority: number;
  dependencies: string[];
}

interface TaskBoardProps {
  tasks: AgentTask[];
}

export function TaskBoard({ tasks }: TaskBoardProps) {
  if (!tasks.length) {
    return (
      <Card className="bg-zinc-950 border-zinc-800">
        <CardContent className="p-4">
          <p className="text-zinc-500 text-xs">
            No tasks yet. Create tasks to coordinate agents via the Kanban board.
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="grid grid-cols-5 gap-3">
      {COLUMNS.map((col) => {
        const columnTasks = tasks.filter((t) => t.status === col.status);
        return (
          <div key={col.status} className="space-y-2">
            <div className="flex items-center gap-2">
              <span className={`text-xs font-medium ${col.color}`}>
                {col.label}
              </span>
              <Badge variant="outline" className="text-xs">
                {columnTasks.length}
              </Badge>
            </div>
            <div className="space-y-2">
              {columnTasks.map((task) => (
                <Card
                  key={task.id}
                  className="bg-zinc-900 border-zinc-800 p-2"
                >
                  <p className="text-zinc-200 text-xs font-medium">
                    {task.title}
                  </p>
                  {task.assignee && (
                    <p className="text-zinc-500 text-xs mt-1">
                      {task.assignee}
                    </p>
                  )}
                  {task.dependencies.length > 0 && (
                    <p className="text-zinc-600 text-xs mt-1">
                      Depends on: {task.dependencies.join(", ")}
                    </p>
                  )}
                </Card>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}
