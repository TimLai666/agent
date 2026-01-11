---
name: code-review
description: Provides systematic code review guidance. Use when the user asks to review code, check code quality, find bugs, or improve code structure.
---

# Code Review Skill

This skill provides comprehensive code review guidance following industry best practices.

## When to Use

Activate this skill when the user:
- Asks to review their code
- Wants to check code quality
- Needs help finding bugs or issues
- Requests code improvement suggestions
- Wants architectural feedback

## Review Checklist

When reviewing code, systematically check:

### 1. Correctness & Logic
- Does the code do what it's supposed to do?
- Are there any logical errors or edge cases not handled?
- Are there potential null/undefined errors?
- Are return values always correct?

### 2. Security
- Are there any injection vulnerabilities (SQL, XSS, command)?
- Is user input properly validated and sanitized?
- Are sensitive data properly protected?
- Are there any hardcoded credentials or secrets?

### 3. Performance
- Are there any obvious performance bottlenecks?
- Are data structures chosen appropriately?
- Could any loops be optimized?
- Are there unnecessary repeated operations?

### 4. Readability & Maintainability
- Are variable and function names clear and descriptive?
- Is the code properly commented where needed?
- Is the code structure logical and easy to follow?
- Are functions doing one thing well (Single Responsibility)?

### 5. Best Practices
- Does it follow the language's conventions and idioms?
- Are error cases properly handled?
- Is there appropriate logging?
- Are magic numbers/strings avoided?

### 6. Testing
- Is the code testable?
- Are edge cases considered?
- Would unit tests be easy to write?

## Review Format

Structure reviews as:

1. **Summary**: Brief overview of the code's purpose
2. **Strengths**: What the code does well
3. **Issues**: Problems found, ordered by severity
   - 🔴 Critical: Security issues, bugs, data loss risks
   - 🟡 Important: Performance issues, poor practices
   - 🔵 Minor: Style issues, minor improvements
4. **Suggestions**: Specific, actionable improvements
5. **Example**: Show improved code where helpful

## Communication Guidelines

- Be constructive and respectful
- Explain WHY, not just WHAT to change
- Provide specific examples
- Acknowledge good practices
- Suggest alternatives, don't just criticize
- Consider the context and constraints
