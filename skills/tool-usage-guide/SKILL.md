---
name: tool-usage-guide
description: Guidance on when and how to use tools effectively. Use when the user asks about tools, API calls, or executing operations.
---

# Tool Usage Guide Skill

This skill provides best practices for using tools effectively in AI agent systems.

## When to Use Tools

Tools should be used when you need to:

### 1. Execute Real Operations
- Read or write files
- Make API calls
- Query databases
- Execute code
- Perform calculations

### 2. Get Real-Time Data
- Current weather
- Stock prices
- Search results
- System status
- Live metrics

### 3. Modify State
- Create/update/delete files
- Send emails or messages
- Update databases
- Modify configurations

### 4. Return Structured Data
- Parse JSON/XML
- Extract information
- Transform data formats
- Generate reports

## Tool Selection Guidelines

### Choose the Right Tool

**For File Operations:**
```python
# Reading
read_file(path)           # Read entire file
read_file_lines(path, start, end)  # Read specific lines

# Writing
write_file(path, content) # Write/overwrite
append_file(path, content) # Append
```

**For Web Operations:**
```python
search_web(query)         # Search engines
fetch_url(url)           # Get webpage content
api_call(endpoint, data)  # API requests
```

**For Data Operations:**
```python
parse_json(text)         # JSON parsing
parse_csv(text)          # CSV parsing
calculate(expression)    # Math calculations
```

## Best Practices

### 1. Check Before Acting

**Always verify:**
- Does the file/resource exist?
- Do I have permissions?
- Is the input valid?

**Example:**
```python
# ❌ Bad: Direct operation
content = read_file(path)

# ✅ Good: Check first
if file_exists(path):
    content = read_file(path)
else:
    # Handle missing file
```

### 2. Handle Errors Gracefully

**Anticipate failures:**
- Network timeouts
- Permission denied
- Invalid input
- Resource not found

**Example:**
```python
# Try the operation
result = api_call(endpoint)

# If it fails, have a fallback
if result.error:
    # Use cached data or default value
    result = get_cached_data()
```

### 3. Minimize Tool Calls

**Why:**
- Each call takes time
- Costs tokens
- Can hit rate limits

**Strategies:**
```python
# ❌ Bad: Multiple calls for same data
data1 = read_file("config.json")
data2 = read_file("config.json")  # Duplicate!

# ✅ Good: Call once, reuse
data = read_file("config.json")
# Use 'data' multiple times
```

### 4. Validate Input

**Before calling tools:**
```python
# ❌ Bad: No validation
write_file(user_path, user_content)

# ✅ Good: Validate first
if is_safe_path(user_path):
    if is_valid_content(user_content):
        write_file(user_path, user_content)
```

### 5. Use Appropriate Tools

**Match tool to task:**
```python
# ❌ Bad: Wrong tool
execute_bash("cat file.txt")  # Overkill

# ✅ Good: Right tool
read_file("file.txt")  # Direct and safe
```

## Common Patterns

### Pattern 1: Read-Process-Write

```python
# 1. Read input
data = read_file("input.txt")

# 2. Process (this is where you apply logic)
processed = transform(data)

# 3. Write output
write_file("output.txt", processed)
```

### Pattern 2: Try-Fallback

```python
# 1. Try primary source
result = api_call(primary_endpoint)

# 2. Fallback if needed
if not result:
    result = api_call(backup_endpoint)

# 3. Ultimate fallback
if not result:
    result = use_default_data()
```

### Pattern 3: Batch Operations

```python
# ❌ Bad: One at a time
for item in items:
    process(item)  # N tool calls

# ✅ Good: Batch when possible
process_batch(items)  # 1 tool call
```

## Security Considerations

### 1. Path Traversal Prevention

```python
# ❌ Dangerous
read_file(user_input)  # Could be "../../etc/passwd"

# ✅ Safe
safe_path = sanitize_path(user_input)
if is_within_allowed_dir(safe_path):
    read_file(safe_path)
```

### 2. Code Injection Prevention

```python
# ❌ Dangerous
execute_code(user_input)  # Could be malicious

# ✅ Safe
if is_safe_code(user_input):
    execute_in_sandbox(user_input)
```

### 3. API Key Protection

```python
# ❌ Bad: Exposed key
api_call(url, api_key="sk_live_...")

# ✅ Good: Use environment variables
api_call(url, api_key=get_env_var("API_KEY"))
```

## Performance Tips

### 1. Cache Results

```python
# Cache expensive operations
@cache
def get_heavy_data():
    return api_call(expensive_endpoint)

# Subsequent calls use cache
```

### 2. Parallel Execution

```python
# ❌ Sequential: Slow
data1 = fetch_url(url1)
data2 = fetch_url(url2)

# ✅ Parallel: Fast
data1, data2 = parallel_fetch([url1, url2])
```

### 3. Lazy Loading

```python
# Don't load until needed
def process():
    # Only load if condition met
    if needs_data:
        data = read_large_file()
```

## Error Messages

**Provide helpful errors:**
```python
# ❌ Bad
"Error"

# ✅ Good
"Failed to read 'config.json': File not found.
 Please check the file path is correct."
```

## Tool Composition

**Combine tools effectively:**
```python
# Example: Complete workflow
def analyze_data(filename):
    # 1. Read
    raw_data = read_file(filename)

    # 2. Parse
    data = parse_json(raw_data)

    # 3. Calculate
    stats = calculate_stats(data)

    # 4. Format
    report = format_report(stats)

    # 5. Write
    write_file("report.txt", report)
```

## Debugging Tool Calls

**When tools fail:**
1. Check the tool's return value
2. Look at error messages
3. Verify input parameters
4. Test with simpler inputs
5. Check permissions and access

**Example:**
```python
result = read_file(path)

if result.error:
    print(f"Error: {result.error}")
    print(f"Path tried: {path}")
    print(f"Does file exist: {file_exists(path)}")
```

## Summary

**Remember:**
- ✅ Use tools for actual operations
- ✅ Validate inputs before calling
- ✅ Handle errors gracefully
- ✅ Minimize unnecessary calls
- ✅ Choose appropriate tools
- ✅ Consider security
- ✅ Optimize performance

Tools are powerful but should be used thoughtfully and safely!
