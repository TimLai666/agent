"""
Web UI for configuration management.
Provides a browser-based interface for managing providers and agent configurations.
"""

from flask import Flask, render_template, request, jsonify
from pathlib import Path
import json
from typing import Optional
import threading
import webbrowser

from internal.services.config_db import (
    AgentModelConfig,
    McpToolConfig,
    ProviderConfig,
    add_mcp_tool,
    add_provider,
    delete_agent_config,
    delete_mcp_tool,
    delete_provider,
    get_agent_config,
    get_provider,
    list_agent_configs,
    list_mcp_tools,
    list_providers,
    set_agent_config,
    RemoteMcpConfig,
    add_remote_mcp,
    list_remote_mcps,
    delete_remote_mcp,
)
from internal.logger import logger
from internal.services.github_oauth import authenticate_github
from internal.services.agent_discovery import discover_agents


app = Flask(
    __name__,
    template_folder=str(Path(__file__).parent.parent.parent / "templates"),
    static_folder=str(Path(__file__).parent.parent.parent / "static"),
)

# Background web UI thread handles
_webui_thread: threading.Thread | None = None
_webui_url: str | None = None

DEFAULT_WEBUI_HOST = "127.0.0.1"
DEFAULT_WEBUI_PORT = 5000


def get_available_models(provider_id: str) -> list[str]:
    """
    獲取提供者可用的模型列表
    
    Args:
        provider_id: 提供者 ID
        
    Returns:
        模型名稱列表
    """
    provider = get_provider(provider_id)
    if not provider:
        return []
    
    try:
        if provider.provider_type == "openai-compatible":
            return _get_openai_compatible_models(provider)
        elif provider.provider_type == "github-copilot":
            return _get_github_copilot_models(provider)
        else:
            return []
    except Exception as e:
        print(f"獲取模型列表時發生錯誤: {e}")
        return []


def _get_openai_compatible_models(provider: ProviderConfig) -> list[str]:
    """獲取 OpenAI 相容 API 的模型列表 - 只返回真實從 API 獲取的資料"""
    import httpx
    
    base_url = provider.base_url or "https://api.openai.com/v1"
    
    # 標準化 base_url - 確保以 /v1 結尾
    base_url = base_url.rstrip('/')
    if not base_url.endswith('/v1'):
        base_url += '/v1'
    
    try:
        with httpx.Client(timeout=15.0) as client:
            headers = {}
            if provider.api_key:
                headers["Authorization"] = f"Bearer {provider.api_key}"
            
            models_url = f"{base_url}/models"
            print(f"正在獲取模型列表: {models_url}")
            
            response = client.get(models_url, headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                models = [model["id"] for model in data.get("data", [])]
                print(f"成功獲取 {len(models)} 個模型")
                return sorted(models) if models else []
            else:
                print(f"API 返回錯誤 {response.status_code}: {response.text[:200]}")
                return []
    except httpx.TimeoutException:
        print(f"連接超時: {base_url}")
        return []
    except Exception as e:
        print(f"無法連接到 API: {type(e).__name__}: {e}")
        return []


def _get_github_copilot_models(provider: ProviderConfig) -> list[str]:
    """
    獲取 GitHub Copilot 可用的模型列表
    
    GitHub Copilot 的模型資訊來自 models.dev API
    參考: https://github.com/anomalyco/opencode
    
    注意：獲取模型列表不需要 GitHub token，只有實際使用 API 時才需要
    """
    import httpx
    
    try:
        # 從 models.dev 獲取模型資訊（類似 opencode 的做法）
        with httpx.Client(timeout=15.0) as client:
            print("正在從 models.dev 獲取 GitHub Copilot 模型列表...")
            response = client.get("https://models.dev/api.json")
            
            if response.status_code == 200:
                data = response.json()
                print(f"API 返回的 keys: {list(data.keys())[:10]}")
                
                # 尋找 github-copilot provider
                if "github-copilot" in data:
                    copilot_data = data["github-copilot"]
                    print(f"GitHub Copilot data keys: {list(copilot_data.keys())}")
                    
                    if "models" in copilot_data:
                        models = list(copilot_data["models"].keys())
                        print(f"成功獲取 {len(models)} 個 GitHub Copilot 模型")
                        print(f"前 5 個模型: {models[:5]}")
                        return sorted(models) if models else []
                    else:
                        print("找不到 models key")
                else:
                    print("找不到 github-copilot provider")
            
            print(f"從 models.dev 獲取失敗: HTTP {response.status_code}")
            return []
            
    except httpx.TimeoutException:
        print("連接 models.dev 超時")
        return []
    except Exception as e:
        print(f"無法連接到 models.dev: {type(e).__name__}: {e}")
        return []


def _get_fallback_models(provider: ProviderConfig) -> list[str]:
    """此函數已棄用 - 不再使用假資料"""
    return []


# ===== API Routes =====

@app.route('/')
def index():
    """主頁"""
    return render_template('config.html')


@app.route('/api/providers', methods=['GET'])
def api_list_providers():
    """列出所有提供者"""
    providers = list_providers()
    return jsonify([
        {
            "provider_id": p.provider_id,
            "name": p.name,
            "provider_type": p.provider_type,
            "base_url": p.base_url,
            "has_api_key": bool(p.api_key),
            "has_github_token": bool(p.github_token),
        }
        for p in providers
    ])


@app.route('/api/providers/<provider_id>', methods=['GET'])
def api_get_provider(provider_id: str):
    """獲取單個提供者詳情"""
    provider = get_provider(provider_id)
    if not provider:
        return jsonify({"error": "Provider not found"}), 404
    
    return jsonify({
        "provider_id": provider.provider_id,
        "name": provider.name,
        "provider_type": provider.provider_type,
        "base_url": provider.base_url,
        "has_api_key": bool(provider.api_key),
        "has_github_token": bool(provider.github_token),
    })


@app.route('/api/providers', methods=['POST'])
def api_add_provider():
    """新增提供者"""
    data = request.json
    
    provider = ProviderConfig(
        provider_id=data["provider_id"],
        provider_type=data["provider_type"],
        name=data["name"],
        base_url=data.get("base_url"),
        api_key=data.get("api_key"),
        github_token=data.get("github_token"),
    )
    
    if add_provider(provider):
        return jsonify({"success": True, "message": "提供者新增成功"})
    else:
        return jsonify({"success": False, "error": "提供者新增失敗"}), 400


@app.route('/api/providers/<provider_id>', methods=['DELETE'])
def api_delete_provider(provider_id: str):
    """刪除提供者"""
    if delete_provider(provider_id):
        return jsonify({"success": True, "message": "提供者刪除成功"})
    else:
        return jsonify({"success": False, "error": "提供者刪除失敗"}), 400


@app.route('/api/providers/<provider_id>/models', methods=['GET'])
def api_get_provider_models(provider_id: str):
    """獲取提供者的可用模型列表"""
    models = get_available_models(provider_id)
    return jsonify({"models": models})


@app.route('/api/available-agents', methods=['GET'])
def api_available_agents():
    """獲取專案中所有可用的 agents"""
    agents = discover_agents()
    return jsonify(agents)


@app.route('/api/agents', methods=['GET'])
def api_list_agents():
    """列出所有 agent 配置
    
    只返回已明確配置的 agents（直接配置或繼承配置）
    未配置的 agents 會在運行時自動使用默認配置
    """
    configs = list_agent_configs()
    
    return jsonify([
        {
            "agent_name": c.agent_name,
            "provider_id": c.provider_id,
            "model_name": c.model_name,
            "temperature": c.temperature,
            "inherit_from": c.inherit_from,
            "uses_default": False  # 已配置的 agent 不使用默認
        }
        for c in configs
    ])


@app.route('/api/agents/<agent_name>', methods=['GET'])
def api_get_agent(agent_name: str):
    """獲取單個 agent 配置"""
    config = get_agent_config(agent_name)
    if not config:
        return jsonify({"error": "Agent not found"}), 404
    
    return jsonify({
        "agent_name": config.agent_name,
        "provider_id": config.provider_id,
        "model_name": config.model_name,
        "temperature": config.temperature,
        "inherit_from": config.inherit_from,
    })


@app.route('/api/agents', methods=['POST'])
def api_set_agent():
    """設定 agent 配置"""
    data = request.json
    
    config = AgentModelConfig(
        agent_name=data["agent_name"],
        provider_id=data.get("provider_id"),
        model_name=data.get("model_name"),
        temperature=float(data.get("temperature", 0.2)),
        inherit_from=data.get("inherit_from"),
    )
    
    if set_agent_config(config):
        return jsonify({"success": True, "message": "Agent 配置成功"})
    else:
        return jsonify({"success": False, "error": "Agent 配置失敗"}), 400


@app.route('/api/agents/<agent_name>', methods=['DELETE'])
def api_delete_agent(agent_name: str):
    """刪除 agent 配置"""
    if delete_agent_config(agent_name):
        return jsonify({"success": True, "message": "Agent 配置刪除成功"})
    else:
        return jsonify({"success": False, "error": "Agent 配置刪除失敗"}), 400


@app.route('/api/default-config', methods=['GET'])
def api_get_default_config():
    """獲取默認配置"""
    config = get_agent_config("default", use_default=False)
    if not config:
        return jsonify({"success": True, "config": None})
    
    # 獲取提供者信息
    provider = get_provider(config.provider_id)
    provider_name = provider.name if provider else config.provider_id
    
    return jsonify({
        "success": True,
        "config": {
            "provider_id": config.provider_id,
            "provider_name": provider_name,
            "model_name": config.model_name,
            "temperature": config.temperature,
        }
    })


@app.route('/api/default-config', methods=['POST'])
def api_set_default_config():
    """設置默認配置"""
    data = request.json
    
    config = AgentModelConfig(
        agent_name="default",
        provider_id=data["provider_id"],
        model_name=data["model_name"],
        temperature=float(data.get("temperature", 0.2)),
        inherit_from=None,
    )
    
    if set_agent_config(config):
        return jsonify({"success": True, "message": "默認配置設置成功"})
    else:
        return jsonify({"success": False, "error": "默認配置設置失敗"}), 400


@app.route('/api/default-config', methods=['DELETE'])
def api_delete_default_config():
    """刪除默認配置"""
    if delete_agent_config("default"):
        return jsonify({"success": True, "message": "默認配置刪除成功"})
    else:
        return jsonify({"success": False, "error": "默認配置刪除失敗"}), 400


@app.route('/api/category-default-config/<path:category>', methods=['GET'])
def api_get_category_default_config(category: str):
    """獲取類別默認配置"""
    config = get_agent_config(f"default:{category}", use_default=False)
    if not config:
        return jsonify({"success": True, "config": None})
    
    # 獲取提供者信息
    provider = get_provider(config.provider_id)
    provider_name = provider.name if provider else config.provider_id
    
    return jsonify({
        "success": True,
        "config": {
            "provider_id": config.provider_id,
            "provider_name": provider_name,
            "model_name": config.model_name,
            "temperature": config.temperature,
        }
    })


@app.route('/api/category-default-config/<path:category>', methods=['POST'])
def api_set_category_default_config(category: str):
    """設置類別默認配置"""
    data = request.json
    
    config = AgentModelConfig(
        agent_name=f"default:{category}",
        provider_id=data["provider_id"],
        model_name=data["model_name"],
        temperature=float(data.get("temperature", 0.2)),
        inherit_from=None,
    )
    
    if set_agent_config(config):
        return jsonify({"success": True, "message": f"{category} 類別默認配置設置成功"})
    else:
        return jsonify({"success": False, "error": "類別默認配置設置失敗"}), 400


@app.route('/api/category-default-config/<path:category>', methods=['DELETE'])
def api_delete_category_default_config(category: str):
    """刪除類別默認配置"""
    if delete_agent_config(f"default:{category}"):
        return jsonify({"success": True, "message": f"{category} 類別默認配置刪除成功"})
    else:
        return jsonify({"success": False, "error": "類別默認配置刪除失敗"}), 400


@app.route('/api/agent-categories', methods=['GET'])
def api_get_agent_categories():
    """獲取所有 agent 類別列表"""
    agents = discover_agents()
    categories = sorted(list(set(agent["category"] for agent in agents)))
    return jsonify({"categories": categories})


@app.route('/api/subagent-default-config', methods=['GET'])
def api_get_subagent_default_config():
    """獲取 Subagent 整體默認配置"""
    config = get_agent_config("default:subagents", use_default=False)
    if not config:
        return jsonify({"success": True, "config": None})
    
    # 獲取提供者信息
    provider = get_provider(config.provider_id)
    provider_name = provider.name if provider else config.provider_id
    
    return jsonify({
        "success": True,
        "config": {
            "provider_id": config.provider_id,
            "provider_name": provider_name,
            "model_name": config.model_name,
            "temperature": config.temperature,
        }
    })


@app.route('/api/subagent-default-config', methods=['POST'])
def api_set_subagent_default_config():
    """設置 Subagent 整體默認配置"""
    data = request.json
    
    config = AgentModelConfig(
        agent_name="default:subagents",
        provider_id=data["provider_id"],
        model_name=data["model_name"],
        temperature=float(data.get("temperature", 0.2)),
        inherit_from=None,
    )
    
    if set_agent_config(config):
        return jsonify({"success": True, "message": "Subagent 整體默認配置設置成功"})
    else:
        return jsonify({"success": False, "error": "Subagent 整體默認配置設置失敗"}), 400


@app.route('/api/subagent-default-config', methods=['DELETE'])
def api_delete_subagent_default_config():
    """刪除 Subagent 整體默認配置"""
    if delete_agent_config("default:subagents"):
        return jsonify({"success": True, "message": "Subagent 整體默認配置刪除成功"})
    else:
        return jsonify({"success": False, "error": "Subagent 整體默認配置刪除失敗"}), 400



@app.route('/api/mcp-tools', methods=['GET'])
def api_list_mcp_tools():
    """List all custom MCP tools"""
    tools = list_mcp_tools()
    return jsonify([
        {
            "mcp_tool_id": t.mcp_tool_id,
            "name": t.name,
            "command": t.command,
            "args": t.args,
        }
        for t in tools
    ])


@app.route('/api/mcp-tools', methods=['POST'])
def api_add_mcp_tool():
    """Add or update a custom MCP tool"""
    data = request.json
    
    config = McpToolConfig(
        mcp_tool_id=data["mcp_tool_id"],
        name=data["name"],
        command=data["command"],
        args=data.get("args"),
    )
    
    if add_mcp_tool(config):
        return jsonify({"success": True, "message": "MCP 工具新增成功"})
    else:
        return jsonify({"success": False, "error": "MCP 工具新增失敗"}), 400


@app.route('/api/mcp-tools/<mcp_tool_id>', methods=['DELETE'])
def api_delete_mcp_tool(mcp_tool_id: str):
    """Delete a custom MCP tool"""
    if delete_mcp_tool(mcp_tool_id):
        return jsonify({"success": True, "message": "MCP 工具刪除成功"})
    else:
        return jsonify({"success": False, "error": "MCP 工具刪除失敗"}), 400


@app.route('/api/remote-mcps', methods=['GET'])
def api_list_remote_mcps():
    """List all remote MCP configurations"""
    try:
        mcps = list_remote_mcps()
        logger.debug(f"api_list_remote_mcps: found {len(mcps)} remote MCP entries")
        return jsonify([
            {
                "remote_mcp_id": m.remote_mcp_id,
                "name": m.name,
                "url": m.url,
            }
            for m in mcps
        ])
    except Exception as e:
        logger.exception(f"Failed to list remote MCPs: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/remote-mcps', methods=['POST'])
def api_add_remote_mcp():
    """Add or update a remote MCP configuration"""
    data = request.json
    
    config = RemoteMcpConfig(
        remote_mcp_id=data["remote_mcp_id"],
        name=data["name"],
        url=data["url"],
    )
    
    if add_remote_mcp(config):
        return jsonify({"success": True, "message": "遠端 MCP 新增成功"})
    else:
        return jsonify({"success": False, "error": "遠端 MCP 新增失敗"}), 400


@app.route('/api/remote-mcps/<remote_mcp_id>', methods=['DELETE'])
def api_delete_remote_mcp(remote_mcp_id: str):
    """Delete a remote MCP configuration"""
    if delete_remote_mcp(remote_mcp_id):
        return jsonify({"success": True, "message": "遠端 MCP 刪除成功"})
    else:
        return jsonify({"success": False, "error": "遠端 MCP 刪除失敗"}), 400


@app.route('/api/github/authenticate', methods=['POST'])
def api_github_authenticate():
    """啟動 GitHub OAuth 認證流程"""
    try:
        token = authenticate_github(use_device_flow=True)
        if token:
            return jsonify({"success": True, "token": token})
        else:
            return jsonify({"success": False, "error": "認證失敗"}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


def start_webui(host: str = "127.0.0.1", port: int = 5000, debug: bool = False):
    """
    啟動 Web UI 伺服器
    
    Args:
        host: 主機地址
        port: 端口號
        debug: 是否開啟除錯模式
    """
    # 禁用模板快取，確保每次都加載最新的 HTML
    app.config['TEMPLATES_AUTO_RELOAD'] = True
    app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
    
    print(f"\n{'=' * 60}")
    print(f"  配置管理 Web UI")
    print(f"{'=' * 60}")
    print(f"\n🌐 伺服器啟動在: http://{host}:{port}")
    print(f"   請在瀏覽器中打開此網址\n")
    print(f"   按 Ctrl+C 停止伺服器\n")
    
    # Blocking run (keeps existing behavior when called directly)
    app.run(host=host, port=port, debug=debug, use_reloader=False)


def _run_app(host: str, port: int, debug: bool) -> None:
    try:
        app.run(host=host, port=port, debug=debug, use_reloader=False)
    except Exception:
        # Suppress exceptions from threaded server shutdown
        pass


def ensure_webui_running(host: str = DEFAULT_WEBUI_HOST, port: int = DEFAULT_WEBUI_PORT, debug: bool = False) -> str:
    """
    Ensure the Web UI is running in a background thread. Returns the base URL.
    This is idempotent and safe to call multiple times.
    """
    global _webui_thread, _webui_url
    if _webui_thread and _webui_thread.is_alive():
        return _webui_url or f"http://{host}:{port}"

    _webui_url = f"http://{host}:{port}"
    _webui_thread = threading.Thread(target=_run_app, args=(host, port, debug), daemon=True)
    _webui_thread.start()
    return _webui_url


def open_config_in_browser(host: str = DEFAULT_WEBUI_HOST, port: int = DEFAULT_WEBUI_PORT, new: int = 2) -> bool:
    """Ensure server running and open config page in default browser."""
    url = ensure_webui_running(host=host, port=port)
    try:
        webbrowser.open(url, new=new)
        return True
    except Exception:
        return False


if __name__ == "__main__":
    start_webui(debug=True)
