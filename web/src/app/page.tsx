import { getPipelineData, getOwnerRepo } from "@/lib/github";
import { PipelineBoard } from "@/components/pipeline-board";
import type { PipelineItem } from "@/lib/types";

export default async function DashboardPage() {
  let items: PipelineItem[];
  let error: string | null = null;
  const { owner, repo } = getOwnerRepo();

  try {
    items = await getPipelineData();
  } catch (e) {
    error = e instanceof Error ? e.message : "Failed to load pipeline data";
    items = [];
  }

  return (
    <div className="container max-w-screen-2xl px-6 py-8">
      <div className="mb-8">
        <h1 className="text-2xl font-bold tracking-tight">Pipeline</h1>
        <p className="text-muted-foreground mt-1">
          Track issues and PRs across the{" "}
          <a
            href={`https://github.com/${owner}/${repo}`}
            target="_blank"
            rel="noopener noreferrer"
            className="text-primary hover:underline"
          >
            {owner}/{repo}
          </a>{" "}
          workflow &mdash; from spec to implementation.
        </p>
      </div>
      {error && (
        <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-4 mb-6">
          <p className="text-sm text-destructive font-medium">
            Failed to load data from GitHub
          </p>
          <p className="text-xs text-destructive/80 mt-1">{error}</p>
          <p className="text-xs text-muted-foreground mt-2">
            Make sure <code className="bg-muted px-1 rounded">GITHUB_TOKEN</code> is set
            in your environment.
          </p>
        </div>
      )}
      <PipelineBoard items={items} />
    </div>
  );
}
