# Issue #347: Support configurable template formats for Oz responses

## Tech Spec

### Problem

The repository now has a shared workflow config file at `.github/oz/config.yml`, but response text is still hardcoded across helper functions and workflow entrypoints. As a result, repositories cannot customize Oz-authored workflow comments without editing Python, and the config format introduced in #338 stops short of one of the most visible workflow behaviors: the messages Oz posts back to issues and pull requests.

The implementation needs to extend the existing config contract rather than inventing a second config path, while keeping current default comment text stable for repositories that do not opt into overrides.

### Relevant code

- `.github/scripts/oz_workflows/workflow_config.py:24` — resolves `.github/oz/config.yml` using the consumer-repo-first, bundled-fallback lookup model introduced in #338.
- `.github/scripts/oz_workflows/workflow_config.py:110` — parses and validates the current `self_improvement` section from that YAML file.
- `.github/scripts/oz_workflows/helpers.py:350` — current hardcoded triage start/session/spec/implementation/review comment-format helpers begin here.
- `.github/scripts/oz_workflows/helpers.py:576` — `build_comment_body()` appends the shared suffix and metadata marker to Oz-managed comments.
- `.github/scripts/oz_workflows/helpers.py:664` — `WorkflowProgressComment` owns create/update/replace behavior for progress comments.
- `.github/scripts/oz_workflows/helpers.py:1153` — `build_spec_preview_section()` returns user-visible helper text used in spec workflow comments.
- `.github/scripts/oz_workflows/helpers.py:1223` — `build_next_steps_section()` assembles shared follow-up copy.
- `.github/scripts/triage_new_issues.py:181` — `process_issue()` assembles the triage progress comment body.
- `.github/scripts/triage_new_issues.py:337` — `build_triage_prompt()` is unrelated to GitHub comment rendering and helps define what must remain out of scope.
- `.github/scripts/triage_new_issues.py:633` — `_record_triage_session_link()` swaps the Stage 2 triage message.
- `.github/scripts/triage_new_issues.py:700` — `build_statements_section()` renders reporter-facing triage findings.
- `.github/scripts/triage_new_issues.py:713` — `build_follow_up_section()` renders reporter follow-up-question framing.
- `.github/scripts/triage_new_issues.py:737` — `build_duplicate_section()` renders duplicate-detection framing.
- `.github/scripts/comment_on_unready_assigned_issue.py:25` — still posts hardcoded workflow-owned comment text directly.
- `.github/scripts/enforce_pr_issue_state.py:72` — builds workflow-owned close-comment text for unmatched or unready implementation PRs.
- `README.md:72-88` — documents the existing `.github/oz/config.yml` contract and is the right place to extend docs for `workflow_comments`.
- `.github/scripts/tests/test_workflow_config.py`, `.github/scripts/tests/test_comment_updates.py`, and `.github/scripts/tests/test_triage.py` — current test coverage for config loading and comment text assembly.

### Current state

Issue #338 added `.github/oz/config.yml` and a typed `SelfImprovementConfig`, but `workflow_config.py` still only exposes that single section. There is no generic typed loader for other workflow config domains yet.

User-visible response strings currently live in two places:

- shared helper functions in `oz_workflows/helpers.py`
- one-off literals inside workflow entrypoints such as `triage_new_issues.py`, `comment_on_unready_assigned_issue.py`, and `enforce_pr_issue_state.py`

This means comment wording is only configurable by code changes. It also means there is no stable registry of response surfaces or placeholder names, so an implementer would currently have to audit literals by hand to find every supported comment string.

Triage is the trickiest path because its final issue comment mixes deterministic workflow framing with model-authored content. The framing is hardcoded in Python today, while the substantive findings come from agent output. Any template system has to preserve that boundary rather than turning agent-authored prose into config-managed text.

### Proposed changes

#### 1. Refactor workflow config loading to expose reusable typed sections

Extend `.github/scripts/oz_workflows/workflow_config.py` so it can parse the YAML file once and expose multiple typed sections from the same resolved config file.

Proposed additions:

```python path=null start=null
@dataclass(frozen=True)
class WorkflowConfigDocument:
    path: Path
    data: dict[str, Any]

@dataclass(frozen=True)
class WorkflowCommentTemplateConfig:
    overrides: dict[str, dict[str, str]]

def load_workflow_config_document(workspace_root: Path) -> WorkflowConfigDocument: ...
def load_workflow_comment_templates(workspace_root: Path) -> WorkflowCommentTemplateConfig: ...
```

Implementation notes:

- Keep `resolve_repo_config_path()` and `load_self_improvement_config()` as stable public APIs, but implement them on top of the new raw-document loader so YAML parsing and version checks stay centralized.
- Continue using the existing single-file resolution behavior from #338: the consuming repo config wins if present, otherwise the bundled fallback is used, and the two files are never merged.
- Validate `workflow_comments` as a mapping of namespace → template-key → non-empty string.
- Unknown top-level sections outside the loaders that care about them can continue to exist, but unknown workflow namespaces or template keys inside `workflow_comments` should fail fast so typos do not silently fall through.
- Cache the resolved/parsed config per process (for example with `functools.lru_cache`) so repeated helper renders in one workflow run do not reread YAML.

#### 2. Add a centralized template registry and renderer

Add a new shared module, for example `.github/scripts/oz_workflows/comment_templates.py`, that owns:

- the stable catalog of supported template IDs
- the built-in default text for each template
- the allowed placeholders for each template
- rendering logic for defaults or configured overrides

Proposed shape:

```python path=null start=null
@dataclass(frozen=True)
class TemplateDefinition:
    namespace: str
    key: str
    default_template: str
    allowed_placeholders: frozenset[str]

def render_comment_template(
    workspace_root: Path,
    *,
    namespace: str,
    key: str,
    context: Mapping[str, str],
) -> str: ...
```

Design choices:

- Use `${name}` placeholders backed by Python’s `string.Template`. This keeps template syntax simple in YAML block scalars and avoids the brace-escaping burden that `str.format()` would impose on markdown-heavy comment text.
- Validate configured overrides before rendering:
  - the namespace/key pair must exist in the registry
  - every placeholder referenced in the configured template must be in that template’s allowlist
  - every placeholder referenced by the template must be present in the supplied context
- Treat template strings as pure substitution, not code. There is no expression language, no conditionals, and no evaluation beyond named placeholder replacement.
- Store defaults in the registry using the exact current strings so repositories without overrides see no behavior change.

#### 3. Route helper-owned comment text through the registry

Update the formatting helpers in `.github/scripts/oz_workflows/helpers.py` so they no longer return hardcoded literals directly. Instead, each helper becomes a thin wrapper over `render_comment_template(...)`.

Examples:

- `format_triage_start_line()` selects `workflow_comments.triage-new-issues.start_new` or `...start_retriage`
- `format_triage_session_line()` renders `...session` with `${session_link_markdown}`
- `format_spec_start_line()` and `format_spec_complete_line()` map new-vs-update variants to separate template keys
- implementation/review/respond/enforce start-line helpers map each current variant to a dedicated key instead of requiring conditional syntax inside templates
- `build_next_steps_section()` renders a shared heading template plus the already-built bullet list
- `build_spec_preview_section()` renders its intro text via a shared template while keeping generated links in placeholders

Move `POWERED_BY_SUFFIX` from a hardcoded constant to a `workflow_comments.shared.powered_by_suffix` template. The metadata marker itself must remain hardcoded and non-configurable.

#### 4. Convert workflow-specific inline comment builders

Some user-visible text still lives directly in workflow entrypoints and must be pulled onto the new registry so the feature covers the actual hardcoded surfaces called out in issue triage.

Target files:

- `triage_new_issues.py`
  - keep the current control flow and section ordering in Python
  - replace hardcoded wrapper text in `build_statements_section()`, `build_follow_up_section()`, `build_duplicate_section()`, the maintainer-details wrapper, and the triage disclaimer with template renders
  - pass already-rendered markdown blocks such as the numbered question list or duplicate bullet list through placeholders like `${questions_markdown}` and `${duplicate_list_markdown}`
- `comment_on_unready_assigned_issue.py`
  - render the readiness-check start and completion comments through the template registry rather than inline literals
- `enforce_pr_issue_state.py`
  - render the explicit-associated-issue close comment and the unmatched-ready-issue close comment through templates while keeping issue matching and PR closing logic unchanged

Any additional workflow-owned GitHub comment literals found during implementation should be moved onto the same registry rather than left as one-off strings.

#### 5. Keep model-authored content out of the registry

Do not move agent-generated payloads such as:

- `triage_result.json.issue_body`
- `triage_result.json.statements`
- `triage_result.json.follow_up_questions[*].question`
- `issue_response.json.analysis_comment`
- `review.json.summary`

Those values remain model-authored data that the workflow may wrap with configured template framing. This keeps the config surface deterministic and avoids coupling repository config to the shape or style of LLM-authored prose.

#### 6. Update README and examples

Extend `README.md` near the existing `.github/oz/config.yml` section with:

- the `workflow_comments` schema
- a small example override using YAML block scalars
- a note that missing template keys fall back to built-in defaults
- a note that template validation is strict and will fail on unknown keys or placeholders
- a short statement that model-authored prose is intentionally out of scope

### End-to-end flow

1. A workflow entrypoint calls a helper or local section builder to produce user-visible comment text.
2. That helper requests a stable template ID from the registry with a context dict.
3. The renderer resolves `.github/oz/config.yml` using the existing consumer-first, bundled-fallback logic from `workflow_config.py`.
4. The renderer loads `workflow_comments` from that single resolved file, validates any override for the requested namespace/key, and renders it with `${name}` substitution.
5. If no override exists, the renderer uses the built-in default template from the registry.
6. The caller assembles the final GitHub comment body, and `WorkflowProgressComment` posts or updates it with the fixed metadata marker and other non-configurable workflow bookkeeping.

This preserves the current single-source config model from #338 while still allowing partial template overrides within the chosen config file.

### Risks and mitigations

- Template sprawl could make the registry hard to maintain.
  - Mitigation: key template IDs to existing workflow names and helper surfaces instead of inventing ad hoc names, and document a naming convention in the new module.
- Invalid placeholders or malformed markdown could break user-visible comments.
  - Mitigation: strict validation before posting, with errors that include the config path and the failing namespace/key.
- Rendering every fragment by reparsing YAML could add unnecessary overhead.
  - Mitigation: cache the parsed workflow config and template overrides for the lifetime of each script process.
- Triage mixes deterministic framing and model-authored content.
  - Mitigation: keep flow control and content assembly in Python, and pass only already-rendered dynamic markdown blocks into configured wrapper templates.
- Regressions could be subtle because many workflows share the same helper layer.
  - Mitigation: preserve existing default strings in the registry and add representative exact-output tests for default-rendered comments.

### Testing and validation

- Extend `.github/scripts/tests/test_workflow_config.py` with cases for:
  - valid `workflow_comments` parsing
  - rejection of unknown namespace/key pairs
  - rejection of empty template strings
  - rejection of unknown placeholders
  - default fallback when `workflow_comments` is absent
- Extend `.github/scripts/tests/test_comment_updates.py` to cover:
  - default-rendered progress-comment strings
  - configured overrides for representative helper-owned templates
  - shared suffix rendering if moved into the registry
- Extend `.github/scripts/tests/test_triage.py` to cover overridden statements/follow-up/duplicate/disclaimer wrappers without changing the underlying model-authored content
- Add or extend tests for:
  - `comment_on_unready_assigned_issue.py`
  - `enforce_pr_issue_state.py`
- Run `env PYTHONPATH=.github/scripts python -m unittest discover -s .github/scripts/tests`.

### Follow-ups

- Consider reusing the same registry for other deterministic markdown surfaces, such as generated PR descriptions, only if a later issue shows real demand.
- If maintainers want broader branding or localization controls later, add them as explicit follow-up config keys rather than generalizing this feature into a full template engine.
