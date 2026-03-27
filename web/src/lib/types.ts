export interface GitHubLabel {
  id: number;
  name: string;
  color: string;
  description?: string;
}

export interface GitHubUser {
  login: string;
  avatar_url: string;
  html_url: string;
}

export interface GitHubIssue {
  number: number;
  title: string;
  body: string | null;
  state: string;
  html_url: string;
  created_at: string;
  updated_at: string;
  labels: GitHubLabel[];
  assignees: GitHubUser[];
  user: GitHubUser;
}

export interface GitHubPullRequest {
  number: number;
  title: string;
  body: string | null;
  state: string;
  draft: boolean;
  html_url: string;
  created_at: string;
  updated_at: string;
  merged_at: string | null;
  labels: GitHubLabel[];
  user: GitHubUser;
  head: {
    ref: string;
    sha: string;
  };
  base: {
    ref: string;
  };
  requested_reviewers: GitHubUser[];
}

export interface GitHubFile {
  filename: string;
  status: string;
  additions: number;
  deletions: number;
  changes: number;
  patch?: string;
}

export interface SpecFiles {
  productSpec: string | null;
  techSpec: string | null;
}

export type PipelineStage =
  | "ready-to-spec"
  | "spec-in-review"
  | "ready-to-implement"
  | "code-in-review";

export interface PipelineItem {
  type: "issue" | "pr";
  stage: PipelineStage;
  issue?: GitHubIssue;
  pr?: GitHubPullRequest;
  issueNumber?: number;
  hasApprovedSpec?: boolean;
  specFiles?: SpecFiles;
}
