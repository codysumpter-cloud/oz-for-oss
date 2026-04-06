# Issue #157: Triage issue agent duplicates comments posted

## Product Spec

### Summary

The triage workflow currently posts up to three separate comments on an issue (progress, follow-up questions, duplicate detection). All triage output should be consolidated into a single comment that updates in place as the triage progresses, and session links should use markdown link syntax instead of raw URLs.

### Problem

When the triage agent runs on an issue, it creates multiple distinct comments:

1. A progress/status comment managed by `WorkflowProgressComment`.
2. A separate follow-up questions comment managed by `sync_follow_up_comment()`.
3. A separate duplicate-detection comment managed by `sync_duplicate_comment()`.

This clutters the issue timeline, is confusing for reporters, and makes it harder for maintainers to see the full triage result at a glance. Additionally, session links appear as raw URLs instead of readable markdown links.

### Goals

- All triage output (progress, session link, triage summary, follow-up questions, duplicate detection) appears in a single issue comment.
- That comment updates in place through three progression stages rather than spawning new comments.
- Session links use markdown link syntax.
- The triage disclaimer appears exactly once, at the end of the consolidated comment.

### Non-goals

- Changing the triage agent's internal behavior or the `triage_result.json` schema.
- Changing which labels are applied or how the issue body is rewritten.
- Changing the `respond_to_triaged_issue_comment` workflow or re-triage behavior (beyond ensuring re-triage replaces the consolidated comment correctly).
- Changing the progress comment behavior of non-triage workflows (spec creation, implementation). Only the triage workflow's comment lifecycle changes.

### Figma / design references

Figma: none provided. This is a backend/workflow change with no UI beyond GitHub issue comments.

### User experience

#### Comment progression stages

The single triage comment progresses through three stages. Each stage replaces the previous content of the comment (not appended):

**Stage 1 — Started:**
> @{requester}
>
> Oz is starting to work on triaging this issue.

**Stage 2 — In progress (session link available):**
> @{requester}
>
> Oz is triaging this issue. You can follow the triage session on [Warp]({session_url}).

**Stage 3 — Completed:**
> @{requester}
>
> Oz has completed the triage of this issue. You can view the triage session on [Warp]({session_url}). The triage concluded: {summary}.
>
> ### Follow-up questions
>
> {numbered list of questions, with @reporter mention and context text}
>
> ### Potential duplicates
>
> {list of duplicate issues with titles and similarity reasons}
>
> *This is an automated analysis by Oz and may be incorrect. A maintainer will verify the details.*

#### Conditional sections in Stage 3

- The **Follow-up questions** section only appears if the triage result includes follow-up questions. When present, it includes the `@reporter` mention and the existing contextual text ("Thanks for the report. I'm missing a few issue-specific details...").
- The **Potential duplicates** section only appears if the triage result identifies duplicate issues. When present, it includes the existing contextual text ("This issue appears likely to overlap...").
- The **disclaimer** always appears at the end of the completed comment.
- If neither follow-up questions nor duplicates are present, the comment ends after the summary sentence and the disclaimer.

#### Session link formatting

All session links use markdown syntax: `[Warp]({url})` for conversation links and `[Warp]({url})` for sharing links. The link text is "Warp" in both cases.

#### Re-triage behavior

When the triage workflow runs again on the same issue (e.g., triggered by a new comment), the existing consolidated comment is found by its metadata marker and updated in place. The comment returns to Stage 1 and progresses through the stages again. Follow-up question and duplicate sections from a previous run are replaced by the new triage result.

#### Cleanup of legacy comments

On re-triage, any orphaned standalone follow-up or duplicate comments from previous runs (created before this change) should be cleaned up. This is a one-time migration concern.

### Success criteria

1. A triage run that produces follow-up questions and duplicate detection results in exactly one bot comment on the issue, not two or three.
2. A triage run that produces neither follow-up questions nor duplicates results in exactly one bot comment.
3. The single comment progresses through the three defined stages during the triage run.
4. Session links in the comment use markdown `[Warp](url)` syntax, not raw URLs.
5. The `@requester` mention appears at the top of the comment in all stages.
6. The triage disclaimer appears exactly once, at the bottom of the completed Stage 3 comment.
7. Follow-up questions include the `@reporter` mention and the contextual preamble text.
8. Duplicate detection results include issue links, titles, and similarity reasons.
9. Re-triage updates the same comment in place; no new comments are created.
10. Existing standalone follow-up and duplicate comments from prior runs are cleaned up on re-triage.
11. All existing tests continue to pass (with updates to reflect the new consolidated structure).

### Validation

- **Unit tests**: Update existing `SyncFollowUpCommentTest` and `SyncDuplicateCommentTest` to verify that follow-up and duplicate content is merged into the progress comment rather than created as separate comments.
- **Integration test**: Verify that `process_issue()` produces exactly one comment containing progress, follow-up questions (when present), and duplicate info (when present).
- **Manual validation**: Trigger triage on a test issue and confirm that the GitHub issue shows a single comment that updates through the three stages.
- **Regression**: Verify that triage runs without follow-up questions or duplicates still produce a correct single comment.
- **Link formatting**: Inspect the comment to confirm session links use markdown syntax.

### Open questions

1. Should Stage 2 message text change if the session link is a "sharing" link vs. a "conversation" link, or should both just say "Warp"? The current code has different prefixes for these two cases.
2. When re-triage runs and the previous comment had follow-up questions, should the reply-in-thread guidance text still reference the previous questions, or is a clean replacement sufficient?
