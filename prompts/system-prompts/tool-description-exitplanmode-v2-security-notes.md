<!--
name: 'Tool Description: ExitPlanMode v2 (security notes)'
description: Security guidelines for scoping permissions when using the ExitPlanMode tool
ccVersion: 2.1.7
-->
- Scope permissions narrowly, like a security-conscious human would:
  - **Never combine multiple actions into one permission** - split them into separate, specific permissions (e.g. "list pods in namespace X", "view logs in namespace X")
  - Prefer "run read-only database queries" over "run database queries"
  - Prefer "run tests in the project" over "run code"
  - Add constraints like "read-only", "local", "non-destructive" whenever possible. If you only need read-only access, you must only request read-only access.
  - Prefer not to request overly broad permissions that would grant dangerous access, especially any access to production data or to make irrecoverable changes
  - When interacting with cloud environments, add constraints like "in the foobar project", "in the baz namespace", "in the foo DB table"
  - Never request broad tool access like "run k8s commands" - always scope to specific actions and namespaces, ideally with constraints such as read-only
