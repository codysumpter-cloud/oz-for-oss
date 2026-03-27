import Link from "next/link";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { LabelBadge } from "./label-badge";
import type { PipelineItem, PipelineStage, GitHubIssue, GitHubPullRequest } from "@/lib/types";
import {
  FileText,
  GitPullRequest,
  CircleDot,
  ExternalLink,
  CheckCircle2,
  Code2,
  Lightbulb,
  Hammer,
} from "lucide-react";

const COLUMN_CONFIG: {
  key: PipelineStage;
  title: string;
  description: string;
  icon: React.ReactNode;
  accent: string;
}[] = [
  {
    key: "ready-to-spec",
    title: "Ready to Spec",
    description: "Issues awaiting spec creation",
    icon: <Lightbulb className="h-4 w-4" />,
    accent: "border-t-amber-500",
  },
  {
    key: "spec-in-review",
    title: "Spec in Review",
    description: "Spec PRs open for review",
    icon: <FileText className="h-4 w-4" />,
    accent: "border-t-blue-500",
  },
  {
    key: "ready-to-implement",
    title: "Ready to Implement",
    description: "Approved specs awaiting code",
    icon: <Hammer className="h-4 w-4" />,
    accent: "border-t-purple-500",
  },
  {
    key: "code-in-review",
    title: "Code in Review",
    description: "Implementation PRs open for review",
    icon: <Code2 className="h-4 w-4" />,
    accent: "border-t-green-500",
  },
];

function IssueCard({ issue }: { issue: GitHubIssue }) {
  return (
    <Link href={`/issues/${issue.number}`}>
      <Card className="group hover:shadow-md transition-all hover:border-primary/30 cursor-pointer">
        <CardContent className="p-4">
          <div className="flex items-start gap-3">
            <CircleDot className="h-4 w-4 mt-0.5 text-green-600 shrink-0" />
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium leading-tight group-hover:text-primary transition-colors line-clamp-2">
                {issue.title}
              </p>
              <p className="text-xs text-muted-foreground mt-1">
                #{issue.number}
              </p>
              <div className="flex flex-wrap gap-1 mt-2">
                {issue.labels
                  .filter(
                    (l) =>
                      l.name !== "ready-to-spec" &&
                      l.name !== "ready-to-implement"
                  )
                  .slice(0, 3)
                  .map((label) => (
                    <LabelBadge key={label.id} label={label} />
                  ))}
              </div>
              {issue.assignees.length > 0 && (
                <div className="flex items-center gap-1 mt-2">
                  {issue.assignees.slice(0, 3).map((user) => (
                    <Avatar key={user.login} className="h-5 w-5">
                      <AvatarImage src={user.avatar_url} alt={user.login} />
                      <AvatarFallback className="text-[10px]">
                        {user.login.slice(0, 2).toUpperCase()}
                      </AvatarFallback>
                    </Avatar>
                  ))}
                </div>
              )}
            </div>
            <a
              href={issue.html_url}
              target="_blank"
              rel="noopener noreferrer"
              className="opacity-0 group-hover:opacity-100 transition-opacity"
              onClick={(e) => e.stopPropagation()}
            >
              <ExternalLink className="h-3.5 w-3.5 text-muted-foreground hover:text-foreground" />
            </a>
          </div>
        </CardContent>
      </Card>
    </Link>
  );
}

function PrCard({
  pr,
  issueNumber,
  hasApprovedSpec,
}: {
  pr: GitHubPullRequest;
  issueNumber?: number;
  hasApprovedSpec?: boolean;
}) {
  return (
    <Link href={`/prs/${pr.number}`}>
      <Card className="group hover:shadow-md transition-all hover:border-primary/30 cursor-pointer">
        <CardContent className="p-4">
          <div className="flex items-start gap-3">
            <GitPullRequest className="h-4 w-4 mt-0.5 text-purple-600 shrink-0" />
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium leading-tight group-hover:text-primary transition-colors line-clamp-2">
                {pr.title}
              </p>
              <div className="flex items-center gap-2 mt-1">
                <p className="text-xs text-muted-foreground">#{pr.number}</p>
                {issueNumber && (
                  <Link
                    href={`/issues/${issueNumber}`}
                    className="text-xs text-muted-foreground hover:text-primary transition-colors"
                    onClick={(e) => e.stopPropagation()}
                  >
                    ← Issue #{issueNumber}
                  </Link>
                )}
              </div>
              <div className="flex flex-wrap items-center gap-1.5 mt-2">
                {hasApprovedSpec && (
                  <Badge variant="default" className="gap-1 text-xs bg-green-600 hover:bg-green-700">
                    <CheckCircle2 className="h-3 w-3" />
                    Approved
                  </Badge>
                )}
                {pr.draft && (
                  <Badge variant="secondary" className="text-xs">
                    Draft
                  </Badge>
                )}
                {pr.labels
                  .filter(
                    (l) => l.name !== "plan-approved"
                  )
                  .slice(0, 2)
                  .map((label) => (
                    <LabelBadge key={label.id} label={label} />
                  ))}
              </div>
              <div className="flex items-center gap-1 mt-2">
                <Avatar className="h-5 w-5">
                  <AvatarImage src={pr.user.avatar_url} alt={pr.user.login} />
                  <AvatarFallback className="text-[10px]">
                    {pr.user.login.slice(0, 2).toUpperCase()}
                  </AvatarFallback>
                </Avatar>
                <span className="text-xs text-muted-foreground">{pr.user.login}</span>
              </div>
            </div>
            <a
              href={pr.html_url}
              target="_blank"
              rel="noopener noreferrer"
              className="opacity-0 group-hover:opacity-100 transition-opacity"
              onClick={(e) => e.stopPropagation()}
            >
              <ExternalLink className="h-3.5 w-3.5 text-muted-foreground hover:text-foreground" />
            </a>
          </div>
        </CardContent>
      </Card>
    </Link>
  );
}

interface PipelineBoardProps {
  items: PipelineItem[];
}

export function PipelineBoard({ items }: PipelineBoardProps) {
  const byStage = COLUMN_CONFIG.map((col) => ({
    ...col,
    items: items.filter((item) => item.stage === col.key),
  }));

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-6">
      {byStage.map((column) => (
        <div key={column.key} className="flex flex-col">
          <Card className={`border-t-4 ${column.accent}`}>
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  {column.icon}
                  <CardTitle className="text-sm font-semibold">
                    {column.title}
                  </CardTitle>
                </div>
                <Badge variant="secondary" className="text-xs tabular-nums">
                  {column.items.length}
                </Badge>
              </div>
              <CardDescription className="text-xs">
                {column.description}
              </CardDescription>
            </CardHeader>
            <CardContent className="pt-0">
              <ScrollArea className="h-[calc(100vh-280px)]">
                <div className="space-y-3 pr-4">
                  {column.items.length === 0 ? (
                    <p className="text-xs text-muted-foreground text-center py-8">
                      No items
                    </p>
                  ) : (
                    column.items.map((item) =>
                      item.type === "issue" && item.issue ? (
                        <IssueCard key={`issue-${item.issue.number}`} issue={item.issue} />
                      ) : item.type === "pr" && item.pr ? (
                        <PrCard
                          key={`pr-${item.pr.number}`}
                          pr={item.pr}
                          issueNumber={item.issueNumber}
                          hasApprovedSpec={item.hasApprovedSpec}
                        />
                      ) : null
                    )
                  )}
                </div>
              </ScrollArea>
            </CardContent>
          </Card>
        </div>
      ))}
    </div>
  );
}
