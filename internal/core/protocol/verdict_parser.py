from __future__ import annotations

from internal.core.tasks.task_types import VerificationEvidence, VerificationResult


def parse_verification_verdict(text: str, task_id: str = "") -> VerificationResult:
    verdict = None
    if "VERDICT: PASS" in text:
        verdict = "PASS"
    elif "VERDICT: FAIL" in text:
        verdict = "FAIL"
    elif "VERDICT: PARTIAL" in text:
        verdict = "PARTIAL"

    if not verdict:
        raise ValueError("Verification output missing VERDICT")

    evidence: list[VerificationEvidence] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("$ "):
            evidence.append(VerificationEvidence(command=stripped[2:], output="", result="PASS"))

    summary = text.strip().splitlines()[0] if text.strip() else ""
    return VerificationResult(
        taskId=task_id,
        verdict=verdict,
        summary=summary,
        evidence=evidence,
        missingRequirements=[],
        suspectedProblems=[],
    )
