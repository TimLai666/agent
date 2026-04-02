---
name: debugging-assistant
description: Systematic debugging guidance for finding and fixing code issues. Use when the user reports a bug, error, unexpected behavior, or asks for help troubleshooting.
---

# Debugging Assistant Skill

This skill provides structured debugging methodology to efficiently identify and resolve code issues.

## When to Use

Activate this skill when the user:
- Reports a bug or error
- Describes unexpected behavior
- Asks "why isn't this working?"
- Needs help troubleshooting
- Has a stack trace or error message

## Debugging Process

Follow this systematic approach:

### 1. Understand the Problem

**Gather Information:**
- What is the expected behavior?
- What is the actual behavior?
- When did it start happening?
- Can it be reproduced consistently?
- What are the exact steps to reproduce?
- Are there any error messages or stack traces?

**Ask Clarifying Questions:**
- What input causes the issue?
- Does it happen in all environments?
- Have there been recent changes?
- Are there any relevant logs?

### 2. Isolate the Issue

**Narrow Down:**
- Binary search: Comment out half the code to find which half contains the bug
- Trace execution: Add logging/prints to track program flow
- Check assumptions: Verify what you think is happening actually is
- Simplify: Create minimal reproducible example

**Common Culprits:**
- Input validation issues
- Off-by-one errors
- Null/undefined references
- Asynchronous timing issues
- Type mismatches
- Scope problems

### 3. Form Hypotheses

Based on the symptoms and isolated area:
- What could cause this behavior?
- List 2-3 most likely causes
- Order by probability

### 4. Test Hypotheses

For each hypothesis:
- Design a test to confirm/refute it
- Execute the test
- Observe results
- Update understanding

### 5. Fix and Verify

**Fix:**
- Implement the minimal fix
- Don't over-engineer the solution
- Consider edge cases

**Verify:**
- Test the original issue is fixed
- Test that nothing else broke
- Add regression test if appropriate

## Debugging Techniques

### Print/Log Debugging
```python
print(f"Debug: variable_name = {variable_name}")
print(f"Debug: reached checkpoint A")
```

### Rubber Duck Debugging
Explain the code line-by-line as if teaching someone else. Often reveals the issue.

### Divide and Conquer
Binary search through code or data to locate the problem.

### Check Assumptions
Verify:
- Variable values are what you think
- Functions are called when expected
- API responses match expectations
- Configuration is loaded correctly

## Common Bug Patterns

### Off-by-One
```python
# Wrong
for i in range(len(arr) - 1):  # Misses last element

# Right
for i in range(len(arr)):
```

### Null/Undefined
```python
# Wrong
result = data.get('key').split()  # Crashes if None

# Right
result = data.get('key')
if result:
    result = result.split()
```

### Async Issues
```javascript
// Wrong - race condition
async function wrong() {
    fetch('/api');
    return data;  // data not ready
}

// Right
async function right() {
    const data = await fetch('/api');
    return data;
}
```

### Type Issues
```python
# Wrong
"5" + 3  # Type error or unexpected result

# Right
int("5") + 3  # = 8
```

## Communication

When debugging with the user:
1. Acknowledge the frustration
2. Be systematic, not random
3. Explain your reasoning
4. Ask for confirmation at each step
5. Celebrate when the bug is found!

## Prevention

After fixing, consider:
- Could a test catch this?
- Is there a code pattern to avoid this class of bug?
- Should validation be added?
- Could types/linting help?
