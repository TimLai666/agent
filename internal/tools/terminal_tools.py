import platform
import re
import shutil
import subprocess
from pathlib import Path

from pydantic_ai import Agent

from internal.cli import confirm
from internal.logger import logger
from internal.paths import TIM_AGENT_SANDBOX_DIR


# Agent workspace root - points to sandbox directory for isolation
# Agent sees sandbox as its workspace root, real CWD is hidden
AGENT_WORKSPACE_ROOT = TIM_AGENT_SANDBOX_DIR
SANDBOX_ROOT = TIM_AGENT_SANDBOX_DIR


def _ensure_sandbox_dir() -> Path:
    SANDBOX_ROOT.mkdir(parents=True, exist_ok=True)
    return SANDBOX_ROOT


def _resolve_sandbox_path(path_in_sandbox: str) -> Path:
    sandbox = _ensure_sandbox_dir()
    candidate = (sandbox / path_in_sandbox).resolve() if path_in_sandbox else sandbox
    if candidate != sandbox and sandbox not in candidate.parents:
        raise ValueError("Path escapes sandbox directory.")
    return candidate


def _resolve_workspace_path(path_in_workspace: str) -> Path:
    if not path_in_workspace:
        raise ValueError("path_in_workspace cannot be empty.")

    raw = Path(path_in_workspace)
    candidate = raw.resolve() if raw.is_absolute() else (AGENT_WORKSPACE_ROOT / raw).resolve()
    if candidate != AGENT_WORKSPACE_ROOT and AGENT_WORKSPACE_ROOT not in candidate.parents:
        raise ValueError("Path escapes workspace root.")
    return candidate


def get_platform_info() -> str:
    """
    Get the current operating system and architecture information.
    Agent SHOULD call this before running any terminal commands to ensure compatibility.
    """
    info = {
        "system": platform.system(),
        "node": platform.node(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "architecture": str(platform.architecture()),
    }
    logger.info(f"Retrieved platform info: {info['system']} {info['machine']}")
    return "\n".join([f"{k}: {v}" for k, v in info.items()])


def get_sandbox_info() -> str:
    """Get sandbox directory information for command execution and artifact isolation."""
    sandbox = _ensure_sandbox_dir()
    return "\n".join(
        [
            f"workspace_root: {AGENT_WORKSPACE_ROOT}",
            f"sandbox_root: {sandbox}",
            "note: run_terminal_command executes with sandbox as current working directory.",
        ]
    )


def stage_to_sandbox(path_in_workspace: str, target_path_in_sandbox: str = "") -> str:
    """Copy a file or directory from workspace into sandbox for isolated changes."""
    source = _resolve_workspace_path(path_in_workspace)
    if not source.exists():
        return f"Error: source path not found: {source}"

    sandbox_target_base = _resolve_sandbox_path(target_path_in_sandbox)
    if source.is_file():
        destination = sandbox_target_base
        if destination.exists() and destination.is_dir():
            destination = destination / source.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        return f"Staged file to sandbox: {source} -> {destination}"

    destination = sandbox_target_base
    if destination.exists() and destination.is_file():
        return f"Error: destination is a file: {destination}"

    if destination.exists():
        destination = destination / source.name

    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination, dirs_exist_ok=True)
    return f"Staged directory to sandbox: {source} -> {destination}"


def export_from_sandbox(path_in_sandbox: str, destination_in_workspace: str, overwrite: bool = False) -> str:
    """Export a file or directory from sandbox back into workspace."""
    source = _resolve_sandbox_path(path_in_sandbox)
    destination = _resolve_workspace_path(destination_in_workspace)

    if not source.exists():
        return f"Error: sandbox path not found: {source}"

    if destination.exists() and not overwrite:
        return (
            f"Error: destination exists: {destination}. "
            "Set overwrite=true to replace it."
        )

    if source.is_file():
        if destination.exists() and destination.is_dir():
            destination = destination / source.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        return f"Exported file from sandbox: {source} -> {destination}"

    if destination.exists() and destination.is_file():
        return f"Error: destination is a file: {destination}"

    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination, dirs_exist_ok=overwrite)
    return f"Exported directory from sandbox: {source} -> {destination}"


def run_terminal_command(command: str) -> str:
    """
    Execute a terminal command and return its output.

    IMPORTANT:
    1. Always call `get_platform_info` first to determine if you are on Windows, Linux, or macOS.
    2. Catastrophic commands are hard-blocked; other non-read-only commands require manual confirmation.
    3. Safe read-only commands are auto-approved; other commands still require manual confirmation.
    4. There is a 120-second timeout.
    5. Windows commands run through PowerShell by default.
    """
    logger.info(f"Agent attempting to run terminal command: {command}")

    # Hard-block only catastrophic, system-destroying command patterns.
    hard_block_patterns = {
        r"\brm\s+-rf\s+/(\s|$)": "rm -rf /",
        r"\brm\s+-rf\s+--no-preserve-root\b": "rm --no-preserve-root",
        r"\bdd\s+if=.*\s+of=/dev/(sd[a-z]|nvme\d+n\d+|disk\d+)\b": "dd to raw disk",
        r"\bmkfs(\.[a-z0-9]+)?\b": "mkfs",
        r"\bfdisk\b": "fdisk",
        r"\bparted\b": "parted",
        r"\bformat\s+[a-z]:\b": "format drive",
        r"\bshutdown\b": "shutdown",
        r"\breboot\b": "reboot",
        r"\bhalt\b": "halt",
        r"\bpoweroff\b": "poweroff",
    }

    normalized_command = command.lower()
    for pattern, label in hard_block_patterns.items():
        if re.search(pattern, normalized_command):
            logger.warning(
                "Blocked catastrophic command: %s (pattern: %s)",
                command,
                label,
            )
            return (
                "Error: Command execution denied. "
                f"Detected catastrophic command pattern: {label}."
            )

    try:
        if _is_read_only_safe_command(command):
            logger.info("Auto-approved safe read-only command: %s", command)
        else:
            # User confirmation is the final safety gate for non-read-only commands
            if not confirm(
                message=f"Agent wants to execute terminal command: `{command}`. Allow?",
                default_choice="N",
            ):
                logger.info(f"User denied command execution: {command}")
                return "❌ User denied permission to execute this command. The operation was cancelled."

        process = _run_command(command)

        stdout = process.stdout
        stderr = process.stderr
        return_code = process.returncode

        results = []
        if stdout:
            results.append(f"--- Standard Output ---\n{stdout}")
        if stderr:
            results.append(f"--- Standard Error ---\n{stderr}")

        if not stdout and not stderr:
            results.append("Command executed successfully with no output.")

        results.append(f"Process finished with return code {return_code}")

        return "\n".join(results)

    except subprocess.TimeoutExpired:
        logger.error(f"Command timed out: {command}")
        return "Error: Command timed out after 120 seconds."
    except Exception as e:
        logger.error(f"Error executing command: {str(e)}")
        return f"Error executing command: {str(e)}"


def add_terminal_tools(agent: Agent) -> None:
    """Add terminal execution tools to the agent."""
    agent.tool_plain(get_platform_info)
    agent.tool_plain(get_sandbox_info)
    agent.tool_plain(stage_to_sandbox)
    agent.tool_plain(export_from_sandbox)
    agent.tool_plain(run_terminal_command)


def _is_read_only_safe_command(command: str) -> bool:
    """Return True when command is a simple, read-only, low-risk command."""
    if not command or not command.strip():
        return False

    normalized = command.strip().lower()

    # Require single command without chaining or redirection to keep auto-approval strict.
    disallowed_operators = ["&&", "||", ";", ">", "<"]
    if any(op in normalized for op in disallowed_operators):
        return False

    # Normalize first token for quick classification.
    match = re.match(r"^\s*([a-z0-9_.-]+)", normalized)
    if not match:
        return False
    first = match.group(1)

    safe_single_commands = {
        "pwd",
        "ls",
        "dir",
        "whoami",
        "hostname",
        "date",
        "ver",
        "where",
        "which",
        "uname",
        "cat",
        "type",
        "head",
        "tail",
        "get-date",
        "get-location",
        "get-content",
        "get-childitem",
        "get-command",
    }
    if first in safe_single_commands:
        return True

    # Explicitly allow safe inspection commands for common toolchains/shell binaries.
    safe_exact_commands = {
        # go
        "go version",
        "go env",
        "go help",
        "go tool dist list",
        # bun
        "bun --version",
        "bun -v",
        "bun --help",
        "bun pm --version",
        # shell binaries: version/help only (no -c / -command execution)
        "powershell --version",
        "powershell -version",
        "pwsh --version",
        "pwsh -v",
        "bash --version",
        "bash -version",
        "zsh --version",
    }
    if normalized in safe_exact_commands:
        return True

    # Explicitly allow read-only git inspection commands.
    git_prefixes = (
        "git status",
        "git log",
        "git show",
        "git diff",
        "git branch",
        "git rev-parse",
    )
    if normalized.startswith(git_prefixes):
        return True

    # Allow version checks only.
    if normalized in {
        "python --version",
        "python -v",
        "uv --version",
        "node --version",
        "go version",
        "bun --version",
        "bun -v",
    }:
        return True

    return False


def _run_command(command: str) -> subprocess.CompletedProcess[str]:
    system = platform.system().lower()
    if system == "windows":
        return _run_windows_command(command)
    return _run_posix_command(command)


def _run_windows_command(command: str) -> subprocess.CompletedProcess[str]:
    # Force UTF-8 output to avoid locale decode crashes (e.g., cp950 on Windows).
    utf8_bootstrap = (
        "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); "
        "$OutputEncoding = [System.Text.UTF8Encoding]::new($false); "
        "chcp 65001 > $null; "
    )

    # Default to PowerShell to handle common cmdlets and pipelines reliably.
    powershell = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        utf8_bootstrap + command,
    ]

    return subprocess.run(
        powershell,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=120,
        cwd=str(_ensure_sandbox_dir()),
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def _run_posix_command(command: str) -> subprocess.CompletedProcess[str]:
    shell = ["/bin/bash", "-lc", command]
    return subprocess.run(
        shell,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=120,
        cwd=str(_ensure_sandbox_dir()),
    )
