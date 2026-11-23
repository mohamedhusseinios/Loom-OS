import { Suspense } from "react";
import { AgentAppShell } from "@/components/agent-app-shell";

// Shell reads ?project= / ?task= via useSearchParams (client), so it must sit
// inside a Suspense boundary for prerendering.
export default function AgentAppPage() {
  return (
    <Suspense fallback={null}>
      <AgentAppShell />
    </Suspense>
  );
}
