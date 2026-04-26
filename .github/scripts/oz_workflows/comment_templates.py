from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from string import Template
from typing import Mapping

from .env import workspace
from .workflow_config import load_workflow_config_document


_PLACEHOLDER_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


@dataclass(frozen=True)
class TemplateDefinition:
    namespace: str
    key: str
    default_template: str
    allowed_placeholders: frozenset[str]


@dataclass(frozen=True)
class WorkflowCommentTemplateConfig:
    overrides: dict[str, dict[str, str]]
    config_path: Path


def _definition(
    namespace: str,
    key: str,
    default_template: str,
    *,
    allowed_placeholders: tuple[str, ...] = (),
) -> TemplateDefinition:
    return TemplateDefinition(
        namespace=namespace,
        key=key,
        default_template=default_template,
        allowed_placeholders=frozenset(allowed_placeholders),
    )


_TEMPLATE_DEFINITIONS: tuple[TemplateDefinition, ...] = (
    _definition(
        "shared",
        "progress_session_session",
        "You can follow along in ${session_link_markdown}.",
        allowed_placeholders=("session_link_markdown",),
    ),
    _definition(
        "shared",
        "progress_session_conversation",
        "You can view ${session_link_markdown}.",
        allowed_placeholders=("session_link_markdown",),
    ),
    _definition(
        "shared",
        "spec_preview",
        "Preview generated specs:\n"
        "- Product spec: [${product_path}](${product_url})\n"
        "- Tech spec: [${tech_path}](${tech_url})",
        allowed_placeholders=("product_path", "product_url", "tech_path", "tech_url"),
    ),
    _definition(
        "shared",
        "next_steps_section",
        "Next steps:\n${next_steps_markdown}",
        allowed_placeholders=("next_steps_markdown",),
    ),
    _definition(
        "shared",
        "error_with_run_link",
        "I ran into an unexpected error while working on this. "
        "You can view [the workflow run](${workflow_run_url}) for more details.",
        allowed_placeholders=("workflow_run_url",),
    ),
    _definition(
        "shared",
        "error_without_run_link",
        "I ran into an unexpected error while working on this.",
    ),
    _definition(
        "triage-new-issues",
        "start_new",
        "I'm starting to work on triaging this issue.",
    ),
    _definition(
        "triage-new-issues",
        "start_retriage",
        "I'm re-triaging this issue based on new information.",
    ),
    _definition(
        "triage-new-issues",
        "session",
        "I'm ${triage_verb} this issue. You can follow ${session_link_markdown}.",
        allowed_placeholders=("session_link_markdown", "triage_verb"),
    ),
    _definition(
        "triage-new-issues",
        "complete_without_user_facing_content_with_session",
        "I've finished triaging this issue. "
        "A maintainer will verify the details shortly. "
        "You can view ${session_link_markdown}.",
        allowed_placeholders=("session_link_markdown",),
    ),
    _definition(
        "triage-new-issues",
        "complete_without_user_facing_content_without_session",
        "I've completed the triage of this issue.",
    ),
    _definition(
        "triage-new-issues",
        "session_link_only",
        "You can view ${session_link_markdown}.",
        allowed_placeholders=("session_link_markdown",),
    ),
    _definition(
        "triage-new-issues",
        "statements_with_reporter",
        "${reporter_mention} — here's what I found while triaging this issue:\n\n${statements_markdown}",
        allowed_placeholders=("reporter_mention", "statements_markdown"),
    ),
    _definition(
        "triage-new-issues",
        "statements_without_reporter",
        "Here's what I found while triaging this issue:\n\n${statements_markdown}",
        allowed_placeholders=("statements_markdown",),
    ),
    _definition(
        "triage-new-issues",
        "follow_up_with_reporter",
        "${reporter_mention} — I have a few follow-up questions before I can narrow this down:\n\n"
        "${questions_markdown}\n\n"
        "Reply in-thread with those details and the triage workflow will "
        "automatically re-evaluate the issue and update the diagnosis, "
        "labels, and next steps.",
        allowed_placeholders=("reporter_mention", "questions_markdown"),
    ),
    _definition(
        "triage-new-issues",
        "follow_up_without_reporter",
        "I have a few follow-up questions before I can narrow this down:\n\n"
        "${questions_markdown}\n\n"
        "Reply in-thread with those details and the triage workflow will "
        "automatically re-evaluate the issue and update the diagnosis, "
        "labels, and next steps.",
        allowed_placeholders=("questions_markdown",),
    ),
    _definition(
        "triage-new-issues",
        "duplicate_with_reporter",
        "${reporter_mention} — this issue appears to overlap with existing issues:\n\n"
        "${duplicate_list_markdown}\n\n"
        "If this report is meaningfully different, please comment with the "
        "additional context or distinguishing behavior so a maintainer can "
        "review it. Otherwise, a maintainer may close it as a duplicate after review.",
        allowed_placeholders=("reporter_mention", "duplicate_list_markdown"),
    ),
    _definition(
        "triage-new-issues",
        "duplicate_without_reporter",
        "This issue appears to overlap with existing issues:\n\n"
        "${duplicate_list_markdown}\n\n"
        "If this report is meaningfully different, please comment with the "
        "additional context or distinguishing behavior so a maintainer can "
        "review it. Otherwise, a maintainer may close it as a duplicate after review.",
        allowed_placeholders=("duplicate_list_markdown",),
    ),
    _definition(
        "triage-new-issues",
        "maintainer_details",
        "<details>\n<summary>Maintainer details</summary>\n\n${maintainer_details_markdown}\n\n</details>",
        allowed_placeholders=("maintainer_details_markdown",),
    ),
    _definition(
        "triage-new-issues",
        "disclaimer",
        "*This is my automated analysis and may be incorrect. A maintainer will verify the details.*",
    ),
    _definition(
        "respond-to-triaged-issue",
        "start",
        "I'm drafting an inline response to this comment. "
        "This issue is already triaged, so I'll reply without changing labels, "
        "the issue body, or assignees.",
    ),
    _definition(
        "create-spec-from-issue",
        "start_new",
        "I'm starting work on product and tech specs for this issue.",
    ),
    _definition(
        "create-spec-from-issue",
        "start_update",
        "I'm updating the existing spec PR for this issue.",
    ),
    _definition(
        "create-spec-from-issue",
        "complete_created",
        "I created a new [spec PR](${pr_url}) for this issue.",
        allowed_placeholders=("pr_url",),
    ),
    _definition(
        "create-spec-from-issue",
        "complete_updated",
        "I updated the existing [spec PR](${pr_url}) for this issue.",
        allowed_placeholders=("pr_url",),
    ),
    _definition(
        "create-spec-from-issue",
        "complete_no_diff",
        "I analyzed this issue but did not produce a spec diff.",
    ),
    _definition(
        "create-implementation-from-issue",
        "start_blocked_unapproved_specs",
        "I'm not starting implementation because the linked spec PR(s) "
        "have not been marked `plan-approved`${linked_spec_prs_suffix}.",
        allowed_placeholders=("linked_spec_prs_suffix",),
    ),
    _definition(
        "create-implementation-from-issue",
        "start_from_approved_spec_new_pr",
        "I'm implementing this issue on top of the approved spec PR's branch.",
    ),
    _definition(
        "create-implementation-from-issue",
        "start_from_approved_spec_update_pr",
        "I'm implementing this issue on top of the approved spec PR's branch (updating the existing draft PR).",
    ),
    _definition(
        "create-implementation-from-issue",
        "start_from_directory_specs_new_pr",
        "I'm implementing this issue using the repository's directory specs.",
    ),
    _definition(
        "create-implementation-from-issue",
        "start_from_directory_specs_update_pr",
        "I'm implementing this issue using the repository's directory specs (updating the existing draft PR).",
    ),
    _definition(
        "create-implementation-from-issue",
        "start_without_spec_context_new_pr",
        "I'm implementing this issue with no spec context.",
    ),
    _definition(
        "create-implementation-from-issue",
        "start_without_spec_context_update_pr",
        "I'm implementing this issue with no spec context (updating the existing draft PR).",
    ),
    _definition(
        "create-implementation-from-issue",
        "complete_updated_spec_pr",
        "I pushed implementation updates to the linked approved [spec PR](${pr_url}).",
        allowed_placeholders=("pr_url",),
    ),
    _definition(
        "create-implementation-from-issue",
        "complete_updated_existing_draft_pr",
        "I updated the existing draft [implementation PR](${pr_url}) for this issue.",
        allowed_placeholders=("pr_url",),
    ),
    _definition(
        "create-implementation-from-issue",
        "complete_created_new_draft_pr",
        "I created a new draft [implementation PR](${pr_url}) for this issue.",
        allowed_placeholders=("pr_url",),
    ),
    _definition(
        "create-implementation-from-issue",
        "complete_no_diff",
        "I analyzed this issue but did not produce an implementation diff.",
    ),
    _definition(
        "review-pull-request",
        "start_first_review_code",
        "I'm starting a first review of this pull request.${focus_suffix}",
        allowed_placeholders=("focus_suffix",),
    ),
    _definition(
        "review-pull-request",
        "start_first_review_spec",
        "I'm starting a first review of this spec-only pull request.${focus_suffix}",
        allowed_placeholders=("focus_suffix",),
    ),
    _definition(
        "review-pull-request",
        "start_rereview_code",
        "I'm re-reviewing this pull request in response to a review request.${focus_suffix}",
        allowed_placeholders=("focus_suffix",),
    ),
    _definition(
        "review-pull-request",
        "start_rereview_spec",
        "I'm re-reviewing this spec-only pull request in response to a review request.${focus_suffix}",
        allowed_placeholders=("focus_suffix",),
    ),
    _definition(
        "review-pull-request",
        "complete_no_feedback",
        "I completed the review and did not identify any actionable feedback for this pull request.",
    ),
    _definition(
        "review-pull-request",
        "complete_approved_with_reviewers",
        "I approved this pull request and requested human review from: ${reviewer_mentions}.",
        allowed_placeholders=("reviewer_mentions",),
    ),
    _definition(
        "review-pull-request",
        "complete_approved_no_reviewers",
        "I approved this pull request. No matching stakeholder was found "
        "for the changed files, so no human reviewers were requested.",
    ),
    _definition(
        "review-pull-request",
        "complete_changes_requested",
        "I requested changes on this pull request and posted feedback.",
    ),
    _definition(
        "review-pull-request",
        "complete_commented",
        "I completed the review and posted feedback on this pull request.",
    ),
    _definition(
        "respond-to-pr-comment",
        "start_review_reply_with_spec_context",
        "I'm working on changes requested in this PR (responding to an inline review-thread comment). "
        "Spec context was found and will be used to ground the change.",
    ),
    _definition(
        "respond-to-pr-comment",
        "start_review_reply_without_spec_context",
        "I'm working on changes requested in this PR (responding to an inline review-thread comment).",
    ),
    _definition(
        "respond-to-pr-comment",
        "start_review_body_with_spec_context",
        "I'm working on changes requested in this PR (responding to a PR review body). "
        "Spec context was found and will be used to ground the change.",
    ),
    _definition(
        "respond-to-pr-comment",
        "start_review_body_without_spec_context",
        "I'm working on changes requested in this PR (responding to a PR review body).",
    ),
    _definition(
        "respond-to-pr-comment",
        "start_conversation_comment_with_spec_context",
        "I'm working on changes requested in this PR (responding to a PR conversation comment). "
        "Spec context was found and will be used to ground the change.",
    ),
    _definition(
        "respond-to-pr-comment",
        "start_conversation_comment_without_spec_context",
        "I'm working on changes requested in this PR (responding to a PR conversation comment).",
    ),
    _definition(
        "respond-to-pr-comment",
        "complete_no_diff",
        "I analyzed the request but did not produce any changes.",
    ),
    _definition(
        "comment-on-unready-assigned-issue",
        "start",
        "I'm checking whether this assignment is ready for work.",
    ),
    _definition(
        "comment-on-unready-assigned-issue",
        "complete",
        "This issue is assigned to me, but it is not labeled `ready-to-spec` or `ready-to-implement`, so there is no work to do yet.",
    ),
    _definition(
        "enforce-pr-issue-state",
        "start_explicit_issue",
        "I'm checking this ${change_kind} PR for association with an explicitly linked issue.",
        allowed_placeholders=("change_kind",),
    ),
    _definition(
        "enforce-pr-issue-state",
        "start_matching_ready_issue",
        "I'm checking this ${change_kind} PR for association with a likely matching ready issue.",
        allowed_placeholders=("change_kind",),
    ),
    _definition(
        "enforce-pr-issue-state",
        "close_explicit_issue_not_ready",
        "The PR that you've opened seems to contain ${change_kind} changes and is associated with issue "
        "${issue_refs}, but none of those associated ${associated_issue_noun} are marked as "
        "`${required_label}`. This PR will be automatically closed. Please see our "
        "[contribution docs](${contribution_docs_url}) for guidance on when changes are accepted for issues.",
        allowed_placeholders=(
            "change_kind",
            "issue_refs",
            "associated_issue_noun",
            "required_label",
            "contribution_docs_url",
        ),
    ),
    _definition(
        "enforce-pr-issue-state",
        "close_no_matching_ready_issue",
        "I couldn't confidently match this ${change_kind} PR to an issue marked `${required_label}`, "
        "so this PR will be automatically closed.\n\n"
        "Rationale: ${association_rationale}\n\n"
        "Please see our [contribution docs](${contribution_docs_url}) for guidance on when changes are accepted for issues.",
        allowed_placeholders=(
            "change_kind",
            "required_label",
            "association_rationale",
            "contribution_docs_url",
        ),
    ),
)

_TEMPLATE_REGISTRY: dict[tuple[str, str], TemplateDefinition] = {
    (definition.namespace, definition.key): definition
    for definition in _TEMPLATE_DEFINITIONS
}
_KNOWN_NAMESPACES = {definition.namespace for definition in _TEMPLATE_DEFINITIONS}


def _fail(config_path: Path, message: str) -> RuntimeError:
    return RuntimeError(f"{config_path}: {message}")


def _template_source(namespace: str, key: str) -> str:
    return f"workflow_comments.{namespace}.{key}"


def _extract_placeholders(
    template_text: str,
    *,
    config_path: Path | None = None,
    namespace: str = "",
    key: str = "",
) -> set[str]:
    placeholders: set[str] = set()
    index = 0
    while index < len(template_text):
        if template_text[index] != "$":
            index += 1
            continue
        if index + 1 < len(template_text) and template_text[index + 1] == "$":
            index += 2
            continue
        match = _PLACEHOLDER_PATTERN.match(template_text, index)
        if match is not None:
            placeholders.add(match.group(1))
            index = match.end()
            continue
        if config_path is not None:
            raise _fail(
                config_path,
                f"Invalid placeholder syntax in {_template_source(namespace, key)}. "
                "Use ${name} placeholders.",
            )
        raise RuntimeError(
            f"Invalid placeholder syntax in default workflow comment template "
            f"{namespace}.{key}. Use ${name} placeholders."
        )
    return placeholders


def _validate_template_definition(definition: TemplateDefinition) -> None:
    placeholders = _extract_placeholders(
        definition.default_template,
        namespace=definition.namespace,
        key=definition.key,
    )
    unknown_placeholders = sorted(placeholders - definition.allowed_placeholders)
    if unknown_placeholders:
        joined = ", ".join(unknown_placeholders)
        raise RuntimeError(
            f"Default workflow comment template {definition.namespace}.{definition.key} "
            f"references unsupported placeholders: {joined}."
        )


for _definition_item in _TEMPLATE_DEFINITIONS:
    _validate_template_definition(_definition_item)


def get_template_definition(namespace: str, key: str) -> TemplateDefinition:
    definition = _TEMPLATE_REGISTRY.get((namespace, key))
    if definition is None:
        raise RuntimeError(f"Unknown workflow comment template: {namespace}.{key}")
    return definition


@lru_cache(maxsize=None)
def _load_workflow_comment_template_config_cached(
    workspace_root: Path,
) -> WorkflowCommentTemplateConfig:
    document = load_workflow_config_document(workspace_root)
    config_path = document.path
    raw_section = document.data.get("workflow_comments")
    if raw_section is None:
        return WorkflowCommentTemplateConfig(overrides={}, config_path=config_path)
    if not isinstance(raw_section, dict):
        raise _fail(config_path, "workflow_comments must be a YAML mapping.")

    overrides: dict[str, dict[str, str]] = {}
    for raw_namespace, raw_templates in raw_section.items():
        if not isinstance(raw_namespace, str) or not raw_namespace.strip():
            raise _fail(config_path, "workflow_comments keys must be non-empty strings.")
        namespace = raw_namespace.strip()
        if not isinstance(raw_templates, dict):
            raise _fail(
                config_path,
                f"workflow_comments.{namespace} must be a YAML mapping of template keys to strings.",
            )
        parsed_templates: dict[str, str] = {}
        for raw_key, raw_template in raw_templates.items():
            if not isinstance(raw_key, str) or not raw_key.strip():
                raise _fail(
                    config_path,
                    f"workflow_comments.{namespace} keys must be non-empty strings.",
                )
            key = raw_key.strip()
            definition = _TEMPLATE_REGISTRY.get((namespace, key))
            if definition is None:
                if namespace not in _KNOWN_NAMESPACES:
                    raise _fail(
                        config_path,
                        f"Unknown workflow_comments namespace: {namespace}.",
                    )
                raise _fail(
                    config_path,
                    f"Unknown workflow comment template key: {_template_source(namespace, key)}.",
                )
            if not isinstance(raw_template, str):
                raise _fail(
                    config_path,
                    f"{_template_source(namespace, key)} must be a string.",
                )
            if not raw_template.strip():
                raise _fail(
                    config_path,
                    f"{_template_source(namespace, key)} must not be blank.",
                )
            placeholders = _extract_placeholders(
                raw_template,
                config_path=config_path,
                namespace=namespace,
                key=key,
            )
            unknown_placeholders = sorted(
                placeholders - definition.allowed_placeholders
            )
            if unknown_placeholders:
                raise _fail(
                    config_path,
                    f"Unknown placeholders in {_template_source(namespace, key)}: "
                    + ", ".join(unknown_placeholders),
                )
            parsed_templates[key] = raw_template
        overrides[namespace] = parsed_templates
    return WorkflowCommentTemplateConfig(overrides=overrides, config_path=config_path)


def load_workflow_comment_template_config(
    workspace_root: Path | None = None,
) -> WorkflowCommentTemplateConfig:
    return _load_workflow_comment_template_config_cached(
        Path(workspace_root or workspace()).resolve()
    )


def render_comment_template(
    workspace_root: Path | None = None,
    *,
    namespace: str,
    key: str,
    context: Mapping[str, str] | None = None,
) -> str:
    definition = get_template_definition(namespace, key)
    config = load_workflow_comment_template_config(workspace_root)
    override_text = config.overrides.get(namespace, {}).get(key)
    template_text = override_text or definition.default_template
    placeholders = _extract_placeholders(
        template_text,
        namespace=namespace,
        key=key,
    )
    normalized_context = {
        name: str(value)
        for name, value in (context or {}).items()
    }
    missing = sorted(name for name in placeholders if name not in normalized_context)
    if missing:
        if override_text:
            raise _fail(
                config.config_path,
                f"Missing placeholder values for workflow comment template "
                f"{namespace}.{key}: {', '.join(missing)}.",
            )
        raise RuntimeError(
            f"Missing placeholder values for workflow comment template "
            f"{namespace}.{key}: {', '.join(missing)}."
        )
    return Template(template_text).substitute(normalized_context)
