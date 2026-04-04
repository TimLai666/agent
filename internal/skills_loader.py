"""Skills loader for Claude Code compatible skills.

Skills are folders containing SKILL.md files with YAML frontmatter and instructions.
This module provides functionality to load and manage skills with support for:
- Progressive disclosure (lazy loading)
- Bundled resources (scripts, references, assets)
- LLM-based relevance scoring
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Optional, Any, TYPE_CHECKING
import json
import asyncio

from internal.logger import logger
from internal.paths import TIM_AGENT_SKILLS_DIR

if TYPE_CHECKING:
    from pydantic_ai import Agent


SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"
DEFAULT_EXTERNAL_SKILLS_DIRS = [
    TIM_AGENT_SKILLS_DIR,
    Path.home() / ".agents" / "skills",
    Path.home() / ".claude" / "skills",
]


@dataclass
class SkillResources:
    """Bundled resources for a skill."""

    scripts: dict[str, Path] = field(default_factory=dict)
    references: dict[str, Path] = field(default_factory=dict)
    assets: dict[str, Path] = field(default_factory=dict)

    def has_resources(self) -> bool:
        """Check if any resources exist."""
        return bool(self.scripts or self.references or self.assets)

    def list_all(self) -> dict[str, list[str]]:
        """List all resource files."""
        return {
            "scripts": list(self.scripts.keys()),
            "references": list(self.references.keys()),
            "assets": list(self.assets.keys()),
        }


@dataclass
class SkillSpec:
    """Specification for a loaded skill with progressive disclosure support."""

    name: str
    description: str
    path: Path
    resources: SkillResources = field(default_factory=SkillResources)
    _content: Optional[str] = field(default=None, repr=False)
    _loaded_resources: dict[str, str] = field(default_factory=dict, repr=False)

    @property
    def content(self) -> str:
        """Lazy load content on first access."""
        if self._content is None:
            self._content = self._load_content()
        return self._content

    def _load_content(self) -> str:
        """Load SKILL.md content from disk."""
        try:
            skill_file = self.path / "SKILL.md"
            if skill_file.exists():
                raw = skill_file.read_text(encoding="utf-8")
                _, body = _split_frontmatter(raw)
                logger.info("Loaded content for skill '%s' (~%d chars)", self.name, len(body))
                return body.strip()
            return ""
        except Exception:
            logger.exception("Failed to load content for skill '%s'", self.name)
            return ""

    def load_resource(self, resource_type: str, name: str) -> Optional[str]:
        """Load a specific resource file on demand.

        Args:
            resource_type: One of 'scripts', 'references', 'assets'
            name: Resource file name

        Returns:
            Resource content or None if not found
        """
        cache_key = f"{resource_type}:{name}"
        if cache_key in self._loaded_resources:
            return self._loaded_resources[cache_key]

        resource_dict = getattr(self.resources, resource_type, {})
        if name not in resource_dict:
            return None

        try:
            resource_path = resource_dict[name]
            content = resource_path.read_text(encoding="utf-8")
            self._loaded_resources[cache_key] = content
            logger.info("Loaded resource %s for skill '%s'", cache_key, self.name)
            return content
        except Exception:
            logger.exception("Failed to load resource %s for skill '%s'", cache_key, self.name)
            return None

    def short_description(self) -> str:
        """Get the first line of description."""
        if not self.description:
            return ""
        if "\\n" in self.description:
            return self.description.split("\\n", 1)[0].strip()
        if "\n" in self.description:
            return self.description.split("\n", 1)[0].strip()
        return self.description.strip()

    def metadata_dict(self) -> dict:
        """Get lightweight metadata for progressive disclosure."""
        return {
            "name": self.name,
            "description": self.description,
            "has_resources": self.resources.has_resources(),
            "resources": self.resources.list_all() if self.resources.has_resources() else {},
        }


class SkillRegistry:
    """Registry for managing loaded skills with progressive disclosure."""

    def __init__(
        self,
        skills: dict[str, SkillSpec],
        llm_scorer: Optional["SkillRelevanceScorer"] = None
    ) -> None:
        self._skills = skills
        self._llm_scorer = llm_scorer
        logger.info(
            "SkillRegistry initialized with %d skills (LLM scorer: %s)",
            len(skills),
            "enabled" if llm_scorer else "disabled"
        )

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

    def get_metadata_summary(self) -> dict[str, dict]:
        """Get lightweight metadata for all skills (for progressive disclosure).

        Returns only name and description without loading full content.
        This is the ~100 token metadata scan mentioned in Claude Code docs.
        """
        return {
            name: spec.metadata_dict()
            for name, spec in self._skills.items()
        }

    async def find_relevant_skills(
        self,
        prompt: str,
        max_skills: int = 3,
        min_score: float = 0.1,
        use_llm: bool = False
    ) -> list[SkillSpec]:
        """Find skills relevant to the given prompt.

        Supports two matching modes:
        1. Keyword-based (default): Fast, deterministic Jaccard similarity
        2. LLM-based (use_llm=True): More accurate but requires LLM call

        Args:
            prompt: User's input prompt
            max_skills: Maximum number of skills to return
            min_score: Minimum relevance score (0-1) to include a skill
            use_llm: Whether to use LLM for relevance scoring

        Returns:
            List of relevant skills sorted by relevance score
        """
        if not prompt or not self._skills:
            return []

        # Use LLM scoring if available and requested
        if use_llm and self._llm_scorer:
            return await self._llm_scorer.score_skills(prompt, list(self._skills.values()), max_skills, min_score)

        # Fall back to keyword-based matching
        return self._keyword_based_matching(prompt, max_skills, min_score)

    def _keyword_based_matching(
        self,
        prompt: str,
        max_skills: int = 3,
        min_score: float = 0.1
    ) -> list[SkillSpec]:
        """Keyword-based skill matching using Jaccard similarity."""
        prompt_lower = prompt.lower()
        scored_skills: list[tuple[float, SkillSpec]] = []

        # Stop words to filter out
        stop_words = {
            'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at',
            'to', 'for', 'of', 'with', 'by', 'from', 'as', 'is', 'are',
            'was', 'were', 'be', 'been', 'being', 'have', 'has', 'had',
            'do', 'does', 'did', 'will', 'would', 'should', 'could',
            'this', 'that', 'these', 'those', 'it', 'its', 'when', 'use'
        }

        for skill in self._skills.values():
            desc_lower = skill.description.lower()

            # Extract meaningful words
            desc_words = {w for w in re.findall(r'\w+', desc_lower) if w not in stop_words}
            prompt_words = {w for w in re.findall(r'\w+', prompt_lower) if w not in stop_words}

            if not desc_words or not prompt_words:
                continue

            # Calculate Jaccard similarity
            common_words = desc_words & prompt_words
            if not common_words:
                continue

            # Base score
            score = len(common_words) / len(desc_words | prompt_words)

            # Boost score if key technical words match
            key_words = {'code', 'review', 'debug', 'bug', 'error', 'skill', 'help', 'test', 'fix'}
            key_matches = common_words & key_words
            if key_matches:
                score *= (1 + len(key_matches) * 0.2)

            if score >= min_score:
                scored_skills.append((score, skill))

        # Sort by score descending
        scored_skills.sort(key=lambda x: x[0], reverse=True)
        return [skill for _, skill in scored_skills[:max_skills]]

    def build_skills_context(self, skills: list[SkillSpec]) -> str:
        """Build context string from selected skills with priority guidance."""
        if not skills:
            return ""

        parts = [
            "# Active Skills (PRIORITY: Use these BEFORE tools)\n",
            "",
            "**IMPORTANT**: The following skills have been activated for this task. "
            "You MUST prioritize the knowledge and methodologies provided in these skills "
            "over direct tool usage. Think of these as expert guidance that should inform "
            "all your decisions and actions.\n",
            ""
        ]

        for skill in skills:
            parts.append(f"## {skill.name}\n")
            parts.append(f"{skill.content}\n")

        parts.append("\n---\n")
        parts.append("**Remember**: Follow the skills guidance above before using any tools.\n")

        return "\n".join(parts)


def load_skill_registry(
    root_dir: Optional[Path] = None,
    root_dirs: Optional[list[Path]] = None,
    enable_llm_scoring: bool = False,
    agent: Optional[Any] = None,
    disabled_skills: Optional[list[str]] = None,
) -> SkillRegistry:
    """Load all skills from the skills directory with optional LLM scoring.

    Args:
        root_dir: Single skills directory path (legacy, defaults to SKILLS_DIR)
        root_dirs: Multiple skills directory paths. When provided, root_dir is ignored.
        enable_llm_scoring: Whether to enable LLM-based relevance scoring
        agent: Agent instance for LLM scoring (required if enable_llm_scoring=True)

    Returns:
        SkillRegistry instance
    """
    if root_dirs:
        skills_roots = [Path(p) for p in root_dirs]
    elif root_dir is not None:
        skills_roots = [Path(root_dir)]
    else:
        # Default precedence: user global dirs first, then project-local skills.
        skills_roots = [*DEFAULT_EXTERNAL_SKILLS_DIRS, SKILLS_DIR]

    specs: list[SkillSpec] = []
    for skills_root in skills_roots:
        if not skills_root.exists():
            logger.info("Skills directory not found: %s", skills_root)
            continue
        specs.extend(load_skill_specs(skills_root))

    disabled_set: set[str] = {_normalize_name(s) for s in (disabled_skills or [])}

    skill_map: dict[str, SkillSpec] = {}
    for spec in specs:
        key = _normalize_name(spec.name)
        if key in disabled_set:
            logger.info("Skipping disabled skill '%s'", spec.name)
            continue
        if key in skill_map:
            logger.warning(
                "Duplicate skill name '%s' from %s; skipping",
                spec.name,
                spec.path,
            )
            continue
        skill_map[key] = spec

    # Create LLM scorer if requested
    llm_scorer = None
    if enable_llm_scoring and agent:
        try:
            llm_scorer = SkillRelevanceScorer(agent)
            logger.info("LLM-based skill scoring enabled")
        except Exception:
            logger.exception("Failed to create LLM scorer; falling back to keyword matching")

    roots_text = ", ".join(str(p) for p in skills_roots)
    logger.info("Loaded %d skills from %s", len(skill_map), roots_text)
    return SkillRegistry(skill_map, llm_scorer)


def load_skill_specs(root_dir: Path) -> list[SkillSpec]:
    """Load all SKILL.md files with bundled resources from the root directory.

    Supports progressive disclosure - only metadata is loaded initially,
    content is lazy-loaded on first access.
    """
    if not root_dir.exists():
        logger.warning("Skills directory not found: %s", root_dir)
        return []

    specs: list[SkillSpec] = []

    # Look for SKILL.md files in subdirectories
    for skill_file in root_dir.rglob("SKILL.md"):
        skill_dir = skill_file.parent

        try:
            raw = skill_file.read_text(encoding="utf-8")
        except Exception:
            logger.exception("Failed to read skill file: %s", skill_file)
            continue

        meta, _ = _split_frontmatter(raw)

        # Get name from frontmatter or use parent directory name
        name = (meta.get("name") or skill_dir.name).strip()
        if not name:
            logger.warning("Skill file missing name: %s", skill_file)
            continue

        description = (meta.get("description") or "").strip()
        if not description:
            logger.warning("Skill file missing description: %s", skill_file)
            continue

        # Load bundled resources (scripts, references, assets)
        resources = _load_skill_resources(skill_dir)

        # Create spec with lazy content loading
        specs.append(
            SkillSpec(
                name=name,
                description=description,
                path=skill_dir,
                resources=resources,
                _content=None,  # Will be lazy-loaded
            )
        )

    specs.sort(key=lambda spec: spec.name)
    logger.info("Found %d skill files", len(specs))
    return specs


def _load_skill_resources(skill_dir: Path) -> SkillResources:
    """Load bundled resources for a skill.

    Supports:
    - scripts/: Executable scripts
    - references/: Reference documentation
    - assets/: Templates, images, etc.
    """
    resources = SkillResources()

    # Load scripts
    scripts_dir = skill_dir / "scripts"
    if scripts_dir.exists() and scripts_dir.is_dir():
        for script_file in scripts_dir.iterdir():
            if script_file.is_file():
                resources.scripts[script_file.name] = script_file

    # Load references
    refs_dir = skill_dir / "references"
    if refs_dir.exists() and refs_dir.is_dir():
        for ref_file in refs_dir.iterdir():
            if ref_file.is_file():
                resources.references[ref_file.name] = ref_file

    # Load assets
    assets_dir = skill_dir / "assets"
    if assets_dir.exists() and assets_dir.is_dir():
        for asset_file in assets_dir.iterdir():
            if asset_file.is_file():
                resources.assets[asset_file.name] = asset_file

    if resources.has_resources():
        logger.debug(
            "Loaded resources for skill at %s: %s",
            skill_dir.name,
            resources.list_all()
        )

    return resources


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


class SkillRelevanceScorer:
    """LLM-based skill relevance scoring for more accurate matching."""

    def __init__(self, agent: "Agent[None, str]") -> None:
        self.agent = agent

    async def score_skills(
        self,
        prompt: str,
        skills: list[SkillSpec],
        max_skills: int = 3,
        min_score: float = 0.1
    ) -> list[SkillSpec]:
        """Score skills using LLM-based relevance evaluation.

        Args:
            prompt: User's input prompt
            skills: List of all available skills
            max_skills: Maximum number of skills to return
            min_score: Minimum relevance score (0-1) to include

        Returns:
            List of relevant skills sorted by LLM-assessed relevance
        """
        if not skills:
            return []

        # Build skill catalog for LLM
        skill_catalog = []
        for skill in skills:
            skill_catalog.append({
                "name": skill.name,
                "description": skill.description
            })

        # Ask LLM to score relevance
        scoring_prompt = (
            "You are a skill relevance evaluator. Given a user prompt and a list of available skills, "
            "score each skill's relevance from 0.0 (completely irrelevant) to 1.0 (highly relevant).\n\n"
            f"User prompt: {prompt}\n\n"
            "Available skills:\n"
            + "\n".join([f"- {s['name']}: {s['description']}" for s in skill_catalog]) + "\n\n"
            "Return ONLY a JSON object with skill names as keys and relevance scores (0.0-1.0) as values.\n"
            "Example: {\"skill-1\": 0.8, \"skill-2\": 0.3, \"skill-3\": 0.0}\n\n"
            "JSON:"
        )

        try:
            result = await self.agent.run(scoring_prompt)
            scores_json = (result.output or "").strip()

            # Try to extract JSON from response
            scores = self._extract_json_scores(scores_json)

            if not scores:
                logger.warning("Failed to parse LLM skill scores; falling back to keyword matching")
                return []

            # Build scored skills list
            scored_skills: list[tuple[float, SkillSpec]] = []
            for skill in skills:
                score = scores.get(skill.name, 0.0)
                if score >= min_score:
                    scored_skills.append((score, skill))

            # Sort by score descending
            scored_skills.sort(key=lambda x: x[0], reverse=True)
            return [skill for _, skill in scored_skills[:max_skills]]

        except Exception:
            logger.exception("LLM scoring failed; falling back to keyword matching")
            return []

    def _extract_json_scores(self, text: str) -> dict[str, float]:
        """Extract skill scores from LLM response."""
        try:
            # Try direct JSON parse
            scores = json.loads(text)
            if isinstance(scores, dict):
                return {k: float(v) for k, v in scores.items() if isinstance(v, (int, float))}
        except Exception:
            pass

        # Try to find JSON in text
        import re
        json_match = re.search(r'\{[^{}]*\}', text)
        if json_match:
            try:
                scores = json.loads(json_match.group())
                if isinstance(scores, dict):
                    return {k: float(v) for k, v in scores.items() if isinstance(v, (int, float))}
            except Exception:
                pass

        return {}

    def score_skills_sync(
        self,
        prompt: str,
        skills: list[SkillSpec],
        max_skills: int = 3,
        min_score: float = 0.1
    ) -> list[SkillSpec]:
        """Synchronous wrapper for async score_skills."""
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        return loop.run_until_complete(
            self.score_skills(prompt, skills, max_skills, min_score)
        )
