"""
Agent discovery and management utilities.
Automatically discovers all agents in the project.
"""

from pathlib import Path
from typing import List, Dict


def discover_agents() -> List[Dict[str, str]]:
    """
    發現專案中的所有 agent
    
    Returns:
        List of agent info dicts with keys: name, category, description
    """
    agents = []
    
    # 主 Agent
    agents.append({
        "name": "main",
        "category": "core",
        "description": "主要 Agent",
    })
    
    # Co-Agents
    co_agents_dir = Path(__file__).parent.parent / "co_agents"
    if co_agents_dir.exists():
        for file in co_agents_dir.glob("*.py"):
            if file.stem not in ["__init__", "base"]:
                agent_name = file.stem.replace("_", "-")
                agents.append({
                    "name": agent_name,
                    "category": "co-agent",
                    "description": f"Co-Agent: {file.stem}",
                })
    
    # Sub-Agents (掃描 .md 文件，排除 README.md)
    sub_agents_dir = Path(__file__).parent.parent / "sub_agents"
    if sub_agents_dir.exists():
        for md_file in sub_agents_dir.rglob("*.md"):
            if md_file.name.lower() in ["readme.md", "agents.md"]:
                continue
            
            try:
                content = md_file.read_text(encoding="utf-8")
                
                # 解析 frontmatter 獲取名稱和描述
                agent_name = md_file.stem  # 預設使用檔名
                description = f"Sub-Agent: {agent_name}"
                category_name = md_file.parent.name
                
                # 簡單的 frontmatter 解析
                if content.startswith("---"):
                    lines = content.splitlines()
                    end_idx = None
                    for idx in range(1, len(lines)):
                        if lines[idx].strip() == "---":
                            end_idx = idx
                            break
                    
                    if end_idx:
                        # 解析 frontmatter
                        for line in lines[1:end_idx]:
                            if ":" in line:
                                key, value = line.split(":", 1)
                                key = key.strip().lower()
                                value = value.strip().strip('"\'')
                                if key == "name":
                                    agent_name = value
                                elif key == "description":
                                    description = value
                
                agents.append({
                    "name": agent_name,
                    "category": f"sub-agent/{category_name}",
                    "description": description,
                })
            except Exception as e:
                # 靜默忽略錯誤
                pass
    
    return sorted(agents, key=lambda x: (x["category"], x["name"]))


def get_agent_categories() -> Dict[str, List[str]]:
    """
    獲取按類別分組的 agent 列表
    
    Returns:
        Dict mapping category to list of agent names
    """
    agents = discover_agents()
    categories = {}
    
    for agent in agents:
        category = agent["category"]
        if category not in categories:
            categories[category] = []
        categories[category].append(agent["name"])
    
    return categories


def get_all_agent_names() -> List[str]:
    """
    獲取所有 agent 名稱列表
    
    Returns:
        List of agent names
    """
    return [agent["name"] for agent in discover_agents()]


if __name__ == "__main__":
    # 測試
    print("發現的 Agents:")
    print("=" * 60)
    
    agents = discover_agents()
    current_category = None
    
    for agent in agents:
        if agent["category"] != current_category:
            current_category = agent["category"]
            print(f"\n{current_category.upper()}:")
        print(f"  - {agent['name']}: {agent['description']}")
    
    print(f"\n總共: {len(agents)} 個 agents")
