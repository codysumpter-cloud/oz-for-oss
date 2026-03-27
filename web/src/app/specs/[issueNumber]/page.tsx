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
import { buttonVariants } from "@/components/ui/button-variants";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";
import {
  ArrowLeft,
  ExternalLink,
  CircleDot,
  GitPullRequest,
  FileText,
} from "lucide-react";

export default async function SpecReviewerPage({
  params,
}: {
  params: Promise<{ issueNumber: string }>;
}) {
  const { issueNumber: issueNumberStr } = await params;
  const issueNumber = parseInt(issueNumberStr, 10);
  if (isNaN(issueNumber)) notFound();

  let issue;
  try {
    issue = await getIssue(issueNumber);
  } catch {
    notFound();
  }

  const [specFiles, allPRs] = await Promise.all([
    getSpecFiles(issueNumber).catch(() => ({ productSpec: null, techSpec: null })),
    getOpenPullRequests().catch(() => []),
  ]);

  if (!specFiles.productSpec && !specFiles.techSpec) {
    // Try fetching from an open spec PR branch
    const specPR = allPRs.find(
      (pr) => isSpecPR(pr) && extractIssueNumber(pr) === issueNumber
    );
    if (specPR) {
      const branchSpecs = await getSpecFiles(issueNumber, specPR.head.ref).catch(
        () => ({ productSpec: null, techSpec: null })
      );
      specFiles.productSpec = branchSpecs.productSpec;
      specFiles.techSpec = branchSpecs.techSpec;
    }
  }

  const hasSpecs = specFiles.productSpec || specFiles.techSpec;
  const specPR = allPRs.find(
    (pr) => isSpecPR(pr) && extractIssueNumber(pr) === issueNumber
  );
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
        <Link
          href={`/issues/${issueNumber}`}
          className="text-sm text-muted-foreground hover:text-foreground transition-colors"
        >
          Issue #{issueNumber}
        </Link>
        <span className="text-muted-foreground">/</span>
        <span className="text-sm font-medium">Specs</span>
      </div>

      {/* Header */}
      <div className="flex flex-col gap-4 mb-8">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 text-sm text-muted-foreground mb-1">
              <FileText className="h-4 w-4" />
              Specs for Issue #{issueNumber}
            </div>
            <h1 className="text-2xl font-bold tracking-tight">
              {issue.title}
            </h1>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <Link
              href={`/issues/${issueNumber}`}
              className={cn(buttonVariants({ variant: "outline", size: "sm" }), "gap-2")}
            >
              <CircleDot className="h-4 w-4" />
              Issue
            </Link>
            {specPR && (
              <Link
                href={`/prs/${specPR.number}`}
                className={cn(buttonVariants({ variant: "outline", size: "sm" }), "gap-2")}
              >
                <GitPullRequest className="h-4 w-4" />
                Spec PR #{specPR.number}
              </Link>
            )}
            <a
              href={`${repoUrl}/tree/main/specs/issue-${issueNumber}`}
              target="_blank"
              rel="noopener noreferrer"
              className={cn(buttonVariants({ variant: "outline", size: "sm" }), "gap-2")}
            >
              <ExternalLink className="h-4 w-4" />
              GitHub
            </a>
          </div>
        </div>

        {/* Status badges */}
        <div className="flex items-center gap-2">
          {specPR && hasLabel(specPR, "plan-approved") && (
            <Badge className="bg-green-600 hover:bg-green-700 gap-1">
              Spec Approved
            </Badge>
          )}
          {specPR && !hasLabel(specPR, "plan-approved") && (
            <Badge variant="secondary" className="gap-1">
              Pending Review
            </Badge>
          )}
          {specFiles.productSpec && (
            <Badge variant="outline" className="gap-1">
              <FileText className="h-3 w-3" />
              Product Spec
            </Badge>
          )}
          {specFiles.techSpec && (
            <Badge variant="outline" className="gap-1">
              <FileText className="h-3 w-3" />
              Tech Spec
            </Badge>
          )}
        </div>
      </div>

      <Separator className="mb-8" />

      {/* Spec content */}
      {hasSpecs ? (
        <SpecTabs
          productSpec={specFiles.productSpec}
          techSpec={specFiles.techSpec}
        />
      ) : (
        <div className="text-center py-16">
          <FileText className="h-12 w-12 text-muted-foreground/50 mx-auto mb-4" />
          <h2 className="text-lg font-semibold mb-2">No Specs Yet</h2>
          <p className="text-sm text-muted-foreground max-w-md mx-auto">
            No product or tech spec has been created for this issue yet.
            Specs are generated when an issue is labeled{" "}
            <code className="bg-muted px-1 rounded text-xs">ready-to-spec</code>{" "}
            and assigned to oz-agent.
          </p>
          <a
            href={issue.html_url}
            target="_blank"
            rel="noopener noreferrer"
            className={cn(buttonVariants({ variant: "outline" }), "mt-4 gap-2")}
          >
            <ExternalLink className="h-4 w-4" />
            View Issue on GitHub
          </a>
        </div>
      )}
    </div>
  );
}
