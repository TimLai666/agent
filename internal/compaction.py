from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Awaitable, Callable, Literal

from pydantic_ai.messages import ModelRequest, ModelResponse, UserPromptPart

Role = Literal["system", "user", "assistant", "tool"]
CompactMode = Literal["base", "partial_from", "partial_up_to"]
MessageLike = ModelRequest | ModelResponse

MAX_CONTEXT_TOKENS = 128000
COMPACT_TRIGGER_RATIO = 0.75
RECENT_KEEP_COUNT = 8

NO_TOOLS_PREAMBLE = """CRITICAL: Respond with TEXT ONLY. Do NOT call any tools.

- Do NOT use Read, Bash, Grep, Glob, Edit, Write, or ANY other tool.
- You already have all the context you need in the conversation above.
- Tool calls will be REJECTED and will waste your only turn - you will fail the task.
- Your entire response must be plain text: an <analysis> block followed by a <summary> block.
"""

BASE_COMPACT_PROMPT = f"""{NO_TOOLS_PREAMBLE}

Your task is to create a detailed summary of the conversation so far, paying close attention to the user's explicit requests and your previous actions.
This summary should be thorough in capturing technical details, code patterns, and architectural decisions that would be essential for continuing development work without losing context.

Before providing your final summary, wrap your analysis in <analysis> tags to organize your thoughts and ensure you've covered all necessary points. In your analysis process:

1. Chronologically analyze each message and section of the conversation. For each section thoroughly identify:
   - The user's explicit requests and intents
   - Your approach to addressing the user's requests
   - Key decisions, technical concepts and code patterns
   - Specific details like:
     - file names
     - full code snippets
     - function signatures
     - file edits
   - Errors that you ran into and how you fixed them
   - Pay special attention to specific user feedback that you received, especially if the user told you to do something differently.
2. Double-check for technical accuracy and completeness, addressing each required element thoroughly.

Your summary should include the following sections:

1. Primary Request and Intent
2. Key Technical Concepts
3. Files and Code Sections
4. Errors and fixes
5. Problem Solving
6. All user messages
7. Pending Tasks
8. Current Work
9. Optional Next Step

Output format:

<analysis>
...
</analysis>

<summary>
...
</summary>

CRITICAL REMINDER: Do NOT call tools. Return text only.
"""

PARTIAL_COMPACT_FROM_PROMPT = f"""{NO_TOOLS_PREAMBLE}

Your task is to create a detailed summary of the RECENT portion of the conversation - the messages that follow earlier retained context. The earlier messages are being kept intact and do NOT need to be summarized.
This summary should be thorough in capturing technical details, code patterns, and architectural decisions that would be essential for continuing development work without losing context.

Before providing your final summary, wrap your analysis in <analysis> tags to organize your thoughts and ensure you've covered all necessary points. In your analysis process:

1. Analyze the recent messages chronologically. For each section thoroughly identify:
   - The user's explicit requests and intents
   - Your approach to addressing the user's requests
   - Key decisions, technical concepts and code patterns
   - Specific details like:
     - file names
     - full code snippets
     - function signatures
     - file edits
   - Errors that you ran into and how you fixed them
   - Pay special attention to specific user feedback that you received, especially if the user told you to do something differently.
2. Double-check for technical accuracy and completeness, addressing each required element thoroughly.

Your summary should include the following sections:

1. Primary Request and Intent
2. Key Technical Concepts
3. Files and Code Sections
4. Errors and fixes
5. Problem Solving
6. All user messages
7. Pending Tasks
8. Current Work
9. Optional Next Step

Output format:

<analysis>
...
</analysis>

<summary>
...
</summary>

CRITICAL REMINDER: Do NOT call tools. Return text only.
"""

PARTIAL_COMPACT_UP_TO_PROMPT = f"""{NO_TOOLS_PREAMBLE}

Your task is to summarize the EARLIER portion of the conversation up to the cutoff point. Newer messages will remain in the conversation verbatim after this summary, so your summary should focus on preserving the context needed for those later messages to make sense.

Before providing your final summary, wrap your analysis in <analysis> tags to organize your thoughts and ensure you've covered all necessary points. In your analysis process:

1. Analyze the messages chronologically up to the cutoff point.
2. Identify:
   - The user's explicit requests and intents
   - Key technical concepts, files, code patterns, and decisions
   - Errors encountered and how they were fixed
   - Important user feedback that changed direction
3. Double-check for technical accuracy and continuity with later messages.

Your summary should include the following sections:

1. Primary Request and Intent
2. Key Technical Concepts
3. Files and Code Sections
4. Errors and fixes
5. Problem Solving
6. All user messages
7. Pending Tasks
8. Work Completed
9. Context for Continuing Work

Output format:

<analysis>
...
</analysis>

<summary>
...
</summary>

CRITICAL REMINDER: Do NOT call tools. Return text only.
"""

FALLBACK_COMPACT_PROMPT = f"""{NO_TOOLS_PREAMBLE}

Summarize only what is needed to continue work accurately.
Return both <analysis> and <summary> blocks.
In <summary>, include:
1. Primary Request and Intent
2. Current Work
3. Pending Tasks
4. Key Files and Decisions
"""


@dataclass
class Message:
    id: str
    role: Role
    content: str
    tokenCount: int
    createdAt: str


@dataclass
class CompactSummary:
    version: int
    mode: CompactMode
    rawOutput: str
    formattedSummary: str
    createdAt: str


@dataclass
class ConversationState:
    fullMessages: list[MessageLike]
    compressedSummary: str | None = None
    recentMessages: list[MessageLike] | None = None
    transcriptPath: str | None = None
    totalTokens: int = 0
    lastCompactedMessageId: str | None = None


@dataclass
class CompactJob:
    jobId: str
    mode: CompactMode
    oldSummary: str
    messagesToCompress: list[Message]
    preservedRecentMessages: list[MessageLike]
    suppressFollowUpQuestions: bool


CompactionRunner = Callable[[CompactJob, str], Awaitable[str]]


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)


def should_compact(total_tokens: int) -> bool:
    return total_tokens >= int(MAX_CONTEXT_TOKENS * COMPACT_TRIGGER_RATIO)


def get_compaction_prompt(mode: CompactMode, custom_instructions: str | None = None) -> str:
    prompt_map: dict[CompactMode, str] = {
        "base": BASE_COMPACT_PROMPT,
        "partial_from": PARTIAL_COMPACT_FROM_PROMPT,
        "partial_up_to": PARTIAL_COMPACT_UP_TO_PROMPT,
    }
    prompt = prompt_map[mode]
    if custom_instructions and custom_instructions.strip():
        prompt = f"{prompt}\n\nAdditional Instructions:\n{custom_instructions.strip()}"
    return prompt


def get_message_text(message: MessageLike) -> str:
    chunks: list[str] = []
    for part in getattr(message, "parts", []) or []:
        part_kind = str(getattr(part, "part_kind", "unknown"))
        content = getattr(part, "content", None)
        if isinstance(content, str):
            value = content
        elif isinstance(content, (list, tuple)):
            values: list[str] = []
            for item in content:
                if isinstance(item, str):
                    values.append(item)
                else:
                    values.append(str(item))
            value = "\n".join(values)
        else:
            value = str(part)
        chunks.append(f"[{part_kind}] {value}".strip())
    return "\n".join(c for c in chunks if c.strip())


def infer_role(message: MessageLike) -> Role:
    if isinstance(message, ModelResponse):
        return "assistant"
    kinds = {str(getattr(p, "part_kind", "")) for p in getattr(message, "parts", []) or []}
    if "tool-return" in kinds:
        return "tool"
    if "system-prompt" in kinds:
        return "system"
    return "user"


def convert_messages(messages: list[MessageLike]) -> list[Message]:
    converted: list[Message] = []
    now = datetime.now().astimezone()
    for idx, message in enumerate(messages):
        text = get_message_text(message)
        timestamp = getattr(message, "timestamp", now)
        if hasattr(timestamp, "isoformat"):
            created = timestamp.isoformat()
        else:
            created = now.isoformat()
        converted.append(
            Message(
                id=f"msg-{idx}",
                role=infer_role(message),
                content=text,
                tokenCount=estimate_tokens(text),
                createdAt=created,
            )
        )
    return converted


def split_messages_for_compaction(
    messages: list[MessageLike],
    keep_count: int = RECENT_KEEP_COUNT,
) -> tuple[list[Message], list[MessageLike]]:
    if len(messages) <= keep_count:
        return [], list(messages)
    preserved_recent_messages = messages[-keep_count:]
    messages_to_compress = convert_messages(messages[:-keep_count])
    return messages_to_compress, preserved_recent_messages


def serialize_compaction_input(job: CompactJob) -> str:
    header = "Previous compressed summary:\n"
    old_summary = job.oldSummary.strip() or "(none)"
    body_lines = ["Messages to compress:"]
    for message in job.messagesToCompress:
        body_lines.extend(
            [
                f"- id: {message.id}",
                f"  role: {message.role}",
                f"  createdAt: {message.createdAt}",
                "  content:",
                f"{message.content}",
            ]
        )
    return f"{header}{old_summary}\n\n" + "\n".join(body_lines)


def format_compact_summary(raw_output: str) -> str:
    formatted = re.sub(r"<analysis>[\s\S]*?</analysis>", "", raw_output, count=1, flags=re.IGNORECASE)
    match = re.search(r"<summary>([\s\S]*?)</summary>", formatted, flags=re.IGNORECASE)
    if not match:
        return ""
    text = match.group(1).strip()
    if not text:
        return ""
    text = re.sub(r"\n\n+", "\n\n", text)
    return f"Summary:\n{text}".strip()


def get_compact_user_summary_message(
    *,
    summary: str,
    suppressFollowUpQuestions: bool = False,
    transcriptPath: str | None = None,
    recentMessagesPreserved: bool = False,
    proactiveMode: bool = False,
) -> str:
    message = (
        "This session is being continued from a previous conversation that ran out of context. "
        "The summary below covers the earlier portion of the conversation.\n\n"
        f"{summary}"
    )

    if transcriptPath:
        message += (
            "\n\nIf you need specific details from before compaction (like exact code snippets, "
            "error messages, or content you generated), read the full transcript at: "
            f"{transcriptPath}"
        )

    if recentMessagesPreserved:
        message += "\n\nRecent messages are preserved verbatim."

    if suppressFollowUpQuestions:
        message += (
            "\n\nContinue the conversation from where it left off without asking the user any further "
            "questions. Resume directly - do not acknowledge the summary, do not recap what was "
            "happening, do not preface with \"I'll continue\" or similar. Pick up the last task "
            "as if the break never happened."
        )

    if proactiveMode:
        message += (
            "\n\nYou are running in autonomous/proactive mode. This is NOT a first wake-up - "
            "you were already working autonomously before compaction. Continue your work loop: "
            "pick up where you left off based on the summary above. Do not greet the user or ask "
            "what to work on."
        )

    return message


def recalc_total_tokens(messages: list[MessageLike]) -> int:
    return sum(estimate_tokens(get_message_text(message)) for message in messages)


class CompactCoordinator:
    def __init__(
        self,
        *,
        runner: CompactionRunner,
        recent_keep_count: int = RECENT_KEEP_COUNT,
    ) -> None:
        self._runner = runner
        self._recent_keep_count = recent_keep_count

    async def runCompact(self, job: CompactJob) -> CompactSummary:
        attempts = [
            get_compaction_prompt(job.mode),
            get_compaction_prompt(job.mode),
            FALLBACK_COMPACT_PROMPT,
        ]

        for prompt in attempts:
            raw_output = await self._runner(job, prompt)
            formatted = format_compact_summary(raw_output)
            if formatted:
                return CompactSummary(
                    version=1,
                    mode=job.mode,
                    rawOutput=raw_output,
                    formattedSummary=formatted,
                    createdAt=datetime.now().astimezone().isoformat(),
                )

        raise RuntimeError("Compaction failed: empty formatted summary")

    def formatCompactSummary(self, rawOutput: str) -> str:
        return format_compact_summary(rawOutput)

    def buildContinuationMessage(
        self,
        args: dict[str, Any],
    ) -> str:
        return get_compact_user_summary_message(**args)

    async def maybeCompact(self, state: ConversationState) -> ConversationState:
        if not should_compact(state.totalTokens):
            state.recentMessages = list(state.fullMessages[-self._recent_keep_count :])
            return state

        messages_to_compress, preserved_recent_messages = split_messages_for_compaction(
            state.fullMessages,
            keep_count=self._recent_keep_count,
        )
        if not messages_to_compress:
            state.recentMessages = preserved_recent_messages
            state.totalTokens = recalc_total_tokens(state.fullMessages)
            return state

        job = CompactJob(
            jobId=f"compact-{datetime.now().timestamp()}",
            mode="base",
            oldSummary=state.compressedSummary or "",
            messagesToCompress=messages_to_compress,
            preservedRecentMessages=preserved_recent_messages,
            suppressFollowUpQuestions=True,
        )

        summary = await self.runCompact(job)
        continuation_message = self.buildContinuationMessage(
            {
                "summary": summary.formattedSummary,
                "transcriptPath": state.transcriptPath,
                "recentMessagesPreserved": True,
                "suppressFollowUpQuestions": job.suppressFollowUpQuestions,
            }
        )

        continuation_request = ModelRequest(parts=[UserPromptPart(content=continuation_message)])
        full_messages: list[MessageLike] = [continuation_request, *preserved_recent_messages]
        return ConversationState(
            fullMessages=full_messages,
            compressedSummary=summary.formattedSummary,
            recentMessages=preserved_recent_messages,
            transcriptPath=state.transcriptPath,
            totalTokens=recalc_total_tokens(full_messages),
            lastCompactedMessageId=messages_to_compress[-1].id,
        )
