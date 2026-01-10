import platform
import re
import subprocess

from pydantic_ai import Agent

from internal.cli import confirm
from internal.logger import logger


def add_terminal_tools(agent: Agent) -> None:
    """Add terminal execution tools to the agent."""

    @agent.tool_plain
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

    @agent.tool_plain
    def run_terminal_command(command: str) -> str:
        """
        Execute a terminal command and return its output.

        IMPORTANT:
        1. Always call `get_platform_info` first to determine if you are on Windows, Linux, or macOS.
        2. Prohibited keywords (e.g., rm, del, format, sudo) will cause the command to be blocked.
        3. Manual user confirmation is required for every execution.
        4. There is a 120-second timeout.
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
            "bash",
            "sh",
            "zsh",
            "cmd",
            "powershell",
            "pwsh",
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
            # User confirmation is the final safety gate
            if not confirm(
                message=f"Agent wants to execute terminal command: `{command}`. Allow?",
                default_choice="N",
            ):
                return "Command execution cancelled by user."

            # Execute the command
            # shell=True is used to support environment variables, pipes, and redirections
            process = subprocess.run(
                command, shell=True, text=True, capture_output=True, timeout=120
            )

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
