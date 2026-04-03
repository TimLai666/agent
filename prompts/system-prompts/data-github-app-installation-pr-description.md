<!--
name: 'Data: GitHub App installation PR description'
description: Template for PR description when installing ${SYSTEM_NAME} GitHub App integration
ccVersion: 2.0.14
-->
## \uD83E\uDD16 Installing ${SYSTEM_NAME} GitHub App

This PR adds a GitHub Actions workflow that enables ${SYSTEM_NAME} integration in our repository.

### What is ${SYSTEM_NAME}?

${SYSTEM_NAME} is an AI coding agent that can help with:
- Bug fixes and improvements  
- Documentation updates
- Implementing new features
- Code reviews and suggestions
- Writing tests
- And more!

### How it works

Once this PR is merged, we'll be able to interact with ${SYSTEM_NAME} by mentioning @assistant in a pull request or issue comment.
Once the workflow is triggered, ${SYSTEM_NAME} will analyze the comment and surrounding context, and execute on the request in a GitHub action.

### Important Notes

- **This workflow won't take effect until this PR is merged**
- **@assistant mentions won't work until after the merge is complete**
- The workflow runs automatically whenever ${SYSTEM_NAME} is mentioned in PR or issue comments
- ${SYSTEM_NAME} gets access to the entire PR or issue context including files, diffs, and previous comments

### Security

- Our provider API key is securely stored as a GitHub Actions secret
- Only users with write access to the repository can trigger the workflow
- All ${SYSTEM_NAME} runs are stored in the GitHub Actions run history
- ${SYSTEM_NAME}'s default tools are limited to reading/writing files and interacting with our repo by creating comments, branches, and commits.
- We can add more allowed tools by adding them to the workflow file like:

\`\`\`
allowed_tools: run_terminal_command(npm install),run_terminal_command(npm run build),run_terminal_command(npm run lint),run_terminal_command(npm run test)
\`\`\`

There's more information in the ${SYSTEM_NAME} action documentation.

After merging this PR, let's try mentioning @assistant in a comment on any PR to get started!

