import { Badge } from "@/components/ui/badge";

interface AgentBadgeProps {
  agent: {
    agent_name: string;
    status: "online" | "offline" | "working";
    capabilities: string[];
    last_heartbeat: string | null;
  };
}

export function AgentBadge({ agent }: AgentBadgeProps) {
  const statusColor = {
    online: "bg-emerald-900 text-emerald-300",
    working: "bg-amber-900 text-amber-300",
    offline: "bg-zinc-800 text-zinc-500",
  };

  return (
    <div className="flex items-center gap-3 py-2">
      <div
        className={`w-2 h-2 rounded-full ${
          agent.status === "online"
            ? "bg-emerald-400"
            : agent.status === "working"
            ? "bg-amber-400"
            : "bg-zinc-600"
        }`}
      />
      <div className="flex-1">
        <div className="text-sm text-zinc-200">{agent.agent_name}</div>
        <div className="text-xs text-zinc-500">{agent.capabilities.join(", ")}</div>
      </div>
      <Badge className={statusColor[agent.status]} variant="outline">
        {agent.status}
      </Badge>
    </div>
  );
}
