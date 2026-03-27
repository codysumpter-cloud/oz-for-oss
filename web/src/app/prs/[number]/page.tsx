import Link from "next/link";
import { notFound } from "next/navigation";
import {
  getPullRequest,
  getPullRequestFiles,
  getSpecFiles,
  extractIssueNumber,
  isSpecPR,
  hasLabel,
  getRepoUrl,
} from "@/lib/github";
import { SpecTabs } from "@/components/spec-tabs";
import { MarkdownViewer } from "@/components/markdown-viewer";
import { LabelBadge } from "@/components/label-badge";
import { buttonVariants } from "@/components/ui/button-variants";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { cn } from "@/lib/utils";
import {
  ArrowLeft,
  ExternalLink,
  GitPullRequest,
  CircleDot,
  FileText,
  ChevronDown,
  Calendar,
  GitBranch,
  FileDiff,
} from "lucide-react";

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export default async function PrDetailPage({
  params,
}: {
  params: Promise<{ number: string }>;
}) {
  const { number: numberStr } = await params;
  const prNumber = parseInt(numberStr, 10);
  if (isNaN(prNumber)) notFound();

  let pr;
  try {
    pr = await getPullRequest(prNumber);
  } catch {
    notFound();
  }

  const [files, specFilesResult] = await Promise.all([
    getPullRequestFiles(prNumber).catch(() => []),
    (async () => {
      const issueNum = extractIssueNumber(pr);
      if (!issueNum) return { productSpec: null, techSpec: null };
      // Try from PR branch first (for spec PRs), then main
      const branchSpecs = await getSpecFiles(issueNum, pr.head.ref).catch(
        () => ({ productSpec: null, techSpec: null })
      );
      if (branchSpecs.productSpec || branchSpecs.techSpec) return branchSpecs;
      return getSpecFiles(issueNum).catch(() => ({
        productSpec: null,
        techSpec: null,
      }));
    })(),
  ]);

  const issueNumber = extractIssueNumber(pr);
  const isSpec = isSpecPR(pr);
  const isApproved = hasLabel(pr, "plan-approved");
  const hasSpecs =
    specFilesResult.productSpec || specFilesResult.techSpec;
  const repoUrl = getRepoUrl();

  const specFiles = files.filter((f) => f.filename.startsWith("specs/"));
  const codeFiles = files.filter((f) => !f.filename.startsWith("specs/"));

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
        {issueNumber && (
          <>
            <Link
              href={`/issues/${issueNumber}`}
              className="text-sm text-muted-foreground hover:text-foreground transition-colors"
            >
              Issue #{issueNumber}
            </Link>
            <span className="text-muted-foreground">/</span>
          </>
        )}
        <span className="text-sm font-medium">PR #{prNumber}</span>
      </div>

      {/* Header */}
      <div className="flex flex-col gap-4 mb-8">
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-start gap-3 min-w-0">
            <GitPullRequest
              className={`h-6 w-6 mt-1 shrink-0 ${
                pr.merged_at
                  ? "text-purple-600"
                  : pr.state === "closed"
                  ? "text-red-600"
                  : "text-green-600"
              }`}
            />
            <div>
              <h1 className="text-2xl font-bold tracking-tight leading-tight">
                {pr.title}
              </h1>
              <div className="flex items-center gap-3 mt-2 text-sm text-muted-foreground">
                <span>#{pr.number}</span>
                <span className="flex items-center gap-1">
                  <Calendar className="h-3.5 w-3.5" />
                  {formatDate(pr.created_at)}
                </span>
                <span className="flex items-center gap-1">
                  <Avatar className="h-4 w-4">
                    <AvatarImage
                      src={pr.user.avatar_url}
                      alt={pr.user.login}
                    />
                    <AvatarFallback className="text-[8px]">
                      {pr.user.login.slice(0, 2).toUpperCase()}
                    </AvatarFallback>
                  </Avatar>
                  {pr.user.login}
                </span>
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {issueNumber && (
              <Link
                href={`/issues/${issueNumber}`}
                className={cn(buttonVariants({ variant: "outline", size: "sm" }), "gap-2")}
              >
                <CircleDot className="h-4 w-4" />
                Issue #{issueNumber}
              </Link>
            )}
            <a
              href={pr.html_url}
              target="_blank"
              rel="noopener noreferrer"
              className={cn(buttonVariants({ variant: "outline", size: "sm" }), "gap-2")}
            >
              <ExternalLink className="h-4 w-4" />
              GitHub
            </a>
          </div>
        </div>

        {/* Badges */}
        <div className="flex flex-wrap items-center gap-2">
          <Badge
            variant={
              pr.merged_at ? "default" : pr.state === "open" ? "secondary" : "destructive"
            }
          >
            {pr.merged_at ? "Merged" : pr.state === "open" ? "Open" : "Closed"}
          </Badge>
          {isSpec && (
            <Badge variant="outline" className="gap-1">
              <FileText className="h-3 w-3" />
              Spec PR
            </Badge>
          )}
          {!isSpec && issueNumber && (
            <Badge variant="outline" className="gap-1">
              <FileDiff className="h-3 w-3" />
              Implementation PR
            </Badge>
          )}
          {isApproved && (
            <Badge className="bg-green-600 hover:bg-green-700 gap-1">
              Spec Approved
            </Badge>
          )}
          {pr.draft && <Badge variant="secondary">Draft</Badge>}
          <div className="flex items-center gap-1 text-xs text-muted-foreground">
            <GitBranch className="h-3.5 w-3.5" />
            <code className="bg-muted px-1.5 py-0.5 rounded text-xs">
              {pr.head.ref}
            </code>
            →
            <code className="bg-muted px-1.5 py-0.5 rounded text-xs">
              {pr.base.ref}
            </code>
          </div>
        </div>

        {/* Labels */}
        <div className="flex flex-wrap gap-1.5">
          {pr.labels.map((label) => (
            <LabelBadge key={label.id} label={label} />
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Main content */}
        <div className="lg:col-span-2 space-y-8">
          {/* PR body */}
          {pr.body && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Description</CardTitle>
              </CardHeader>
              <CardContent>
                <MarkdownViewer content={pr.body} />
              </CardContent>
            </Card>
          )}

          {/* Spec content - shown inline for spec PRs, collapsible for code PRs */}
          {isSpec && hasSpecs && (
            <Card>
              <CardHeader>
                <div className="flex items-center justify-between">
                  <CardTitle className="text-base flex items-center gap-2">
                    <FileText className="h-4 w-4" />
                    Spec Files
                  </CardTitle>
                  {issueNumber && (
                    <Link
                      href={`/specs/${issueNumber}`}
                      className={cn(buttonVariants({ variant: "outline", size: "sm" }), "gap-2")}
                    >
                      Full Spec View
                      <ExternalLink className="h-3 w-3" />
                    </Link>
                  )}
                </div>
              </CardHeader>
              <CardContent>
                <SpecTabs
                  productSpec={specFilesResult.productSpec}
                  techSpec={specFilesResult.techSpec}
                />
              </CardContent>
            </Card>
          )}

          {!isSpec && hasSpecs && (
            <Collapsible>
              <Card>
                <CardHeader>
                  <CollapsibleTrigger className="flex items-center justify-between w-full group">
                    <CardTitle className="text-base flex items-center gap-2">
                      <FileText className="h-4 w-4" />
                      Approved Spec Context
                    </CardTitle>
                    <ChevronDown className="h-4 w-4 text-muted-foreground group-data-[state=open]:rotate-180 transition-transform" />
                  </CollapsibleTrigger>
                  <CardDescription>
                    The spec approved for this implementation
                  </CardDescription>
                </CardHeader>
                <CollapsibleContent>
                  <CardContent>
                    <SpecTabs
                      productSpec={specFilesResult.productSpec}
                      techSpec={specFilesResult.techSpec}
                    />
                  </CardContent>
                </CollapsibleContent>
              </Card>
            </Collapsible>
          )}
        </div>

        {/* Sidebar */}
        <div className="space-y-6">
          {/* Changed files */}
          <Card>
            <CardHeader>
              <CardTitle className="text-sm flex items-center justify-between">
                Changed Files
                <Badge variant="secondary" className="text-xs tabular-nums">
                  {files.length}
                </Badge>
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-1">
                {specFiles.length > 0 && (
                  <>
                    <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold mb-1">
                      Spec files
                    </p>
                    {specFiles.map((file) => (
                      <div
                        key={file.filename}
                        className="flex items-center justify-between py-1"
                      >
                        <span className="text-xs truncate text-muted-foreground">
                          {file.filename}
                        </span>
                        <div className="flex items-center gap-1 text-xs shrink-0 ml-2">
                          {file.additions > 0 && (
                            <span className="text-green-600">
                              +{file.additions}
                            </span>
                          )}
                          {file.deletions > 0 && (
                            <span className="text-red-600">
                              -{file.deletions}
                            </span>
                          )}
                        </div>
                      </div>
                    ))}
                  </>
                )}
                {codeFiles.length > 0 && specFiles.length > 0 && (
                  <Separator className="my-2" />
                )}
                {codeFiles.length > 0 && (
                  <>
                    {specFiles.length > 0 && (
                      <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold mb-1">
                        Code files
                      </p>
                    )}
                    {codeFiles.map((file) => (
                      <div
                        key={file.filename}
                        className="flex items-center justify-between py-1"
                      >
                        <span className="text-xs truncate text-muted-foreground">
                          {file.filename}
                        </span>
                        <div className="flex items-center gap-1 text-xs shrink-0 ml-2">
                          {file.additions > 0 && (
                            <span className="text-green-600">
                              +{file.additions}
                            </span>
                          )}
                          {file.deletions > 0 && (
                            <span className="text-red-600">
                              -{file.deletions}
                            </span>
                          )}
                        </div>
                      </div>
                    ))}
                  </>
                )}
              </div>
            </CardContent>
          </Card>

          {/* Quick links */}
          <Card>
            <CardHeader>
              <CardTitle className="text-sm">Quick Links</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              <a
                href={pr.html_url}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-2 text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                <GitPullRequest className="h-3.5 w-3.5" />
                PR on GitHub
              </a>
              <a
                href={`${pr.html_url}/files`}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-2 text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                <FileDiff className="h-3.5 w-3.5" />
                Files Changed
              </a>
              {issueNumber && (
                <>
                  <Link
                    href={`/issues/${issueNumber}`}
                    className="flex items-center gap-2 text-xs text-muted-foreground hover:text-foreground transition-colors"
                  >
                    <CircleDot className="h-3.5 w-3.5" />
                    Issue #{issueNumber}
                  </Link>
                  <Link
                    href={`/specs/${issueNumber}`}
                    className="flex items-center gap-2 text-xs text-muted-foreground hover:text-foreground transition-colors"
                  >
                    <FileText className="h-3.5 w-3.5" />
                    Spec Viewer
                  </Link>
                </>
              )}
            </CardContent>
          </Card>

          {/* Reviewers */}
          {pr.requested_reviewers.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-sm">Requested Reviewers</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-2">
                  {pr.requested_reviewers.map((user) => (
                    <div
                      key={user.login}
                      className="flex items-center gap-2"
                    >
                      <Avatar className="h-5 w-5">
                        <AvatarImage
                          src={user.avatar_url}
                          alt={user.login}
                        />
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
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
