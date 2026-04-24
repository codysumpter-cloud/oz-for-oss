# Integration tests for oz-for-oss workflow scripts.
#
# These tests exercise the full main() entry-points of the Python workflow
# scripts with only the external API clients (GitHub REST API, Warp API)
# mocked out. They complement the fine-grained unit tests in the parent
# directory by verifying end-to-end data flow: event payload parsing,
# environment variable handling, GitHub state mutation, and the prompt
# construction that drives each agent skill invocation.
