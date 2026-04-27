# Dockerfile for the PR review agent isolation container.
#
# The review workflow keeps GitHub mutations in the host-side Python driver but
# runs the Oz reviewer itself inside a locally-built container for dependency
# isolation and reproducibility. Unlike triage, the reviewer needs a writable
# repository mount so it can check out the PR head, generate `pr_diff.txt`,
# materialize `spec_context.md`, and write transient review artifacts before
# copying the final `review.json` to `/mnt/output`.

FROM warpdotdev/warp-agent:latest

USER root
RUN apt-get update -qq \
    && apt-get install -y -qq --no-install-recommends git jq python3 python-is-python3 \
    && rm -rf /var/lib/apt/lists/*
ENV HOME=/root

ENV OZ_REPO_ROOT=/mnt/repo

RUN mkdir -p /root/.agents /home/warp-agent/.agents \
    && ln -s /root/.agents/skills /home/warp-agent/.agents/skills

# Bake in the shared review skills and the spec-context helper so the
# containerized agent can run against any consuming repository checkout.
COPY .agents/skills/review-pr/SKILL.md /root/.agents/skills/review-pr/SKILL.md
COPY .agents/skills/review-pr/scripts/resolve_spec_context.py /root/.agents/skills/review-pr/scripts/resolve_spec_context.py
COPY .agents/skills/review-spec/SKILL.md /root/.agents/skills/review-spec/SKILL.md
COPY .agents/skills/security-review-pr/SKILL.md /root/.agents/skills/security-review-pr/SKILL.md
COPY .agents/skills/security-review-spec/SKILL.md /root/.agents/skills/security-review-spec/SKILL.md
COPY .agents/skills/check-impl-against-spec/SKILL.md /root/.agents/skills/check-impl-against-spec/SKILL.md

COPY docker/review/entrypoint.sh /review-entrypoint.sh
ENTRYPOINT ["/review-entrypoint.sh"]
