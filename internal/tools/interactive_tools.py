import webbrowser
import tempfile
from pydantic_ai import Agent
import os
import time


def add_interactive_tools(agent: Agent) -> None:
    """Add interactive tools to the agent."""

    @agent.tool_plain
    def show_webpage(url: str) -> str:
        """
        Open a web page in the default web browser for the user.
        You won't see the output.
        """
        ok: bool = False
        try:
            ok = webbrowser.open(url)
            time.sleep(1)  # Give the browser time to open
            if not ok:
                raise RuntimeError("Failed to open the web page.")
        except Exception as e:
            return f"Error opening web page: {str(e)}"
        return "Web page opened successfully."

    @agent.tool_plain
    def show_webpage_from_html_string(html_str: str) -> str:
        """
        Open a web page with the provided HTML content in the default web browser.
        You won't see the output.
        """
        ok: bool = False
        try:
            with tempfile.NamedTemporaryFile('w', delete=False, suffix='.html', encoding='utf-8') as f:
                f.write(html_str)
                ok = webbrowser.open(f.name)
            time.sleep(1)  # Give the browser time to open
            os.remove(f.name)  # Clean up the temporary file after opening it
            if not ok:
                raise RuntimeError("Failed to open the web page.")
        except Exception as e:
            return f"Error opening web page: {str(e)}"
        return "Web page opened successfully."

    @agent.tool_plain
    def show_webpage_from_file(file_path: str) -> str:
        """
        Open a web page from a local HTML file in the default web browser.
        You won't see the output.
        """
        if not os.path.isfile(file_path):
            return f"File not found: {file_path}"
        try:
            ok: bool = webbrowser.open(f'file://{os.path.abspath(file_path)}')
            time.sleep(1)  # Give the browser time to open
            if not ok:
                raise RuntimeError("Failed to open the web page.")
        except Exception as e:
            return f"Error opening web page: {str(e)}"
        return "Web page opened successfully."
