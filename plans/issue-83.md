# Issue #83: Change up workflow to support product and tech specs

## Product Spec

### Goal
Reorient the repository's planning workflow from a single "plan" artifact to a two-part spec system with separate product and technical specifications. This gives clearer separation between _what_ we want to build (product spec) and _how_ we will build it (tech spec), while also introducing a new `ready-to-spec` label to trigger the spec-creation workflow.

### Intended behavior

#### Directory structure
- The current top-level `plans/` directory is renamed to `specs/`.
- Each issue gets its own subdirectory: `specs/issue-{issue-number}/`.
- Within each subdirectory, two files are produced:
  - `product.md` — describes the intended behavior, user-facing goals, and acceptance criteria.
  - `tech.md` — describes the implementation approach, file changes, risks, and technical details (equivalent to today's plan).

#### Label-driven workflow
The current `ready-to-plan` label is replaced by `ready-to-spec` everywhere. The lifecycle becomes:

1. **`ready-to-spec`** — When oz-agent is assigned and the issue has this label, the agent generates both `product.md` (from the issue thread) and `tech.md` (from the product spec and issue thread) in a single agent run. Both are committed to a single PR on branch `oz-agent/spec-issue-{number}`.
2. **`plan-approved`** — Remains targeted at the tech spec. When a reviewer is satisfied with the technical approach in the PR, they add this label. The existing `plan-approved` label semantics stay the same — it signals that the tech spec is accepted.
3. **`ready-to-implement`** — When the issue is marked `ready-to-implement`, the implementation workflow produces code changes on the same PR branch (or a linked branch), using the approved tech spec as context. This behavior is unchanged from today.

#### PR structure
- The spec PR is titled `spec: {issue title}` (replacing `plan: {issue title}`).
- The PR contains both `specs/issue-{issue-number}/product.md` and `specs/issue-{issue-number}/tech.md`.
- Reviewers can iterate on product and tech spec content in the same PR.

#### Agent skills
Two new skills replace the current `create-plan` skill:
- **`create-product-spec`** — Generates a product spec from the issue thread. Covers intended behavior, user goals, acceptance criteria, and scope.
- **`create-tech-spec`** — Generates a tech spec from the product spec and issue thread. Covers implementation details, file changes, risks, and open questions. This is the successor to the current `create-plan` skill.

The existing `create-plan` skill is removed.

#### Backward compatibility
Per the triggering comment, backward compatibility with the current `plans/` directory and `ready-to-plan` label is not required. This is a clean migration.

---

## Tech Spec

### Current state
- `plans/` directory holds plan files named `issue-{number}.md`.
- The `create-plan` skill at `.agents/skills/create-plan/SKILL.md` instructs the agent to produce a single plan file.
- `create-plan-from-issue.yml` workflow triggers on `ready-to-plan` label and runs `src/create_plan_from_issue.py`.
- `create_plan_from_issue.py` builds a prompt referencing `plans/issue-{number}.md`, pushes to `oz-agent/plan-issue-{number}`, and opens a PR titled `plan: {issue title}`.
- `create_implementation_from_issue.py` resolves plan context via `resolve_plan_context_for_issue()` in `helpers.py`, which looks for `plans/issue-{number}.md` locally and for PRs on `oz-agent/plan-issue-{number}` branches.
- `enforce_pr_issue_state.py` checks for `ready-to-plan` and `ready-to-implement` labels, and classifies changes as "plan" when only `.md` files are touched.
- `comment_on_unready_assigned_issue.py` checks for `ready-to-plan` and `ready-to-implement` labels.
- `helpers.py` has functions `build_plan_preview_section()`, `read_local_plan_file()`, `resolve_plan_context_for_issue()`, `find_matching_plan_prs()`, and `resolve_plan_context_for_pr()` — all referencing `plans/` paths and `plan-issue-{number}` branch naming.
- `check-impl-against-plan` skill references `implementation_plan_context.md`.
- `implement-issue` skill references `implementation_plan_context.md`.
- `review-pr` skill references `implementation_plan_context.md`.
- `CONTRIBUTING.md` and `README.md` reference `ready-to-plan`, `plans/`, and the plan workflow.
- `.github/STAKEHOLDERS` has a `/plans/` entry.
- `resolve_issue_number_for_pr()` in `helpers.py` uses regex matching `plans/issue-(\\d+)\\.md` and branch patterns with `plan-issue-`.

### Proposed changes

#### 1. Rename `plans/` to `specs/` and restructure

- Delete `plans/.gitkeep` and any existing plan files (`plans/issue-56.md`, `plans/issue-65.md`).
- Create `specs/.gitkeep`.
- Migrate existing plans to `specs/issue-56/tech.md` and `specs/issue-65/tech.md` (treat them as tech specs since that's what they are).

#### 2. New skill: `create-product-spec`

Create `.agents/skills/create-product-spec/SKILL.md`:
- Inputs: issue number, title, description, labels, assignees, issue comments.
- Instructs the agent to produce `specs/issue-{issue-number}/product.md`.
- Content guidance: describe intended behavior, user goals, acceptance criteria, scope boundaries, and open product questions.
- Do not include implementation details — those belong in the tech spec.
- Follow the same cloud-workflow conventions as the current `create-plan` skill (default no-commit; cloud mode allows commit/push when instructed).

#### 3. New skill: `create-tech-spec`

Create `.agents/skills/create-tech-spec/SKILL.md`:
- Inputs: issue number, title, description, labels, assignees, issue comments, plus the product spec content when available.
- Instructs the agent to produce `specs/issue-{issue-number}/tech.md`.
- Content guidance: problem/goal, current-state observations, proposed changes with file-level detail, risks, dependencies, open technical questions.
- This is the direct successor to the `create-plan` skill content, adapted for the new path.
- Follow the same cloud-workflow conventions.

#### 4. Remove `create-plan` skill

Delete `.agents/skills/create-plan/SKILL.md`.

#### 5. Rename workflow: `create-plan-from-issue.yml` → `create-spec-from-issue.yml`

Create `.github/workflows/create-spec-from-issue.yml` and delete `create-plan-from-issue.yml`:
- Change all references from `ready-to-plan` to `ready-to-spec`.
- Update concurrency group: `create-spec-issue-${{ github.event.issue.number }}`.
- Update job name and step descriptions.
- Reference a new Python entrypoint `src/create_spec_from_issue.py`.
- Pass a new env var `WARP_AGENT_SPEC_ENVIRONMENT_ID` (falling back to `WARP_AGENT_ENVIRONMENT_ID`).

#### 6. New Python entrypoint: `src/create_spec_from_issue.py`

Replace `src/create_plan_from_issue.py` with `src/create_spec_from_issue.py`:
- Branch naming: `oz-agent/spec-issue-{number}`.
- The agent prompt instructs the agent to produce both `specs/issue-{issue-number}/product.md` and `specs/issue-{issue-number}/tech.md` in a single run. Both skill files are referenced in the prompt text; the `skill_name` parameter is omitted from `run_agent()` and the agent reads both skills via prompting.
- PR title: `spec: {issue title}`.
- Update progress messages from "implementation plan" to "spec".
- Update the preview section to point to both spec files.

#### 7. Update `src/create_implementation_from_issue.py`

- Update `resolve_plan_context_for_issue()` calls — the function itself will be renamed (see below), but the call sites need to use the new name.
- Pass both the product spec and the tech spec as context into the implementation agent prompt. The implementation workflow should read both `specs/issue-{number}/product.md` and `specs/issue-{number}/tech.md` and include their contents in `spec_context.md`.
- Update progress messages from "plan" to "spec" where visible to users.

#### 8. Update `src/oz_workflows/helpers.py`

Rename and update the following functions:

- `build_plan_preview_section()` → `build_spec_preview_section()`: generate preview links for both `specs/issue-{number}/product.md` and `specs/issue-{number}/tech.md`.
- `read_local_plan_file()` → `read_local_spec_files()`: read from `specs/issue-{number}/product.md` and `specs/issue-{number}/tech.md`.
- `find_matching_plan_prs()` → `find_matching_spec_prs()`: look for branches named `oz-agent/spec-issue-{number}` instead of `oz-agent/plan-issue-{number}`. Update the file-matching logic to look for files under `specs/` instead of `plans/`.
- `resolve_plan_context_for_issue()` → `resolve_spec_context_for_issue()`: update all internal references to use the renamed functions and new paths.
- `resolve_plan_context_for_pr()` → `resolve_spec_context_for_pr()`: same updates.
- `resolve_issue_number_for_pr()`: update the regex for branch name matching from `(?:plan|implement)-issue-` to `(?:spec|implement)-issue-`, and the file path regex from `^plans/issue-(\\d+)\\.md$` to `^specs/issue-(\\d+)/(?:product|tech)\\.md$`.

#### 9. Update `src/enforce_pr_issue_state.py`

- Replace `ready-to-plan` with `ready-to-spec` in the `required_label` logic.
- Update the `change_kind` from `"plan"` to `"spec"` for non-code changes.
- Update user-facing messages accordingly.

#### 10. Update `src/comment_on_unready_assigned_issue.py`

- Replace `ready-to-plan` with `ready-to-spec` in the progress message.

#### 11. Update `comment-on-unready-assigned-issue.yml` workflow

- Update the `if` condition to check for `ready-to-spec` instead of `ready-to-plan`.

#### 12. Update `check-impl-against-plan` skill

Rename to `.agents/skills/check-impl-against-spec/SKILL.md`:
- Update all references from "plan" to "spec" (specifically tech spec).
- Rename `implementation_plan_context.md` to `spec_context.md` for clarity, even though it introduces churn in the `implement-issue` and `review-pr` skills.
- The skill should verify the implementation against both the product spec (for overall structure and correctness) and the tech spec (for implementation details).

#### 13. Update `implement-issue` skill

- Update references from "plan" to "spec" in the prose.
- Rename `implementation_plan_context.md` references to `spec_context.md`.
- The skill should note that `spec_context.md` contains both product and tech spec content.

#### 14. Update `review-pr` skill

- Update the reference to `check-impl-against-plan` → `check-impl-against-spec`.
- Update prose from "plan" to "spec".
- Rename `implementation_plan_context.md` references to `spec_context.md`.

#### 15. Update `CONTRIBUTING.md`

- Replace `ready-to-plan` with `ready-to-spec` throughout.
- Update the "When to open a plan PR" section to describe spec PRs instead.
- Update language from "plan" to "spec" where appropriate.

#### 16. Update `README.md`

- Replace `plans/` with `specs/` in the primary artifacts section.
- Update `ready-to-plan` → `ready-to-spec`.
- Update workflow surface description from "implementation-plan creation" to "product and tech spec creation".
- Update `.github/STAKEHOLDERS` to reference `/specs/` instead of `/plans/`.

#### 17. Update `.github/STAKEHOLDERS`

- Change `/plans/` to `/specs/`.

#### 18. Update tests

- Update any tests that reference `plans/`, `ready-to-plan`, or plan-related helper functions to use the new names and paths.
- Specifically, tests calling `read_local_plan_file()`, `find_matching_plan_prs()`, or `resolve_plan_context_for_issue()` need to use the renamed functions and updated path expectations.
New files:
- `.agents/skills/create-product-spec/SKILL.md`
- `.agents/skills/create-tech-spec/SKILL.md`
- `.github/workflows/create-spec-from-issue.yml`
- `src/create_spec_from_issue.py`
- `specs/.gitkeep`
- `specs/56/tech.md` (migrated from `plans/issue-56.md`)
- `specs/65/tech.md` (migrated from `plans/issue-65.md`)
- `specs/83/product.md` (migrated from product spec section of `plans/issue-83.md`)
- `specs/83/tech.md` (migrated from tech spec section of `plans/issue-83.md`)
- `specs/.gitkeep`
- `specs/issue-56/tech.md` (migrated from `plans/issue-56.md`)
- `specs/issue-65/tech.md` (migrated from `plans/issue-65.md`)

Deleted files:
- `.agents/skills/create-plan/SKILL.md`
- `.github/workflows/create-plan-from-issue.yml`
- `src/create_plan_from_issue.py`
- `plans/` (entire directory)

Renamed/updated files:
- `.agents/skills/check-impl-against-plan/SKILL.md` → `.agents/skills/check-impl-against-spec/SKILL.md`

Modified files:
- `.agents/skills/implement-issue/SKILL.md`
- `.agents/skills/review-pr/SKILL.md`
- `.github/workflows/comment-on-unready-assigned-issue.yml`
- `.github/workflows/create-implementation-from-issue.yml` (if needed for env var naming)
- `.github/STAKEHOLDERS`
- `src/create_implementation_from_issue.py`
- `src/enforce_pr_issue_state.py`
- `src/comment_on_unready_assigned_issue.py`
- `src/oz_workflows/helpers.py`
- `CONTRIBUTING.md`
- `README.md`
- `src/tests/` (update references)
5. **Two-skill vs one-skill approach for agent invocation**: Since the workflow runs a single Oz agent, and the agent can be given both skills in one prompt, we should invoke the agent once with instructions to use both `create-product-spec` and `create-tech-spec` sequentially. The `skill_name` parameter in `run_agent()` currently takes a single skill name — we will pass `skill_name=None` and embed explicit instructions in the prompt to read both `.agents/skills/create-product-spec/SKILL.md` and `.agents/skills/create-tech-spec/SKILL.md` by path. This avoids changes to `run_agent()` itself.
3. **`plan-approved` label**: The issue discussion says `plan-approved` is still targeted at the tech spec. No rename needed for this label — it continues to gate the transition from spec to implementation.
4. **Existing open PRs**: Any in-flight PRs on `oz-agent/plan-issue-*` branches will not be automatically migrated. This is acceptable since back-compat is explicitly not required.
