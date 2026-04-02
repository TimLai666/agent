"""
Agent discovery and management utilities.
Automatically discovers all agents in the project.
"""

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
