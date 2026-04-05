# Cache Invalidation Verification — Why MCP Tool Discovery Doesn't Actually Bust the Prompt Cache

> **CLI Version:** @anthropic-ai/claude-code v2.1.85 (build 2026-03-26)
> **Date:** 2026-03-28
> **Status:** Verified (source code + official docs + live experiment)

---

## Summary

We set out to verify a seemingly obvious claim: when Claude Code's deferred tool loading system discovers a new MCP tool via ToolSearch, the tools array changes, the cache prefix shifts, and the entire prompt cache is rebuilt at 125% cost. The embedded documentation inside cli.js itself says so — "adding, removing, or reordering a tool invalidates the entire cache."

We ran a live experiment at 283k context tokens and watched /cost. Nothing moved.

This report traces the complete investigation: reverse-engineering CLI v2.1.85, searching 15+ GitHub issues, and reading Anthropic's official API documentation. The answer is that `defer_loading` is not just a flag that delays tool schema delivery — it fundamentally changes how the server treats tool definitions in the cache prefix. Deferred tools are excluded from the prefix entirely. The cache stays intact.

Non-deferred tools still bust cache exactly as documented. The system prompt cache strategy itself shifts depending on whether non-deferred MCP tools exist. And there are at least six other operations that trigger full cache rebuilds. This report maps all of them.

---

## Table of Contents

1. [The Prediction and the Contradiction](#1-the-prediction-and-the-contradiction)
2. [How Prompt Caching Actually Works](#2-how-prompt-caching-actually-works)
3. [The Complete Cache Breakpoint Map](#3-the-complete-cache-breakpoint-map)
4. [Three Cache Strategies Inside Z57](#4-three-cache-strategies-inside-z57)
5. [The Deferred Tool Loading Pipeline](#5-the-deferred-tool-loading-pipeline)
6. [Why Deferred Tools Don't Bust Cache — The Full Evidence Chain](#6-why-deferred-tools-dont-bust-cache--the-full-evidence-chain)
7. [What Actually Does Bust Cache — A Practical Scenario Guide](#7-what-actually-does-bust-cache--a-practical-scenario-guide)
8. [Methodology](#8-methodology)
9. [References](#9-references)

---

## 1. The Prediction and the Contradiction

### The reasoning chain

Our original analysis went like this:

1. Anthropic's prompt cache uses **strict prefix matching**. The server computes a cache key from the byte-for-byte content of the request, in render order: `tools → system → messages`.
2. Claude Code's deferred tool loading system starts with MCP tools **excluded** from the tools array. When ToolSearch discovers a tool, it gets **added** to the array on the next turn.
3. Adding a tool changes the tools array. Since tools render at position 0, everything after them — system prompt, all messages — becomes a prefix mismatch.
4. A prefix mismatch forces a full cache rewrite at 125% of base input cost.

At 283k context tokens, a full rewrite would cost the equivalent of ~354k tokens at the cache write rate. This should have been clearly visible in /cost.

### The experiment

- **Setup:** Active Claude Code CLI session (Opus 4, Claude Max subscription), 283k context, 27% of 5-hour quota consumed, multiple MCP servers connected.
- **Action:** Used ToolSearch to fetch an MCP tool schema for the first time in the conversation.
- **Expected result:** /cost jumps by several percentage points (estimated 3-7%).
- **Actual result:** /cost remained at 27%. No observable change.

### The question

Where did the reasoning chain break? Was the cache bust happening but invisible? Or was the mechanism itself different from what we assumed?

---

## 2. How Prompt Caching Actually Works

Before diving into why deferred tools are special, we need to establish the baseline — how does Claude Code's cache system work in CLI v2.1.85?

### Render order

The Anthropic API processes request content in a fixed order for cache prefix computation, regardless of how the JSON keys are arranged in the request body:

```
Position 0: tools array      (all tool definitions)
Position 1: system prompt     (all system blocks)
Position 2: messages          (conversation history)
```

This is confirmed by embedded documentation inside cli.js (character offset ~12553825):

> *"Render order is: tools → system → messages. A breakpoint on the last system block caches both tools and system together."*

The JS object literal in the code orders keys as `model → messages → system → tools`, but this is irrelevant. The API server always processes them in the canonical render order above.

### How cache_control breakpoints work

A `cache_control` marker on a content block tells the server: "compute a cache key for everything from the start of the request up to and including this block." If the key matches an existing cache entry, everything before this point is read from cache (10% cost). If it doesn't match, everything is written to a new cache entry (125% cost).

The factory function that produces these markers is `XU()` (character offset ~11366730):

```js
function XU({scope, querySource} = {}) {
  return {
    type: "ephemeral",                              // always present
    ...MVY(querySource) ? {ttl: "1h"} : {},         // 1h TTL for allowlisted sources
    ...scope === "global" ? {scope: "global"} : {}   // cross-session caching
  }
}
```

Three fields, each with specific meaning:
- **`type: "ephemeral"`** — standard prompt cache marker, always present
- **`ttl: "1h"`** — extended TTL (default is 5 minutes). Enabled when the source passes a feature flag check (`MVY()`). Cache writes at 1h TTL cost 2x base price instead of 1.25x, but reads are still 10%.
- **`scope: "global"`** — allows cache entries to be shared across conversations. Only applied to static content that doesn't change between sessions.

### What gets a breakpoint and what doesn't

This is the critical detail that our original analysis missed. Not every part of the request gets a `cache_control` marker. Here's what cli.js actually does:

| Content | Gets `cache_control`? | Scope | Purpose |
|---------|----------------------|-------|---------|
| Tool definitions | **No** (by default) | — | Tools are cached implicitly as part of the prefix before the system breakpoint |
| System prompt static zone | **Yes** | `"org"` or `"global"` | Caches tools + system together |
| System prompt dynamic zone | **No** | — | Changes frequently (date, git status), left uncached |
| Last 1-2 messages | **Yes** | per-query | Sliding window that moves forward each turn |

The tool definitions have **no** `cache_control` of their own. The function `vm8()` that converts tools to API format only adds `cache_control` if explicitly passed a `cacheControl` parameter — and the main query function `vuK()` never passes one:

```js
// vm8() — tool schema builder
async function vm8(tool, options) {
  let schema = {
    name: tool.name,
    description: await tool.prompt(...),
    input_schema: tool.inputSchema
  };
  if (options.deferLoading) schema.defer_loading = true;
  if (options.cacheControl) schema.cache_control = options.cacheControl;  // never called in practice
  return schema;
}
```

This means tools are cached **only because they come before the system prompt breakpoint**. The system prompt's `cache_control` marker creates a breakpoint that covers everything before it — including all tools. There is no independent tool-level cache.

---

## 3. The Complete Cache Breakpoint Map

Here is every location in a CLI v2.1.85 API request that receives a `cache_control` marker:

### System prompt breakpoints (via `yVY()` → `Z57()`)

The system prompt is split into blocks and processed by `Z57()`, which assigns a `cacheScope` to each block. Then `yVY()` converts those into actual `cache_control` markers:

```js
// yVY() — system prompt formatter
function yVY(blocks, cachingEnabled, options) {
  return Z57(blocks, options).map(block => ({
    type: "text",
    text: block.text,
    // Only add cache_control if caching is enabled AND scope is not null
    ...cachingEnabled && block.cacheScope !== null
      ? {cache_control: XU({scope: block.cacheScope, querySource: options?.querySource})}
      : {}
  }));
}
```

Blocks with `cacheScope: null` get **no** cache marker — they're in the "dynamic zone" that changes between turns.

### Message breakpoints (via `kVY()` → `WVY()` / `ZVY()`)

```js
// kVY() — message array processor
function kVY(messages, cachingEnabled, querySource, cacheEditing, ..., skipCacheWrite) {
  // Target index: last message, or second-to-last if skipCacheWrite
  let targetIndex = skipCacheWrite ? messages.length - 2 : messages.length - 1;

  return messages.map((msg, index) => {
    let isTarget = index === targetIndex;
    if (msg.type === "user") return WVY(msg, isTarget, cachingEnabled, querySource);
    return ZVY(msg, isTarget, cachingEnabled, querySource);
  });
}
```

Only the last (or second-to-last) message gets a breakpoint, and only on its final content block. This creates a sliding window — each new turn shifts the breakpoint forward, and the server reads everything before it from cache.

### Auto-mode classifier breakpoints

The auto-mode classifier (which decides whether to use agent mode) has its own independent cache markers:
- CLAUDE.md config block → `cache_control` with `querySource: "auto_mode"`
- Classifier system prompt → `cache_control` with `querySource: "auto_mode"`
- Last transcript action → `cache_control` with `querySource: "auto_mode"`

These don't interact with the main conversation cache.

### Visual summary

```
┌─────────────────────────────────────────────────┐
│ API Request (render order)                       │
│                                                  │
│  ┌─ tools ───────────────────────────────────┐  │
│  │  Built-in tools (Read, Write, Bash, ...)  │  │
│  │  MCP tools with defer_loading: true       │  │  ← no cache_control on any tool
│  │  Extra tool schemas                       │  │
│  └───────────────────────────────────────────┘  │
│                                                  │
│  ┌─ system prompt ───────────────────────────┐  │
│  │  [billing header]         scope: null     │  │  ← no cache
│  │  [org/version block]      scope: "org"    │  │  ← cache_control: ephemeral
│  │  [static instructions]    scope: "org"    │──│──── BREAKPOINT: caches tools + system
│  │  [dynamic content]        scope: null     │  │  ← no cache (date, git status, etc.)
│  └───────────────────────────────────────────┘  │
│                                                  │
│  ┌─ messages ────────────────────────────────┐  │
│  │  [message 1]                              │  │
│  │  [message 2]                              │  │
│  │  ...                                      │  │
│  │  [last message - final content block]     │──│──── BREAKPOINT: caches all prior messages
│  └───────────────────────────────────────────┘  │
│                                                  │
└─────────────────────────────────────────────────┘
```

---

## 4. Three Cache Strategies Inside Z57

The `Z57()` function is the decision engine for system prompt caching. It has three distinct branches, and which one executes depends on two conditions: whether global caching is enabled, and whether non-deferred MCP tools exist.

### Branch 1: Standard mode (no global cache)

**Condition:** Global cache feature flag is off.

```
billing header    → cacheScope: null    (not cached)
org-scope blocks  → cacheScope: "org"   (cached at org level)
remaining content → cacheScope: "org"   (cached at org level, joined into one block)
```

This is the simplest path. System prompt blocks get `ephemeral` cache markers. The system breakpoint caches everything before it, including all tools.

### Branch 2: Global cache with boundary marker

**Condition:** Global cache is on, no non-deferred MCP tools, and the dynamic boundary marker `__SYSTEM_PROMPT_DYNAMIC_BOUNDARY__` exists in the prompt.

```
static blocks (before boundary)  → cacheScope: "global"   (cross-session cache)
dynamic blocks (after boundary)  → cacheScope: null        (not cached)
```

The `scope: "global"` marker tells the server this content is identical across conversations — cache it once and share it. This is the most efficient mode but requires stable content.

### Branch 3: Tool-based cache mode

**Condition:** Global cache is on, AND at least one **non-deferred** MCP tool exists in the active tool set.

This branch has the most confusing name. "Tool-based cache" doesn't mean tools get their own `cache_control`. It means the **system prompt gives up its global cache scope** because the presence of non-deferred MCP tools makes the tools-to-system prefix unstable.

Here's the actual code logic:

```js
// In vuK() — the main query function:

// W = is global cache enabled?
let W = isGlobalCacheEnabled() && (forceGlobalCache || featureFlag("tengu_system_prompt_global_cache"));

// Z = is this tool deferred?
let Z = (tool) => toolSearchEnabled && (isDeferredTool(tool) || isLspConnecting(tool));

// G = are there any non-deferred MCP tools?
let G = W && activeTools.some(tool => tool.isMcp === true && !Z(tool));

// G controls the cache strategy:
let globalCacheStrategy = W ? (G ? "none" : "system_prompt") : "none";

// G is passed to yVY as skipGlobalCacheForSystemPrompt
let systemBlocks = yVY(prompt, cachingEnabled, {skipGlobalCacheForSystemPrompt: G, ...});
```

When `G` is true (non-deferred MCP tools exist):

```
billing header    → cacheScope: null    (not cached)
org-scope blocks  → cacheScope: "org"   (downgraded from "global" to "org")
remaining content → cacheScope: "org"   (downgraded)
```

The telemetry event `tengu_sysprompt_using_tool_based_cache` fires to record this downgrade.

**Why does this happen?** Non-deferred MCP tools have full schemas in the tools array. If an MCP server restarts with different tool descriptions, the tools prefix changes, invalidating any `scope: "global"` cache entry. By downgrading to `"org"` scope, the system avoids sharing a potentially unstable cache across conversations.

**The key insight for deferred tools:** Deferred tools have `Z(tool) = true`, so `!Z(tool) = false`. They **never** trigger `G`. When all MCP tools are deferred (which is the normal case with ToolSearch enabled), `G` stays false, and the system prompt retains its `"global"` or `"org"` cache scope. Deferred tools don't affect this calculation at all.

---

## 5. The Deferred Tool Loading Pipeline

Understanding why deferred tools don't bust cache requires understanding the full pipeline from "tool registered" to "tool in API request."

### Step 1: All MCP tools start as deferred

The function `isDeferredTool()` (internally `I0()`, offset ~5318984) has a simple first check:

```js
function isDeferredTool(tool) {
  if (tool.isMcp === true) return true;   // ALL MCP tools are deferred
  if (tool.name === "ToolSearch") return false;
  // ... other checks for feature flags
  return tool.shouldDefer === true;
}
```

Every MCP tool, regardless of configuration, returns `true`. This is not configurable from the user side.

### Step 2: Tool Search mode decides what enters the tools array

The function `Ir6()` determines the tool loading mode:

| Mode | Condition | Behavior |
|------|-----------|----------|
| `"tst"` (tool search) | `ENABLE_TOOL_SEARCH=true` or `=0` | ToolSearch active, deferred tools filtered |
| `"tst-auto"` | Deferred tool tokens exceed context threshold | Auto-activates tool search |
| `"standard"` | None of the above | All tools sent, ToolSearch excluded |

When tool search mode is active (`J = true`), the tools array is filtered:

```js
// X = tools that actually get sent to the API
X = allTools.filter(tool => {
  if (!isDeferredTool(tool)) return true;     // non-deferred: always included
  if (tool.name === "ToolSearch") return true; // ToolSearch itself: always included
  return discoveredTools.has(tool.name);       // deferred: only if previously discovered
});
```

Undiscovered deferred tools are **completely absent** from the API request.

### Step 3: Discovery scanner finds tool_reference blocks

Before each API call, the scanner function `wU()` walks the entire message history looking for `tool_reference` blocks — these are created when ToolSearch returns results:

```js
function extractDiscoveredToolNames(messages) {
  let discovered = new Set();
  for (let msg of messages) {
    if (msg.role !== "user") continue;
    for (let block of msg.content) {
      if (block.type === "tool_result") {
        for (let inner of block.content) {
          if (inner.type === "tool_reference") {
            discovered.add(inner.tool_name);
          }
        }
      }
    }
  }
  // Also recover from compaction metadata
  // ...
  return discovered;
}
```

### Step 4: Discovered tools enter the array with defer_loading: true

When a tool is discovered, it passes the `X` filter and gets sent to the API. But it **still** has `defer_loading: true`:

```js
// Z = should this tool be marked as deferred?
let Z = (tool) => toolSearchEnabled && (isDeferredTool(tool) || isLspConnecting(tool));

// In vm8():
if (options.deferLoading) schema.defer_loading = true;
// deferLoading = Z(tool) — true for all MCP tools, even discovered ones
```

The tool enters the API request with its full schema (name, description, input_schema) **plus** the `defer_loading: true` flag. This flag is the key signal to the server.

### Step 5: Server-side expansion via tool_reference

The `tool_reference` blocks in the message history tell the server where to make the tool available. From Anthropic's documentation:

> "Tool Search Tool doesn't break prompt caching because deferred tools are excluded from the initial prompt entirely. They're only added to context after Claude searches for them, so your system prompt and core tool definitions remain cacheable."

The server expands `tool_reference` blocks inline within the message history, not by modifying the tools prefix. The prefix — which determines cache key matching — remains stable.

### Timeline view

```
Turn 1 (before discovery):
  tools: [Bash, Read, Write, ..., ToolSearch]
  system: [...cache_control breakpoint here...]
  messages: [user: "do something"]
  → Cache: tools+system cached together ✓

Turn 2 (ToolSearch called):
  tools: [Bash, Read, Write, ..., ToolSearch]          ← unchanged
  system: [same...]
  messages: [..., assistant: calls ToolSearch, user: tool_result with tool_reference]
  → Cache: tools+system HIT ✓, messages extended

Turn 3 (after discovery):
  tools: [Bash, Read, Write, ..., ToolSearch, mcp__server__tool(defer_loading:true)]
  system: [same...]
  messages: [...]
  → Client-side tools array changed, BUT server ignores defer_loading tools in prefix
  → Cache: tools+system HIT ✓ (server excludes deferred tools from prefix)
```

---

## 6. Why Deferred Tools Don't Bust Cache — The Full Evidence Chain

Our original prediction was wrong. Here is the complete evidence chain for why:

### Evidence 1: API design constraint — defer_loading XOR cache_control

The Anthropic API explicitly rejects requests where a tool has both `defer_loading: true` and a `cache_control` marker. From [GitHub Issue #30920](https://github.com/anthropics/claude-code/issues/30920):

```
API Error 400:
"Tool 'mcp__atlassian__getConfluencePage' cannot have both defer_loading=true
and cache_control set. Tools with defer_loading cannot use prompt caching."
```

This is not a bug — it's an intentional design constraint. If deferred tools participated in the cache prefix, they would need `cache_control` markers to define breakpoints. The API forbids this combination because **deferred tools are architecturally excluded from the prefix**.

**Evidence strength: Confirmed** (API behavior, reproducible error message)

### Evidence 2: Official documentation

Anthropic's Tool Search Tool documentation states:

> "Tool Search Tool doesn't break prompt caching because deferred tools are excluded from the initial prompt entirely. They're only added to context after Claude searches for them, so your system prompt and core tool definitions remain cacheable."

**Evidence strength: Confirmed** (official documentation)

### Evidence 3: Source code — deferred tools don't trigger cache strategy downgrade

The `skipGlobalCacheForSystemPrompt` flag, which downgrades system prompt caching, is calculated as:

```js
let G = globalCacheEnabled && activeTools.some(tool => tool.isMcp === true && !isDeferred(tool));
```

Deferred tools (`isDeferred = true`) produce `!isDeferred = false`, so they're excluded from this check. Even when a deferred tool is discovered and added to the tools array, it remains deferred (`isDeferredTool()` returns true for all MCP tools unconditionally). The system prompt cache strategy is never affected.

**Evidence strength: Confirmed** (source code, CLI v2.1.85)

### Evidence 4: Live experiment

At 283k context tokens, we used ToolSearch to discover an MCP tool and continued the conversation. The /cost indicator showed no change (remained at 27% of 5-hour quota).

A full cache rebuild at this context size would have cost approximately:
- Cache write: ~283k × 1.25 = ~354k token-equivalents
- At Opus 4 rates ($15/MTok input): ~$5.31 per bust
- As percentage of a ~1M token 5-hour budget: ~3-7%

The absence of any /cost change is consistent with the cache remaining intact.

**Evidence strength: Supporting** (consistent with hypothesis, but /cost precision could mask small changes)

### Evidence 5: Bug history confirms the constraint is enforced

CLI v2.1.69 had a bug where it accidentally set both `defer_loading` and `cache_control` on MCP tools. The result was not a cache bust — it was a **hard API error** that broke all MCP tool calls entirely ([Issue #30989](https://github.com/anthropics/claude-code/issues/30989)). The API doesn't silently handle this case; it rejects the request outright. This confirms that the server treats deferred tools as fundamentally incompatible with cache participation.

**Evidence strength: Confirmed** (reproducible regression in v2.1.69)

### Evidence 6: Design intent

The entire deferred tool loading system exists to reduce token cost. Issue [#124 in the Agent SDK repo](https://github.com/anthropics/claude-agent-sdk-typescript/issues/124) documents that a typical multi-server MCP setup consumes 15,000-20,000 tokens in tool definitions. Deferred loading reduces this by 85%+. If discovering a deferred tool triggered a full cache rebuild (125% of the entire context), the cost savings would be negated on first use — defeating the system's purpose.

**Evidence strength: Reasoning** (design intent, not direct proof)

### Conclusion: Where the original reasoning broke

The reasoning chain broke at step 3:

> ~~3. Adding a tool changes the tools array. Since tools render at position 0, everything after them becomes a prefix mismatch.~~

**Corrected:** Adding a **non-deferred** tool changes the cache prefix. Adding a **deferred** tool (one with `defer_loading: true`) does not, because the server excludes deferred tools from the prefix calculation. The `defer_loading` flag is the server-side signal that separates these two cases.

The embedded documentation that says "adding a tool invalidates the entire cache" is correct for the general case — it describes what happens when you add a regular tool definition. It does not account for the `defer_loading` mechanism, which was introduced later as part of the `advanced-tool-use-2025-11-20` beta.

---

## 7. What Actually Does Bust Cache — A Practical Scenario Guide

The prompt cache is a stack of three layers: tools at the bottom, system prompt in the middle, messages on top. When a layer changes, everything above it gets rewritten. A change in the tools layer is the worst case — it forces the entire stack to rebuild. A change in the system prompt is slightly better — tools stay cached but everything else rebuilds. A change in messages is the mildest — just the new content gets written.

Here's every common scenario, organized by how much damage it does.

### The expensive ones: your entire conversation gets rewritten

These change the tools layer (position 0 in the cache), so every token in the request — tools, system prompt, and all messages — gets treated as new content and written to cache at the elevated write rate.

**When does this happen?**

- **You switch models mid-conversation.** The cache key includes the model name. Switch from Sonnet to Opus, and the server sees an entirely new request.

- **An MCP server restarts and its tool descriptions change.** Each tool's schema is serialized byte-for-byte. If your MCP server includes a timestamp, a record count, or anything dynamic in its tool descriptions, the schema changes between turns. One byte is enough.

- **You toggle `CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS`.** This strips non-standard fields (like `defer_loading`, `eager_input_streaming`) from tool schemas. The serialized bytes change, prefix invalidated.

- **The CLI switches from "standard" to "tool-search" mode (or vice versa).** This restructures the entire tools array — ToolSearch gets added, deferred tools get removed or included differently.

**How much does it cost?** At 200k context with 1h TTL: the server writes ~200k tokens at $2.00/MTok ($0.40) instead of reading them at $0.10/MTok ($0.02). You pay an extra **~$0.38 per occurrence**. At 500k context: **~$0.95 per occurrence**.

### The moderate ones: system prompt and messages rewrite, tools survive

These change the system prompt (position 1), so the tools layer stays cached, but system + all messages get rewritten.

**When does this happen?**

- **The date rolls over.** The system prompt includes `currentDate`. At midnight, this string changes, and the dynamic zone of the system prompt no longer matches. If you're working across midnight, you eat one rebuild.

- **You edit CLAUDE.md during a conversation.** CLAUDE.md content is part of the system prompt. Every save triggers a rebuild. If your editor auto-saves frequently, this adds up.

- **Git status changes between turns.** The system prompt's dynamic zone includes a snapshot of your repo's git status. Run `git commit` between two Claude turns and the status string changes.

- **A non-deferred MCP tool appears for the first time.** This triggers the system prompt cache strategy to downgrade from `"global"` scope to `"org"` scope. The scope change means the old cache entry no longer matches, so a new one gets written.

**How much does it cost?** Slightly less than a full rebuild since tools remain cached. At 200k context where tools account for ~15k tokens: you save ~15k tokens of write cost compared to a full rebuild. In practice, **~$0.35 per occurrence** at 200k context.

### The cheap ones: just new messages get written

This is normal operation. Every time you send a message and Claude responds, the new content gets written to cache. The sliding window breakpoint moves forward, and everything before it is read from cache.

- **Normal conversation turns** — each turn adds new message content. Only the new part is a write. Everything before it is a read. This is the baseline cost of having a conversation.

- **Tool outputs (Read, Bash, etc.)** — the output lands in the messages layer. Large outputs (e.g., reading a 5000-line file) mean more write tokens for that turn, but nothing gets invalidated.

**How much does it cost?** Proportional to the new content. A typical turn with a few hundred tokens of user input + a few thousand tokens of Claude output: negligible.

### The big ones: entire context rebuilt from scratch

These are rare but the most expensive when they happen.

- **Context compaction (auto-compact).** When the conversation exceeds the context limit, Claude Code summarizes older messages. The summarized content replaces the originals, which changes the messages layer entirely. Worse: if compaction changes the message that had the cache breakpoint, it can trigger a chain reaction where the system prompt's breakpoint also needs rebuilding.

- **Session resume (close and reopen).** The entire request is reconstructed from persisted state. There's no warm cache to hit — everything is a write on the first turn back.

- **Idle timeout (cache TTL expires).** If you don't send a message for 5 minutes (standard) or 1 hour (extended TTL), the server evicts your cache entry. Your next message pays the full write cost.

**How much does it cost?** Same as a full rebuild — the entire context is written at the elevated rate. At 200k context with 1h TTL: **~$0.38**. But the real danger with compaction is that it can happen repeatedly if the conversation stays near the context limit, compounding the cost.

### The free ones: no cache impact at all

These are safe. Do them as much as you want.

- **Discovering an MCP tool via ToolSearch.** The core finding of this report. Deferred tools are excluded from the server's prefix calculation. Discover 10 MCP tools in a row — zero cache impact.

- **Using the Skill tool (/slash commands).** Skill content is appended to the messages layer at the current turn position. It doesn't modify tools or system prompt. Prior cache entries are untouched.

- **Reading files, running commands, writing code.** All tool outputs go into the messages layer. The sliding window handles them normally.

- **Multiple ToolSearch calls in sequence.** Each one adds a `defer_loading` tool to the client-side array, but the server ignores them all in prefix calculation.

### Quick reference card

| What you're doing | Cache impact | Extra cost per occurrence (200k context, 1h TTL) |
|-------------------|-------------|--------------------------------------------------|
| Normal conversation | None (baseline) | — |
| Using ToolSearch to load MCP tools | None | $0 |
| Using Skills (/slash commands) | None | $0 |
| Reading files, running Bash | None (just new content) | — |
| Date rollover (midnight) | System + messages rebuild | ~$0.35 |
| Editing CLAUDE.md | System + messages rebuild | ~$0.35 |
| Git operations between turns | System + messages rebuild | ~$0.35 |
| Switching models | Full rebuild | ~$0.38 |
| MCP server restart (descriptions changed) | Full rebuild | ~$0.38 |
| Idle > 5min (or >1h with extended TTL) | Full rebuild on next turn | ~$0.38 |
| Session close + resume | Full rebuild | ~$0.38 |
| Auto-compact triggered | Full rebuild + chain risk | ~$0.38+ |

For API billing users, these costs are direct charges. For Claude Max subscribers, they translate to faster consumption of your 5-hour rolling quota — the percentage impact depends on your total budget, but the relative proportions are the same.

---

## 8. Methodology

### Tools used

- **CLI v2.1.85** installed via `npm install @anthropic-ai/claude-code@2.1.85` to `/tmp/cc-research/`
- **grep/read** on the 12.9MB minified cli.js for pattern matching
- **GitHub issue search** across anthropics/claude-code and anthropics/claude-agent-sdk-typescript
- **Anthropic API documentation** (docs.anthropic.com)
- **Live experiment** in an active Claude Code CLI session

### Reverse engineering approach

CLI v2.1.85's cli.js is a single 12.9MB minified JavaScript file. Function names are mangled (e.g., `XU`, `Z57`, `vm8`, `vuK`, `I0`, `wU`, `kVY`), but string literals — telemetry event names, error messages, embedded documentation — are preserved in cleartext. We used these as anchors to locate and trace the relevant code paths.

Key anchors:
- `"cache_control"` → breakpoint placement logic
- `"tengu_sysprompt_using_tool_based_cache"` → tool-based cache strategy
- `"skipGlobalCacheForSystemPrompt"` → strategy switching condition
- `"defer_loading"` → deferred tool handling
- `"tool_reference"` → discovery scanner
- `"Render order is: tools"` → embedded documentation

### Verification

Every claim in this report falls into one of three categories:

- **Confirmed (source code):** Directly verified in cli.js v2.1.85. Minified function names are cited for reproducibility.
- **Confirmed (external):** Verified through official Anthropic documentation or reproducible GitHub issue reports.
- **Reasoning:** Logical inference from confirmed facts. Explicitly marked where used.

---

## 9. References

### GitHub Issues

| Issue | Topic | Relevance |
|-------|-------|-----------|
| [anthropics/claude-code#30920](https://github.com/anthropics/claude-code/issues/30920) | defer_loading + cache_control mutual exclusion error | Proves API rejects both flags |
| [anthropics/claude-code#30989](https://github.com/anthropics/claude-code/issues/30989) | v2.1.69 regression: all MCP calls broken | Confirms constraint is enforced at runtime |
| [anthropics/claude-code#31002](https://github.com/anthropics/claude-code/issues/31002) | Built-in tools deferred behind ToolSearch | Documents 93% token reduction |
| [anthropics/claude-code#14963](https://github.com/anthropics/claude-code/issues/14963) | Dynamic variables before static tools | Cache inefficiency from prompt ordering |
| [anthropics/claude-code#29230](https://github.com/anthropics/claude-code/issues/29230) | Stale cache after compaction | Cache invalidation gap on context compaction |
| [anthropics/claude-code#27048](https://github.com/anthropics/claude-code/issues/27048) | Cache invalidation on session resume | Tool-use content fails to cache on resume |
| [anthropics/claude-code#12836](https://github.com/anthropics/claude-code/issues/12836) | Tool Search token reduction | Confirms global caching works with ToolSearch |
| [anthropics/claude-agent-sdk-typescript#124](https://github.com/anthropics/claude-agent-sdk-typescript/issues/124) | SDK defer_loading support request | Documents 85% token reduction with deferral |
| [anthropics/claude-agent-sdk-typescript#89](https://github.com/anthropics/claude-agent-sdk-typescript/issues/89) | SDK cache control | Cache efficiency from 49.7% to 91-98% with fix |
| [anthropics/claude-agent-sdk-typescript#188](https://github.com/anthropics/claude-agent-sdk-typescript/issues/188) | SDK default TTL changed to 1h | Undocumented 60% increase in cache write cost |

### Official Documentation

- Anthropic Prompt Caching Guide — cache prefix computation rules
- Anthropic Tool Search Tool Documentation — "deferred tools are excluded from the initial prompt entirely"
- Anthropic Advanced Tool Use Blog — Tool Search, defer_loading, programmatic tool calling

### Source Code References (CLI v2.1.85)

| Function | Mangled name | Purpose |
|----------|-------------|---------|
| Cache control factory | `XU()` | Produces `{type: "ephemeral", ttl?, scope?}` |
| System prompt strategy | `Z57()` | Three-branch cache strategy selection |
| System prompt formatter | `yVY()` | Applies cache_control to system blocks |
| Tool schema builder | `vm8()` | Converts tools to API format, adds defer_loading |
| Message breakpoint processor | `kVY()` | Sliding window cache breakpoints on messages |
| Main query function | `vuK()` | Orchestrates the entire API request |
| Is-deferred check | `I0()` | Returns true for all MCP tools |
| Discovery scanner | `wU()` | Scans message history for tool_reference blocks |
| Tool search mode check | `Ir6()` | Determines tst/tst-auto/standard mode |
