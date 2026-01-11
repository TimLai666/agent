"""Skills loader for Claude Code compatible skills.

Skills are folders containing SKILL.md files with YAML frontmatter and instructions.
This module provides functionality to load and manage skills.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Optional

from internal.logger import logger


SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"


@dataclass(frozen=True)
class SkillSpec:
    """Specification for a loaded skill."""

    name: str
    description: str
    content: str
    path: Path

    def short_description(self) -> str:
        """Get the first line of description."""
        if not self.description:
            return ""
        if "\\n" in self.description:
            return self.description.split("\\n", 1)[0].strip()
        if "\n" in self.description:
            return self.description.split("\n", 1)[0].strip()
        return self.description.strip()


class SkillRegistry:
    """Registry for managing loaded skills."""

    def __init__(self, skills: dict[str, SkillSpec]) -> None:
        self._skills = skills

    def is_empty(self) -> bool:
        return not self._skills

    def list_specs(self) -> list[SkillSpec]:
        return sorted(self._skills.values(), key=lambda spec: spec.name)

    def list_names(self) -> list[str]:
        return [spec.name for spec in self.list_specs()]

    def list_summaries(self) -> list[dict[str, str]]:
        return [
            {"name": spec.name, "description": spec.short_description()}
            for spec in self.list_specs()
        ]

    def get_skill(self, name: str) -> Optional[SkillSpec]:
        """Get a skill by name (normalized)."""
        key = _normalize_name(name)
        return self._skills.get(key)

    def find_relevant_skills(
        self,
        prompt: str,
        max_skills: int = 3,
        min_score: float = 0.1
    ) -> list[SkillSpec]:
        """Find skills relevant to the given prompt based on description matching.

        This is a simple keyword-based approach. More sophisticated matching
        could use embeddings or LLM-based relevance scoring.

        Args:
            prompt: User's input prompt
            max_skills: Maximum number of skills to return
            min_score: Minimum relevance score (0-1) to include a skill

        Returns:
            List of relevant skills sorted by relevance score
        """
        if not prompt or not self._skills:
            return []

        prompt_lower = prompt.lower()
        scored_skills: list[tuple[float, SkillSpec]] = []

        for skill in self._skills.values():
            score = 0.0
            desc_lower = skill.description.lower()

            # Extract meaningful words (excluding common stop words)
            stop_words = {
                'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at',
                'to', 'for', 'of', 'with', 'by', 'from', 'as', 'is', 'are',
                'was', 'were', 'be', 'been', 'being', 'have', 'has', 'had',
                'do', 'does', 'did', 'will', 'would', 'should', 'could',
                'this', 'that', 'these', 'those', 'it', 'its', 'when', 'use'
            }

            desc_words = {w for w in re.findall(r'\w+', desc_lower) if w not in stop_words}
            prompt_words = {w for w in re.findall(r'\w+', prompt_lower) if w not in stop_words}

            if not desc_words or not prompt_words:
                continue

            # Calculate Jaccard similarity
            common_words = desc_words & prompt_words
            if common_words:
                # Weighted scoring: give more weight to rare/specific words
                score = len(common_words) / len(desc_words | prompt_words)

                # Boost score if key skill-specific words match
                key_words = {'code', 'review', 'debug', 'bug', 'error', 'skill', 'help'}
                key_matches = common_words & key_words
                if key_matches:
                    score *= (1 + len(key_matches) * 0.2)

            if score >= min_score:
                scored_skills.append((score, skill))

        # Sort by score descending
        scored_skills.sort(key=lambda x: x[0], reverse=True)
        return [skill for _, skill in scored_skills[:max_skills]]

    def build_skills_context(self, skills: list[SkillSpec]) -> str:
        """Build context string from selected skills."""
        if not skills:
            return ""

        parts = ["# Active Skills\n"]
        for skill in skills:
            parts.append(f"## {skill.name}\n")
            parts.append(f"{skill.content}\n")

        return "\n".join(parts)


def load_skill_registry(root_dir: Optional[Path] = None) -> SkillRegistry:
    """Load all skills from the skills directory."""
    skills_root = root_dir or SKILLS_DIR

    if not skills_root.exists():
        logger.info("Skills directory not found: %s", skills_root)
        return SkillRegistry({})

    specs = load_skill_specs(skills_root)

    skill_map: dict[str, SkillSpec] = {}
    for spec in specs:
        key = _normalize_name(spec.name)
        if key in skill_map:
            logger.warning(
                "Duplicate skill name '%s' from %s; skipping",
                spec.name,
                spec.path,
            )
            continue
        skill_map[key] = spec

    logger.info("Loaded %d skills from %s", len(skill_map), skills_root)
    return SkillRegistry(skill_map)


def load_skill_specs(root_dir: Path) -> list[SkillSpec]:
    """Load all SKILL.md files from the root directory."""
    if not root_dir.exists():
        logger.warning("Skills directory not found: %s", root_dir)
        return []

    specs: list[SkillSpec] = []

    # Look for SKILL.md files in subdirectories
    for skill_file in root_dir.rglob("SKILL.md"):
        try:
            raw = skill_file.read_text(encoding="utf-8")
        except Exception:
            logger.exception("Failed to read skill file: %s", skill_file)
            continue

        meta, body = _split_frontmatter(raw)

        # Get name from frontmatter or use parent directory name
        name = (meta.get("name") or skill_file.parent.name).strip()
        if not name:
            logger.warning("Skill file missing name: %s", skill_file)
            continue

        description = (meta.get("description") or "").strip()
        if not description:
            logger.warning("Skill file missing description: %s", skill_file)
            continue

        content = body.strip()
        if not content:
            logger.warning("Skill file missing content body: %s", skill_file)
            continue

        specs.append(
            SkillSpec(
                name=name,
                description=description,
                content=content,
                path=skill_file,
            )
        )

    specs.sort(key=lambda spec: spec.name)
    logger.info("Found %d skill files", len(specs))
    return specs


def _split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Split YAML frontmatter from markdown content.

    Expected format:
    ---
    name: skill-name
    description: skill description
    ---

    # Content here
    """
    if not text.startswith("---"):
        return {}, text

    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text

    end_idx = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end_idx = idx
            break

    if end_idx is None:
        return {}, text

    front_lines = lines[1:end_idx]
    body = "\n".join(lines[end_idx + 1:])

    return _parse_frontmatter_lines(front_lines), body


def _parse_frontmatter_lines(lines: list[str]) -> dict[str, str]:
    """Parse YAML-like frontmatter lines into a dict."""
    meta: dict[str, str] = {}
    current_key: Optional[str] = None
    current_value: list[str] = []

    for line in lines:
        if not line.strip():
            continue

        # Check if this is a new key
        if ":" in line and not line.startswith(" "):
            # Save previous key if exists
            if current_key:
                meta[current_key] = "\n".join(current_value).strip()

            key, value = line.split(":", 1)
            current_key = key.strip()
            current_value = [value.strip()] if value.strip() else []
        elif current_key:
            # Continuation of previous value
            current_value.append(line.strip())

    # Save last key
    if current_key:
        meta[current_key] = "\n".join(current_value).strip()

    return meta


def _normalize_name(name: str) -> str:
    """Normalize skill name for lookup."""
    cleaned = []
    for char in name.strip().lower():
        if char.isalnum():
            cleaned.append(char)
        elif char in {"-", "_", " "}:
            cleaned.append("-")

    normalized = "".join(cleaned)
    while "--" in normalized:
        normalized = normalized.replace("--", "-")

    return normalized.strip("-")
