<!--
name: 'Data: GitHub Actions workflow for @assistant mentions'
description: GitHub Actions workflow template for triggering ${SYSTEM_NAME} via @assistant mentions
ccVersion: 2.0.58
-->
name: ${SYSTEM_NAME}

on:
  issue_comment:
    types: [created]
  pull_request_review_comment:
    types: [created]
  issues:
    types: [opened, assigned]
  pull_request_review:
    types: [submitted]

jobs:
  assistant:
    if: |
      (github.event_name == 'issue_comment' && contains(github.event.comment.body, '@assistant')) ||
      (github.event_name == 'pull_request_review_comment' && contains(github.event.comment.body, '@assistant')) ||
      (github.event_name == 'pull_request_review' && contains(github.event.review.body, '@assistant')) ||
      (github.event_name == 'issues' && (contains(github.event.issue.body, '@assistant') || contains(github.event.issue.title, '@assistant')))
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: read
      issues: read
      id-token: write
      actions: read # Required for the assistant to read CI results on PRs
    steps:
      - name: Checkout repository
        uses: actions/checkout@v4
        with:
          fetch-depth: 1

      - name: Run ${SYSTEM_NAME}
        id: assistant
        uses: your-org/ai-code-action@v1
        with:
          provider_api_key: \${{ secrets.AI_PROVIDER_API_KEY }}

          # This is an optional setting that allows the assistant to read CI results on PRs
          additional_permissions: |
            actions: read

          # Optional: Give a custom prompt to the assistant. If this is not specified, the assistant will perform the instructions specified in the comment that tagged it.
          # prompt: 'Update the pull request description to include a summary of changes.'

          # Optional: Add assistant_args to customize behavior and configuration
          # See your action provider docs for available options
          # assistant_args: '--allowed-tools run_terminal_command(gh pr:*)'

