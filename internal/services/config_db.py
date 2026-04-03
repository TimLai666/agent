"""Database module for model/provider configuration.

Runtime now uses a single global model config: `default`.
"""
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from internal.logger import logger
from internal.paths import TIM_AGENT_CONFIG_DIR

# Database location
DB_PATH = TIM_AGENT_CONFIG_DIR / "config.db"


@dataclass
class ProviderConfig:
    """Configuration for a model provider"""
    provider_id: str  # Unique identifier for this provider config
    provider_type: str  # "openai-compatible" or "github-copilot"
    name: str  # Display name
    base_url: Optional[str] = None  # For OpenAI-compatible APIs
    api_key: Optional[str] = None  # For OpenAI-compatible APIs
    github_token: Optional[str] = None  # For GitHub Copilot


@dataclass
class AgentModelConfig:
    """Configuration for a named config entry (runtime uses `default`)."""
    agent_name: str  # Runtime active key is "default"
    provider_id: str  # Reference to ProviderConfig
    model_name: str  # e.g., "gpt-4", "claude-3-5-sonnet"
    temperature: float = 0.2
    inherit_from: Optional[str] = None  # Parent agent to inherit from (for sub-agents)


@dataclass
class McpToolConfig:
    """Configuration for a custom MCP tool"""
    mcp_tool_id: str  # Unique identifier for this tool
    name: str  # Display name
    command: str  # The command to execute
    args: Optional[str] = None  # Arguments for the command (space-separated)


@dataclass
class RemoteMcpConfig:
    """Configuration for a remote MCP endpoint"""
    remote_mcp_id: str  # Unique identifier for this remote MCP
    name: str  # Display name
    url: str  # URL to fetch the MCP definition from


def _get_db_path() -> Path:
    """Get the database path, creating the directory if needed"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return DB_PATH


@contextmanager
def get_connection():
    """Context manager for database connections"""
    conn = sqlite3.connect(str(_get_db_path()))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_database():
    """Initialize the database schema"""
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # Providers table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS providers (
                provider_id TEXT PRIMARY KEY,
                provider_type TEXT NOT NULL CHECK(provider_type IN ('openai-compatible', 'github-copilot')),
                name TEXT NOT NULL,
                base_url TEXT,
                api_key TEXT,
                github_token TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Agent model configurations table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS agent_configs (
                agent_name TEXT PRIMARY KEY,
                provider_id TEXT,
                model_name TEXT,
                temperature REAL DEFAULT 0.2,
                inherit_from TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (provider_id) REFERENCES providers(provider_id) ON DELETE CASCADE,
                FOREIGN KEY (inherit_from) REFERENCES agent_configs(agent_name) ON DELETE SET NULL,
                CHECK (
                    (inherit_from IS NULL AND provider_id IS NOT NULL AND model_name IS NOT NULL) OR
                    (inherit_from IS NOT NULL)
                )
            )
        """)
        
        # MCP tools table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS mcp_tools (
                mcp_tool_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                command TEXT NOT NULL,
                args TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Remote MCPs table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS remote_mcps (
                remote_mcp_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                url TEXT NOT NULL UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create indexes
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_agent_provider 
            ON agent_configs(provider_id)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_mcp_tool_name
            ON mcp_tools(name)
        """)
        
        logger.info(f"Database initialized at {_get_db_path()}")


def add_provider(config: ProviderConfig) -> bool:
    """Add or update a provider configuration"""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO providers (provider_id, provider_type, name, base_url, api_key, github_token)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider_id) DO UPDATE SET
                    provider_type=excluded.provider_type,
                    name=excluded.name,
                    base_url=excluded.base_url,
                    api_key=excluded.api_key,
                    github_token=excluded.github_token,
                    updated_at=CURRENT_TIMESTAMP
            """, (
                config.provider_id,
                config.provider_type,
                config.name,
                config.base_url,
                config.api_key,
                config.github_token,
            ))
            return True
    except Exception as e:
        logger.error(f"Failed to add provider: {e}")
        return False


def get_provider(provider_id: str) -> Optional[ProviderConfig]:
    """Get a provider configuration by ID"""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM providers WHERE provider_id = ?", (provider_id,))
            row = cursor.fetchone()
            if row:
                return ProviderConfig(
                    provider_id=row["provider_id"],
                    provider_type=row["provider_type"],
                    name=row["name"],
                    base_url=row["base_url"],
                    api_key=row["api_key"],
                    github_token=row["github_token"],
                )
    except Exception as e:
        logger.error(f"Failed to get provider: {e}")
    return None


def list_providers() -> list[ProviderConfig]:
    """List all provider configurations"""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM providers ORDER BY name")
            rows = cursor.fetchall()
            return [
                ProviderConfig(
                    provider_id=row["provider_id"],
                    provider_type=row["provider_type"],
                    name=row["name"],
                    base_url=row["base_url"],
                    api_key=row["api_key"],
                    github_token=row["github_token"],
                )
                for row in rows
            ]
    except Exception as e:
        logger.error(f"Failed to list providers: {e}")
        return []


def delete_provider(provider_id: str) -> bool:
    """Delete a provider configuration"""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM providers WHERE provider_id = ?", (provider_id,))
            return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Failed to delete provider: {e}")
        return False


def set_agent_config(config: AgentModelConfig) -> bool:
    """Set configuration for a specific agent"""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO agent_configs (agent_name, provider_id, model_name, temperature, inherit_from)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(agent_name) DO UPDATE SET
                    provider_id=excluded.provider_id,
                    model_name=excluded.model_name,
                    temperature=excluded.temperature,
                    inherit_from=excluded.inherit_from,
                    updated_at=CURRENT_TIMESTAMP
            """, (
                config.agent_name,
                config.provider_id,
                config.model_name,
                config.temperature,
                config.inherit_from,
            ))
            return True
    except Exception as e:
        logger.error(f"Failed to set agent config: {e}")
        return False


def get_agent_config(agent_name: str, use_default: bool = True, category: Optional[str] = None) -> Optional[AgentModelConfig]:
    """Get configuration by key, with optional fallback to global `default`.

    The `category` argument is kept for backward compatibility and is ignored.
    """
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM agent_configs WHERE agent_name = ?", (agent_name,))
            row = cursor.fetchone()
            
            if not row:
                if use_default and agent_name != "default":
                    default_config = get_agent_config("default", use_default=False)
                    if default_config:
                        return AgentModelConfig(
                            agent_name=agent_name,
                            provider_id=default_config.provider_id,
                            model_name=default_config.model_name,
                            temperature=default_config.temperature,
                            inherit_from="default",
                        )
                return None
            
            # If this agent has direct configuration (not inheriting)
            if row["provider_id"] and row["model_name"]:
                return AgentModelConfig(
                    agent_name=row["agent_name"],
                    provider_id=row["provider_id"],
                    model_name=row["model_name"],
                    temperature=row["temperature"],
                    inherit_from=row["inherit_from"],
                )
            
            # If this agent inherits from another, follow the chain
            if row["inherit_from"]:
                parent_config = get_agent_config(row["inherit_from"], use_default=True, category=category)
                if parent_config:
                    # Return parent's config but keep the original agent_name
                    return AgentModelConfig(
                        agent_name=agent_name,
                        provider_id=parent_config.provider_id,
                        model_name=parent_config.model_name,
                        temperature=row["temperature"] if row["temperature"] is not None else parent_config.temperature,
                        inherit_from=row["inherit_from"],
                    )
            
            # No valid config found
            return None
            
    except Exception as e:
        logger.error(f"Failed to get agent config: {e}")
    return None


def list_agent_configs() -> list[AgentModelConfig]:
    """List all agent configurations (returns raw configs, not resolved inheritance)"""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM agent_configs ORDER BY agent_name")
            rows = cursor.fetchall()
            return [
                AgentModelConfig(
                    agent_name=row["agent_name"],
                    provider_id=row["provider_id"],
                    model_name=row["model_name"],
                    temperature=row["temperature"],
                    inherit_from=row["inherit_from"],
                )
                for row in rows
            ]
    except Exception as e:
        logger.error(f"Failed to list agent configs: {e}")
        return []


def delete_agent_config(agent_name: str) -> bool:
    """Delete configuration for a specific agent"""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM agent_configs WHERE agent_name = ?", (agent_name,))
            return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Failed to delete agent config: {e}")
        return False


def add_mcp_tool(config: McpToolConfig) -> bool:
    """Add or update an MCP tool configuration"""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO mcp_tools (mcp_tool_id, name, command, args)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(mcp_tool_id) DO UPDATE SET
                    name=excluded.name,
                    command=excluded.command,
                    args=excluded.args,
                    updated_at=CURRENT_TIMESTAMP
            """, (
                config.mcp_tool_id,
                config.name,
                config.command,
                config.args,
            ))
            return True
    except Exception as e:
        logger.error(f"Failed to add MCP tool: {e}")
        return False


def add_remote_mcp(config: RemoteMcpConfig) -> bool:
    """Add or update a remote MCP configuration"""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO remote_mcps (remote_mcp_id, name, url)
                VALUES (?, ?, ?)
                ON CONFLICT(remote_mcp_id) DO UPDATE SET
                    name=excluded.name,
                    url=excluded.url,
                    updated_at=CURRENT_TIMESTAMP
            """, (
                config.remote_mcp_id,
                config.name,
                config.url,
            ))
            return True
    except Exception as e:
        logger.error(f"Failed to add remote MCP: {e}")
        return False


def list_mcp_tools() -> list[McpToolConfig]:
    """List all MCP tool configurations"""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM mcp_tools ORDER BY name")
            rows = cursor.fetchall()
            return [
                McpToolConfig(
                    mcp_tool_id=row["mcp_tool_id"],
                    name=row["name"],
                    command=row["command"],
                    args=row["args"],
                )
                for row in rows
            ]
    except Exception as e:
        logger.error(f"Failed to list MCP tools: {e}")
        return []


def list_remote_mcps() -> list[RemoteMcpConfig]:
    """List all remote MCP configurations"""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM remote_mcps ORDER BY name")
            rows = cursor.fetchall()
            return [
                RemoteMcpConfig(
                    remote_mcp_id=row["remote_mcp_id"],
                    name=row["name"],
                    url=row["url"],
                )
                for row in rows
            ]
    except Exception as e:
        logger.error(f"Failed to list remote MCPs: {e}")
        return []


def delete_mcp_tool(mcp_tool_id: str) -> bool:
    """Delete an MCP tool configuration"""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM mcp_tools WHERE mcp_tool_id = ?", (mcp_tool_id,))
            return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Failed to delete MCP tool: {e}")
        return False


def delete_remote_mcp(remote_mcp_id: str) -> bool:
    """Delete a remote MCP configuration"""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM remote_mcps WHERE remote_mcp_id = ?", (remote_mcp_id,))
            return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Failed to delete remote MCP: {e}")
        return False


def get_mcp_last_updated() -> Optional[str]:
    """
    Get the most recent update timestamp from MCP configurations.
    Returns the latest updated_at timestamp from either mcp_tools or remote_mcps tables.
    """
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT MAX(updated_at) as last_updated FROM (
                    SELECT updated_at FROM mcp_tools
                    UNION ALL
                    SELECT updated_at FROM remote_mcps
                )
            """)
            row = cursor.fetchone()
            return row["last_updated"] if row and row["last_updated"] else None
    except Exception as e:
        logger.error(f"Failed to get MCP last updated timestamp: {e}")
        return None


# Initialize database on module import
init_database()
