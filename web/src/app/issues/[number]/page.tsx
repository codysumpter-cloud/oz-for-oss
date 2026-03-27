import Link from "next/link";
import { notFound } from "next/navigation";
import {
  getIssue,
  getSpecFiles,
  getOpenPullRequests,
  extractIssueNumber,
  isSpecPR,
  hasLabel,
  getRepoUrl,
} from "@/lib/github";
import { SpecTabs } from "@/components/spec-tabs";
import { StageIndicator } from "@/components/stage-indicator";
import { LabelBadge } from "@/components/label-badge";
import { MarkdownViewer } from "@/components/markdown-viewer";
import { buttonVariants } from "@/components/ui/button-variants";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { cn } from "@/lib/utils";
import type { PipelineStage, GitHubPullRequest } from "@/lib/types";
import {
  ExternalLink,
  ArrowLeft,
  GitPullRequest,
  FileText,
  CircleDot,
  Calendar,
} from "lucide-react";

function determineStage(
  issue: { labels: { name: string }[] },
  specPRs: GitHubPullRequest[],
  codePRs: GitHubPullRequest[]
): PipelineStage {
  if (codePRs.length > 0) return "code-in-review";
  if (hasLabel(issue, "ready-to-implement")) return "ready-to-implement";
  if (specPRs.length > 0) return "spec-in-review";
  return "ready-to-spec";
}

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export default async function IssueDetailPage({
  params,
}: {
  params: Promise<{ number: string }>;
}) {
  const { number: numberStr } = await params;
  const issueNumber = parseInt(numberStr, 10);
  if (isNaN(issueNumber)) notFound();

  let issue;
  try {
    issue = await getIssue(issueNumber);
  } catch {
    notFound();
  }

  // Parallel fetch for specs and PRs
  const [specFiles, allPRs] = await Promise.all([
    getSpecFiles(issueNumber).catch(() => ({ productSpec: null, techSpec: null })),
    getOpenPullRequests().catch(() => [] as GitHubPullRequest[]),
  ]);

  const specPRs = allPRs.filter(
    (pr) => isSpecPR(pr) && extractIssueNumber(pr) === issueNumber
  );
  const codePRs = allPRs.filter(
    (pr) => !isSpecPR(pr) && extractIssueNumber(pr) === issueNumber
  );
  const stage = determineStage(issue, specPRs, codePRs);
  const hasSpecs = specFiles.productSpec || specFiles.techSpec;
  const repoUrl = getRepoUrl();

  return (
    <div className="container max-w-screen-xl px-6 py-8">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 mb-6">
        <Link
          href="/"
          className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground transition-colors"
        >
          <ArrowLeft className="h-4 w-4" />
          Pipeline
        </Link>
        <span className="text-muted-foreground">/</span>
        <span className="text-sm font-medium">Issue #{issueNumber}</span>
      </div>

      {/* Header */}
      <div className="flex flex-col gap-4 mb-8">
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-start gap-3 min-w-0">
            <CircleDot className="h-6 w-6 text-green-600 mt-1 shrink-0" />
            <div>
              <h1 className="text-2xl font-bold tracking-tight leading-tight">
                {issue.title}
              </h1>
              <div className="flex items-center gap-3 mt-2 text-sm text-muted-foreground">
                <span>#{issue.number}</span>
                <span className="flex items-center gap-1">
                  <Calendar className="h-3.5 w-3.5" />
                  {formatDate(issue.created_at)}
                </span>
                <span>by {issue.user.login}</span>
              </div>
            </div>
          </div>
          <a
            href={issue.html_url}
            target="_blank"
            rel="noopener noreferrer"
            className={cn(buttonVariants({ variant: "outline", size: "sm" }), "gap-2 shrink-0")}
          >
            <ExternalLink className="h-4 w-4" />
            View on GitHub
          </a>
        </div>

        {/* Stage indicator */}
        <StageIndicator currentStage={stage} />

        {/* Labels */}
        <div className="flex flex-wrap gap-1.5">
          {issue.labels.map((label) => (
            <LabelBadge key={label.id} label={label} />
          ))}
        </div>

        {/* Assignees */}
        {issue.assignees.length > 0 && (
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground">Assigned to:</span>
            {issue.assignees.map((user) => (
              <div key={user.login} className="flex items-center gap-1">
                <Avatar className="h-5 w-5">
                  <AvatarImage src={user.avatar_url} alt={user.login} />
                  <AvatarFallback className="text-[10px]">
                    {user.login.slice(0, 2).toUpperCase()}
                  </AvatarFallback>
                </Avatar>
                <a
                  href={user.html_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-xs hover:underline"
                >
                  {user.login}
                </a>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Main content */}
        <div className="lg:col-span-2 space-y-8">
          {/* Issue body */}
          {issue.body && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Issue Description</CardTitle>
              </CardHeader>
              <CardContent>
                <MarkdownViewer content={issue.body} />
              </CardContent>
            </Card>
          )}

          {/* Spec viewer */}
          {hasSpecs && (
            <Card>
              <CardHeader>
                <div className="flex items-center justify-between">
                  <CardTitle className="text-base flex items-center gap-2">
                    <FileText className="h-4 w-4" />
                    Specs
                  </CardTitle>
                  <Link
                    href={`/specs/${issueNumber}`}
                    className={cn(buttonVariants({ variant: "outline", size: "sm" }), "gap-2")}
                  >
                    Full Spec View
                    <ExternalLink className="h-3 w-3" />
                  </Link>
                </div>
              </CardHeader>
              <CardContent>
                <SpecTabs
                  productSpec={specFiles.productSpec}
                  techSpec={specFiles.techSpec}
                />
              </CardContent>
            </Card>
          )}
        </div>

        {/* Sidebar */}
        <div className="space-y-6">
          {/* Linked PRs */}
          <Card>
            <CardHeader>
              <CardTitle className="text-sm">Linked Pull Requests</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {specPRs.length === 0 && codePRs.length === 0 ? (
                <p className="text-xs text-muted-foreground">
                  No linked PRs yet.
                </p>
              ) : (
                <>
                  {specPRs.map((pr) => (
                    <Link key={pr.number} href={`/prs/${pr.number}`}>
                      <div className="flex items-start gap-2 p-2 rounded-md hover:bg-muted transition-colors">
                        <GitPullRequest className="h-4 w-4 mt-0.5 text-purple-600 shrink-0" />
                        <div className="min-w-0">
                          <p className="text-xs font-medium truncate">
                            {pr.title}
                          </p>
                          <div className="flex items-center gap-1.5 mt-1">
                            <Badge
                              variant="secondary"
                              className="text-[10px] px-1.5"
                            >
                              Spec
                            </Badge>
                            {hasLabel(pr, "plan-approved") && (
                              <Badge className="text-[10px] px-1.5 bg-green-600">
                                Approved
                              </Badge>
                            )}
                          </div>
                        </div>
                      </div>
                    </Link>
                  ))}
                  {codePRs.map((pr) => (
                    <Link key={pr.number} href={`/prs/${pr.number}`}>
                      <div className="flex items-start gap-2 p-2 rounded-md hover:bg-muted transition-colors">
                        <GitPullRequest className="h-4 w-4 mt-0.5 text-green-600 shrink-0" />
                        <div className="min-w-0">
                          <p className="text-xs font-medium truncate">
                            {pr.title}
                          </p>
                          <Badge
                            variant="secondary"
                            className="text-[10px] px-1.5 mt-1"
                          >
                            Implementation
                          </Badge>
                        </div>
                      </div>
                    </Link>
                  ))}
                </>
              )}
            </CardContent>
          </Card>

          {/* Quick links */}
          <Card>
            <CardHeader>
              <CardTitle className="text-sm">Quick Links</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              <a
                href={issue.html_url}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-2 text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                <CircleDot className="h-3.5 w-3.5" />
                Issue on GitHub
              </a>
              {hasSpecs && (
                <Link
                  href={`/specs/${issueNumber}`}
                  className="flex items-center gap-2 text-xs text-muted-foreground hover:text-foreground transition-colors"
                >
                  <FileText className="h-3.5 w-3.5" />
                  Full Spec Viewer
                </Link>
              )}
              <a
                href={`${repoUrl}/tree/main/specs/issue-${issueNumber}`}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-2 text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                <FileText className="h-3.5 w-3.5" />
                Specs on GitHub
              </a>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
