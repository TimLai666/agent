# Multi-Agent Architecture

## Overview
This system uses four agents:
- Main agent: understands user intent and responds quickly.
- Philosopher co-agent: handles complex reasoning and planning.
- Subagent: executes tasks by delegating tool usage.
- Function-call agent: owns all tools and execution MCP servers.

## Responsibilities
- Main agent talks to users and delegates execution via `delegate_to_subagent`.
- Philosopher provides multi-turn reasoning threads.
- Subagent runs tasks via `run_function_call_agent`.
- Function-call agent executes tools and MCP actions (including browser MCP).

## Code Organization
- Runtime bootstrap lives in `internal/runtime/system.py`
- Main agent lives under `internal/agents/`
- Function-call agent and subagent live under `internal/sub_agents/`
- Co-agents live under `internal/co_agents/`

## MCP and Tool Placement
- Execution MCP and tools are attached to the function-call agent.
- Query MCP servers can be attached to the main agent (optional).
- Browser MCP runs in two modes: headed and headless, exposed as:
  - `browser_headed_*`
  - `browser_headless_*`

## Configuration
Each agent supports its own model config via env vars:
- `MAIN_*`, `CO_*`, `PHILOSOPHER_*`, `SUB_*`, `FUNCTION_CALL_*`
  - `*_OPENAI_BASE_URL`
  - `*_OPENAI_API_KEY`
  - `*_MODEL_NAME`
  - `*_MODEL_TEMPERATURE`

Inheritance behavior:
- Main agent falls back to base values.
- Philosopher co-agent falls back to `MAIN_*`, then base.
- Subagent falls back to `MAIN_*`, then base.
- Function-call agent falls back to `SUB_*`, then `MAIN_*`, then base.

Base defaults are read from:
- `OPENAI_BASE_URL`, `OPENAI_API_KEY`, `MODEL_NAME`, `MODEL_TEMPERATURE`

## Prompts
Prompts are loaded from `prompts/` where the filename (uppercase) is the key.
System prompt lives in `prompts/SYSTEM_PROMPT.md`.
Each agent class declares its own prompt key and loads instructions internally.
