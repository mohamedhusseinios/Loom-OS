import Link from "next/link";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

interface ProjectCardProps {
  project: {
    project_id: string;
    project_name: string;
    node_count: number;
    edge_count: number;
    community_count: number;
    active_agents: number;
    last_graph_update: string | null;
  };
}

export function ProjectCard({ project }: ProjectCardProps) {
  const timeAgo = project.last_graph_update
    ? getTimeAgo(new Date(project.last_graph_update))
    : "never";

  return (
    <Link href={`/projects/${project.project_id}`}>
      <Card className="bg-zinc-900 border-zinc-800 hover:border-zinc-700 transition-colors cursor-pointer">
        <CardHeader>
          <CardTitle className="text-zinc-100">{project.project_name}</CardTitle>
          <CardDescription className="text-zinc-500">{project.project_id}</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex gap-4 text-sm">
            <div>
              <span className="text-emerald-400 font-mono">{project.node_count}</span>
              <span className="text-zinc-600 ml-1">nodes</span>
            </div>
            <div>
              <span className="text-blue-400 font-mono">{project.edge_count}</span>
              <span className="text-zinc-600 ml-1">edges</span>
            </div>
            <div>
              <span className="text-purple-400 font-mono">{project.community_count}</span>
              <span className="text-zinc-600 ml-1">communities</span>
            </div>
          </div>
          <div className="flex gap-2 mt-3">
            {project.active_agents > 0 ? (
              <Badge variant="default" className="bg-emerald-900 text-emerald-300 text-xs">
                {project.active_agents} agent{project.active_agents !== 1 ? "s" : ""} active
              </Badge>
            ) : (
              <Badge variant="outline" className="text-zinc-600 text-xs">
                no agents
              </Badge>
            )}
            <span className="text-xs text-zinc-600 self-center">Updated {timeAgo}</span>
          </div>
        </CardContent>
      </Card>
    </Link>
  );
}

function getTimeAgo(date: Date): string {
  const seconds = Math.floor((Date.now() - date.getTime()) / 1000);
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}
