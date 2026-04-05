# Auto Mode Classifier Cost — Every Tool Use Triggers a Hidden LLM Call at Your Expense

> **CLI Version:** @anthropic-ai/claude-code v2.1.88 (build 2026-03-30)
> **Date:** 2026-03-31
> **Method:** Static reverse engineering of minified cli.js (16,667 lines, 13 MB)

---

## Summary

Claude Code's Auto Mode — the mode that "only asks for permission when necessary" — makes a hidden API call before every side-effecting tool use. This call sends a condensed version of the entire conversation history to a classifier LLM, which decides whether to allow or block the action.

In recent versions (v2.1.88), the classifier model was changed from a hardcoded Sonnet to inherit the main conversation model. For Max subscribers, this means the classifier runs on Opus — the same tier as the main conversation. Every Edit, Write, Bash, and MCP tool call silently consumes Opus-level tokens on top of the main conversation.

The classifier also has prompt caching via `cache_control: ephemeral`, but only the fixed portions (system prompt + CLAUDE.md) benefit from it. The conversation transcript — which is the largest and fastest-growing portion — has no cache breakpoint and is billed at full input price every call.

A Statsig-controlled feature flag can additionally enable a two-stage classifier, doubling the API calls per tool use without any user visibility or control.

---

## Table of Contents

1. [What the Classifier Does](#1-what-the-classifier-does)
2. [When It Fires and When It Doesn't](#2-when-it-fires-and-when-it-doesnt)
3. [What Gets Sent to the Classifier](#3-what-gets-sent-to-the-classifier)
4. [Model Selection — Why Max Users Pay More](#4-model-selection--why-max-users-pay-more)
5. [The Cache Illusion](#5-the-cache-illusion)
6. [Two-Stage Classifier — The Remote Kill Switch](#6-two-stage-classifier--the-remote-kill-switch)
7. [Cost Estimation](#7-cost-estimation)
8. [Mitigation](#8-mitigation)
9. [Source Code Reference](#9-source-code-reference)

---

## 1. What the Classifier Does

When you enable Auto Mode in Claude Code, the system no longer asks for permission before every tool use. Instead, it makes a separate API call to determine whether each action should be allowed, blocked, or escalated to the user.

The flow looks like this:

```
Claude proposes a tool use (e.g., Edit a file)
  │
  ├─ Is this tool in the hardcoded allowlist?
  │   Yes → Execute immediately, no API call
  │
  ├─ Does alwaysAllowRules match this action?
  │   Yes → Execute immediately, no API call
  │
  └─ Neither → Make a classifier API call
      │
      ├─ Classifier says "allow" → Execute
      ├─ Classifier says "deny"  → Block
      └─ Classifier says "ask"   → Prompt the user
```

The classifier is a full API request: it has its own system prompt (a permission policy), its own message history (a condensed transcript), and a dedicated tool (`classify_result`) that returns the verdict. It runs with `temperature: 0` and `maxRetries: 10`.

**Source:** Function `kL8()` at byte offset 7,027,377.

---

## 2. When It Fires and When It Doesn't

### Hardcoded allowlist — classifier skipped entirely

These tools never trigger the classifier, regardless of mode:

```
Read, Grep, Glob, LSP, ToolSearch,
ListMcpResourcesTool, ReadMcpResourceTool,
TodoWrite, TaskCreate, TaskGet, TaskUpdate, TaskList, TaskStop, TaskOutput,
AskUserQuestion, EnterPlanMode, ExitPlanMode,
TeamCreate, TeamDelete, SendMessage, Sleep
```

**Source:** `isAutoModeAllowlistedTool()`, Set `N$Y` at byte offset 9,850,151.

### User-configured rules — classifier skipped via path match

If you set `alwaysAllowRules` in settings with a path pattern (e.g., `Edit(/your/project/**)`), the permission check returns "allow" before the classifier is invoked. This only works for tools that have a file path (Edit, Write). Bash and MCP tools cannot be path-matched.

**Source:** Function `Qj6()` at byte offset 11,419,986.

### Everything else — classifier fires

Every Edit, Write, Bash, PowerShell, Agent spawn, MCP tool call, NotebookEdit, WebSearch, WebFetch, Skill invocation, and CronCreate/Delete triggers a classifier API call. In a typical turn where Claude uses 5 tools, that's 5 separate classifier calls.

---

## 3. What Gets Sent to the Classifier

The classifier doesn't just see the current action. It receives a condensed version of the entire conversation.

### Transcript construction (`tb4()`)

The function `tb4()` at byte offset 7,020,034 processes the full message array:

- **User messages** → text content preserved (everything you typed)
- **Assistant messages** → only `tool_use` blocks preserved (tool name + input parameters)
- **Tool results** → discarded entirely
- **Assistant text replies** → discarded entirely

This means every tool Claude has ever used in the conversation — including Read, Grep, and other allowlisted tools that themselves don't trigger the classifier — appears in the transcript of every subsequent classifier call.

### How each tool represents itself

Each tool defines a `toAutoClassifierInput()` method that controls what gets sent:

```js
// Write — full file content 💸
toAutoClassifierInput(input) { return `${input.file_path}: ${input.content}` }

// Edit — file path + new_string only
toAutoClassifierInput(input) { return `${input.file_path}: ${input.new_string}` }

// Bash / PowerShell — full command string
toAutoClassifierInput(input) { return input.command }

// Read — file path only (doesn't trigger classifier, but appears in transcript)
toAutoClassifierInput(input) { return input.file_path }
```

Write is the worst offender: if Claude writes a 500-line file, the entire content is included in the classifier's input.

### What the classifier actually sees

```
User: Fix the error handling in foo.ts
Read src/foo.ts                                          ← in transcript, didn't trigger classifier
Grep {"pattern":"handleError","path":"src/"}             ← in transcript, didn't trigger classifier
Edit {"file_path":"src/foo.ts","new_string":"..."}       ← in transcript from previous call
User: Now run the tests
Bash {"command":"npm test"}                              ← in transcript from previous call
Edit {"file_path":"src/bar.ts","new_string":"..."}       ← THIS is the action being classified
```

The transcript grows with every tool use in the conversation. Read 10 files, grep 5 patterns, edit 3 files — all 18 operations appear in the next classifier call's input.

**Source:** Functions `tb4()` at offset 7,020,034, `qx4()` at offset 7,021,021.

---

## 4. Model Selection — Why Max Users Pay More

### The resolution chain

The classifier model is determined by `lb4()` at byte offset 7,031,025:

```js
function lb4() {
  // 1. Statsig remote override (highest priority)
  let config = featureFlag("tengu_auto_mode_config", {});
  if (config?.model) return config.model;

  // 2. Fall back to main conversation model
  return getMainLoopModel();
}
```

`getMainLoopModel()` resolves through `D5()` → `jS()` → `If()` → `KG()`:

```js
function KG() {
  if (isMaxSubscription())    return "claude-opus-4-6[1m]";
  if (isTeam5xSubscription()) return "claude-opus-4-6[1m]";
  return "claude-sonnet-4-6";  // everyone else
}
```

### What this means

| Subscription | Main model | Classifier model | Relative input cost |
|---|---|---|---|
| Max | claude-opus-4-6 | claude-opus-4-6 | 1× (most expensive) |
| Team 5x | claude-opus-4-6 | claude-opus-4-6 | 1× |
| Pro / Free | claude-sonnet-4-6 | claude-sonnet-4-6 | ~0.2× |
| Bedrock/Vertex | claude-sonnet-4-5 | claude-sonnet-4-5 | ~0.2× |

For Max users, the classifier costs the same per-token as the main conversation. In earlier versions (v2.1.85), the classifier was hardcoded to `"claude-sonnet-4-6"` for everyone. The change to inherit the main model means Max users now pay ~5× more per classifier call than before.

---

## 5. The Cache Illusion

The classifier request includes `cache_control: { type: "ephemeral" }` at three points. This creates an impression of caching efficiency. The reality is less favorable.

### Cache breakpoint structure

```
┌─ system prompt ────────────── cache_control ──┐  Breakpoint 1 (stable)
│  Permission policy, rules                      │
└────────────────────────────────────────────────┘

┌─ CLAUDE.md ────────────────── cache_control ──┐  Breakpoint 2 (stable)
│  User's CLAUDE.md content                      │
└────────────────────────────────────────────────┘
                                                    ↑ Cache hits up to here
                                                    ↓ Everything below is uncached
┌─ Transcript + Action ─────────────────────────┐
│  User: your first message                      │  No breakpoint
│  Read src/foo.ts                               │  No breakpoint
│  Edit {"file_path":..., "new_string":...}      │  No breakpoint
│  User: your second message                     │  No breakpoint
│  ...grows with every tool use...               │
│  Bash {"command":"npm test"}  ── cache_control │  Breakpoint 3 (changes every call)
└────────────────────────────────────────────────┘
```

Anthropic's API cache matches the **longest identical prefix ending at a cache breakpoint**. Since the transcript portion comes after breakpoint 2 and changes between calls (new tool uses get appended), the cache match stops at breakpoint 2.

### Effective cache rates

| Session stage | Fixed portion (cached at 10%) | Transcript (full price) | Cache savings |
|---|---|---|---|
| Early (5 turns) | ~2k tokens | ~2k tokens | ~45% |
| Mid (20 turns) | ~2k tokens | ~6k tokens | ~22% |
| Late (50+ turns) | ~2k tokens | ~15k tokens | ~9% |

The fixed portion (system prompt + CLAUDE.md) stays constant at ~1–2k tokens. The transcript grows linearly with tool usage. By mid-session, the cached portion is a small fraction of the total, and caching provides marginal savings.

**Source:** `pU()` (cache_control factory) at offset 11,539,575; `qMz()` (CLAUDE.md injection) at offset 7,021,531.

---

## 6. Two-Stage Classifier — The Remote Kill Switch

A Statsig-gated feature adds a second classification pass. Function `OMz()` at byte offset ~7,024,500:

### How it works

The feature flag `tengu_auto_mode_config.twoStageClassifier` can be set to:

| Value | Behavior | Max API calls per tool use |
|---|---|---|
| `false` (default) | Single-pass classifier | 1 |
| `"fast"` | Quick check: max_tokens=256, stop at `</block>` | 1 |
| `"thinking"` | Full reasoning: max_tokens=4096, with thinking | 1 |
| `true` or `"both"` | Fast first, thinking if not immediately allowed | **2** |

When set to `true` or `"both"`, a single Edit operation can trigger two classifier API calls — both using Opus for Max users.

### User control

None. The flag is controlled via Statsig, Anthropic's feature flag service. It can be enabled for specific users, cohorts, or globally without notice. There is no environment variable or setting to override it.

**Source:** `$x4()` at offset 7,031,120; `wMz()` and `OMz()` at offset ~7,024,500.

---

## 7. Cost Estimation

### Single classifier call

Assuming a mid-session transcript of ~4k tokens, system prompt + CLAUDE.md of ~2k tokens:

| User type | Model | Cached (2k @ 10%) | Uncached (4k @ 100%) | Output (~100 tokens) | Per-call cost |
|---|---|---|---|---|---|
| Max | Opus | $0.003 | $0.060 | $0.008 | ~$0.071 |
| Pro | Sonnet | $0.001 | $0.012 | $0.003 | ~$0.016 |

### Session accumulation

A 20-turn session with 3 side-effecting tool uses per turn = 60 classifier calls:

| User type | Classifier total | Main conversation total | Classifier overhead |
|---|---|---|---|
| Max (Opus) | ~$4.3 | ~$15–30 | **15–28%** |
| Pro (Sonnet) | ~$1.0 | ~$3–6 | **15–28%** |

With two-stage classifier enabled: multiply by 1.5–2×.

### The compounding effect

The transcript grows with every tool use. Early classifier calls are cheap (small transcript), but later ones are expensive. In a 50-turn heavy session, the last classifier calls can have 15k+ token transcripts — approaching the size of the main conversation's system prompt.

---

## 8. Mitigation

### Option 1: Set path-based allow rules (zero modification)

In `.claude/settings.local.json`:

```json
{
  "permissions": {
    "allow": [
      "Edit(/your/project/**)",
      "Write(/your/project/**)"
    ]
  }
}
```

Matched operations skip the classifier entirely. Only works for Edit/Write (path-matchable tools). Bash, Agent, MCP tools still trigger the classifier.

### Option 2: Patch the classifier model to Haiku

Replace `lb4()` in cli.js to always return Haiku:

```
Find:    function lb4(){let q=g8("tengu_auto_mode_config",{});if(q?.model)return q.model;return D5()}
Replace: function lb4(){return"claude-haiku-4-5-20251001"}
```

This reduces classifier input cost by ~60× (Opus → Haiku). The classification task is a simple allow/deny decision — Haiku is more than capable.

**Uniqueness check:** The find pattern matches exactly 1 location in cli.js.

### Option 3: Disable the classifier entirely

Patch `kL8()` to always return allow:

```
Find:    async function kL8(q,K,_,z,Y){let $=eb4(_),
Replace: async function kL8(q,K,_,z,Y){return{shouldBlock:!1,reason:"patched"};let $=eb4(_),
```

This eliminates all classifier API calls. Auto Mode becomes fully automatic with no safety checks.

### Option 4: Don't use Auto Mode

Manual permission approval for every tool use. Zero classifier overhead, maximum friction.

---

## 9. Source Code Reference

| Symbol | Byte offset | Purpose |
|---|---|---|
| `kL8()` | 7,027,377 | Classifier main function |
| `tb4()` | 7,020,034 | Conversation transcript builder |
| `qx4()` | 7,021,021 | Message block → text converter |
| `qMz()` | 7,021,531 | CLAUDE.md injection for classifier |
| `lb4()` | 7,031,025 | Classifier model selection |
| `KG()` | 2,429,000 | Main model resolution (Max → Opus) |
| `HS()` | 3,508,465 | Max subscription check |
| `DG6()` | 3,462,663 | Auto Mode enablement gate |
| `N$Y` | 9,850,151 | Hardcoded tool allowlist Set |
| `Qj6()` | 11,419,986 | alwaysAllowRules permission check |
| `OMz()` | ~7,024,500 | Two-stage classifier |
| `$x4()` | 7,031,120 | twoStageClassifier flag reader |
| `CN()` | 11,567,782 | API call wrapper |
| `pU()` | 11,539,575 | cache_control factory |

### Version comparison

| Aspect | v2.1.85 | v2.1.88 |
|---|---|---|
| Classifier model | Hardcoded `"claude-sonnet-4-6"` | Dynamic: Max → Opus, others → Sonnet |
| Max user classifier cost | Sonnet-level | **Opus-level (~5× increase)** |
| Two-stage classifier | Not present | Added, Statsig-gated |
| Allowlist fast path | Not present | Added for read-only tools |
| alwaysAllowRules bypass | Unconfirmed | Confirmed working |
| Prompt caching | Unconfirmed | Confirmed (ephemeral, 3 breakpoints) |
