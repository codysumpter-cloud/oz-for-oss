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
