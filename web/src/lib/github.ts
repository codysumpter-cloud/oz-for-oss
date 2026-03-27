import {
  GitHubIssue,
  GitHubPullRequest,
  GitHubFile,
  SpecFiles,
  PipelineItem,
} from "./types";

const GITHUB_API = "https://api.github.com";
const OWNER = process.env.GITHUB_OWNER || "warpdotdev";
const REPO = process.env.GITHUB_REPO || "oz-for-oss";

function headers(): HeadersInit {
  const h: HeadersInit = {
    Accept: "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
  };
  const token = process.env.GITHUB_TOKEN;
  if (token) {
    h.Authorization = `Bearer ${token}`;
  }
  return h;
}

async function ghFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const url = `${GITHUB_API}${path}`;
  const res = await fetch(url, {
    ...init,
    headers: { ...headers(), ...(init?.headers || {}) },
    next: { revalidate: 60 },
  });
  if (!res.ok) {
    throw new Error(`GitHub API ${res.status}: ${url}`);
  }
  return res.json();
}

async function ghFetchText(path: string): Promise<string | null> {
  const url = `${GITHUB_API}${path}`;
  const res = await fetch(url, {
    headers: {
      ...headers(),
      Accept: "application/vnd.github.raw+json",
    },
    next: { revalidate: 60 },
  });
  if (!res.ok) return null;
  return res.text();
}

// ---------------------------------------------------------------------------
// Issues
// ---------------------------------------------------------------------------

export async function getIssuesByLabel(label: string): Promise<GitHubIssue[]> {
  return ghFetch<GitHubIssue[]>(
    `/repos/${OWNER}/${REPO}/issues?labels=${encodeURIComponent(label)}&state=open&per_page=100&sort=updated&direction=desc`
  );
}

export async function getIssue(number: number): Promise<GitHubIssue> {
  return ghFetch<GitHubIssue>(`/repos/${OWNER}/${REPO}/issues/${number}`);
}

// ---------------------------------------------------------------------------
// Pull Requests
// ---------------------------------------------------------------------------

export async function getPullRequest(
  number: number
): Promise<GitHubPullRequest> {
  return ghFetch<GitHubPullRequest>(
    `/repos/${OWNER}/${REPO}/pulls/${number}`
  );
}

export async function getPullRequestFiles(
  number: number
): Promise<GitHubFile[]> {
  return ghFetch<GitHubFile[]>(
    `/repos/${OWNER}/${REPO}/pulls/${number}/files?per_page=100`
  );
}

export async function getOpenPullRequests(): Promise<GitHubPullRequest[]> {
  return ghFetch<GitHubPullRequest[]>(
    `/repos/${OWNER}/${REPO}/pulls?state=open&per_page=100&sort=updated&direction=desc`
  );
}

// ---------------------------------------------------------------------------
// Spec files
// ---------------------------------------------------------------------------

export async function getSpecFiles(
  issueNumber: number,
  ref?: string
): Promise<SpecFiles> {
  const refParam = ref ? `?ref=${encodeURIComponent(ref)}` : "";
  const [productSpec, techSpec] = await Promise.all([
    ghFetchText(
      `/repos/${OWNER}/${REPO}/contents/specs/issue-${issueNumber}/product.md${refParam}`
    ),
    ghFetchText(
      `/repos/${OWNER}/${REPO}/contents/specs/issue-${issueNumber}/tech.md${refParam}`
    ),
  ]);
  return { productSpec, techSpec };
}

// ---------------------------------------------------------------------------
// Linked issue resolution
// ---------------------------------------------------------------------------

const ISSUE_REF_PATTERN =
  /(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?|refs?|implements?|issue)\s*:?\s+#(\d+)/gi;

export function extractIssueNumber(pr: GitHubPullRequest): number | null {
  // From branch name: oz-agent/spec-issue-83 or oz-agent/implement-issue-83
  const branchMatch = pr.head.ref.match(
    /(?:spec|implement)-issue-(\d+)/
  );
  if (branchMatch) return parseInt(branchMatch[1], 10);

  // From PR body
  if (pr.body) {
    const matches = [...pr.body.matchAll(ISSUE_REF_PATTERN)];
    if (matches.length > 0) return parseInt(matches[0][1], 10);

    // Direct #N references
    const hashMatch = pr.body.match(/#(\d+)/);
    if (hashMatch) return parseInt(hashMatch[1], 10);
  }

  return null;
}

export function isSpecPR(pr: GitHubPullRequest): boolean {
  return pr.head.ref.startsWith("oz-agent/spec-issue-");
}

export function hasLabel(
  item: { labels: { name: string }[] },
  labelName: string
): boolean {
  return item.labels.some((l) => l.name === labelName);
}

// ---------------------------------------------------------------------------
// Pipeline aggregation
// ---------------------------------------------------------------------------

export async function getPipelineData(): Promise<PipelineItem[]> {
  const [readyToSpec, readyToImplement, openPRs] = await Promise.all([
    getIssuesByLabel("ready-to-spec"),
    getIssuesByLabel("ready-to-implement"),
    getOpenPullRequests(),
  ]);

  const items: PipelineItem[] = [];

  // Ready to Spec issues (exclude ones that already have a spec PR open)
  const specPRIssueNumbers = new Set(
    openPRs.filter((pr) => isSpecPR(pr)).map((pr) => extractIssueNumber(pr))
  );

  for (const issue of readyToSpec) {
    if (!specPRIssueNumbers.has(issue.number)) {
      items.push({ type: "issue", stage: "ready-to-spec", issue });
    }
  }

  // Spec PRs in review
  for (const pr of openPRs) {
    if (isSpecPR(pr)) {
      const issueNumber = extractIssueNumber(pr);
      items.push({
        type: "pr",
        stage: "spec-in-review",
        pr,
        issueNumber: issueNumber ?? undefined,
        hasApprovedSpec: hasLabel(pr, "plan-approved"),
      });
    }
  }

  // Ready to Implement issues
  const codePRIssueNumbers = new Set(
    openPRs
      .filter((pr) => !isSpecPR(pr))
      .map((pr) => extractIssueNumber(pr))
      .filter(Boolean)
  );

  for (const issue of readyToImplement) {
    if (!codePRIssueNumbers.has(issue.number)) {
      items.push({ type: "issue", stage: "ready-to-implement", issue });
    }
  }

  // Code PRs in review (non-spec PRs that reference issues)
  for (const pr of openPRs) {
    if (!isSpecPR(pr)) {
      const issueNumber = extractIssueNumber(pr);
      if (issueNumber) {
        items.push({
          type: "pr",
          stage: "code-in-review",
          pr,
          issueNumber,
        });
      }
    }
  }

  return items;
}

export function getRepoUrl(): string {
  return `https://github.com/${OWNER}/${REPO}`;
}

export function getOwnerRepo(): { owner: string; repo: string } {
  return { owner: OWNER, repo: REPO };
}
