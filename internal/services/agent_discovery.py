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
