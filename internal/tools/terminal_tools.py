import platform
import re
import subprocess

from pydantic_ai import Agent

from internal.cli import confirm
from internal.logger import logger


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


def run_terminal_command(command: str) -> str:
    """
    Execute a terminal command and return its output.

    IMPORTANT:
    1. Always call `get_platform_info` first to determine if you are on Windows, Linux, or macOS.
    2. Prohibited keywords (e.g., rm, del, format, sudo) will cause the command to be blocked.
    3. Safe read-only commands are auto-approved; other commands still require manual confirmation.
    4. There is a 120-second timeout.
    5. Windows commands run through PowerShell by default.
    """
    logger.info(f"Agent attempting to run terminal command: {command}")

    # Define prohibited keywords to prevent dangerous operations
    prohibited_keywords = {
        # File/Directory deletion
        "rm",
        "del",
        "rd",
        "rmdir",
        "erase",
        # Disk and Filesystem operations
        "format",
        "mkfs",
        "fdisk",
        "parted",
        "dd",
        "mount",
        "umount",
        # System control
        "shutdown",
        "reboot",
        "halt",
        "poweroff",
        # Privilege and User management
        "sudo",
        "su",
        "passwd",
        "chown",
        "chmod",
        "chpasswd",
        "net",
        "useradd",
        "userdel",
        "usermod",
        # Process management
        "kill",
        "pkill",
        "killall",
        "taskkill",
        # Shell/Escaping (prevent bypassing checks)
        "sh",
        "cmd",
        "alias",
        "unalias",
        # Windows system sensitive
        "reg",
        "sc",
        "schtasks",
    }

    # Extract words from the command to check against prohibited keywords
    # Using word boundaries to avoid false positives
    words = set(re.findall(r"\b\w+\b", command.lower()))

    intersected = words.intersection(prohibited_keywords)
    if intersected:
        forbidden = ", ".join(intersected)
        logger.warning(f"Blocked dangerous command: {command} (found: {forbidden})")
        return f"Error: Command execution denied. The command contains prohibited keywords: {forbidden}."

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
    # Default to PowerShell to handle common cmdlets and pipelines reliably.
    powershell = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        command,
    ]

    return subprocess.run(
        powershell,
        text=True,
        capture_output=True,
        timeout=120,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def _run_posix_command(command: str) -> subprocess.CompletedProcess[str]:
    shell = ["/bin/bash", "-lc", command]
    return subprocess.run(shell, text=True, capture_output=True, timeout=120)
