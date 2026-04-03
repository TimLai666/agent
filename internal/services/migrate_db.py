"""
Database migration script to add inheritance support to agent_configs table.
Run this script to update existing database schema.
"""

import sqlite3
from internal.paths import TIM_AGENT_CONFIG_DIR

DB_PATH = TIM_AGENT_CONFIG_DIR / "config.db"


def migrate_database():
    """Add inherit_from column to agent_configs table"""
    if not DB_PATH.exists():
        print("數據庫不存在，無需遷移")
        return
    
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    
    try:
        # 檢查 inherit_from 欄位是否已存在
        cursor.execute("PRAGMA table_info(agent_configs)")
        columns = [row[1] for row in cursor.fetchall()]
        
        if "inherit_from" in columns:
            print("✅ 數據庫已經是最新版本")
            return
        
        print("開始遷移數據庫...")
        
        # 創建新表
        cursor.execute("""
            CREATE TABLE agent_configs_new (
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
        
        # 複製數據
        cursor.execute("""
            INSERT INTO agent_configs_new 
            (agent_name, provider_id, model_name, temperature, created_at, updated_at)
            SELECT agent_name, provider_id, model_name, temperature, created_at, updated_at
            FROM agent_configs
        """)
        
        # 刪除舊表
        cursor.execute("DROP TABLE agent_configs")
        
        # 重命名新表
        cursor.execute("ALTER TABLE agent_configs_new RENAME TO agent_configs")
        
        # 重建索引
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_agent_provider 
            ON agent_configs(provider_id)
        """)
        
        conn.commit()
        print("✅ 數據庫遷移成功！")
        print("   已添加 inherit_from 欄位以支持配置繼承")
        
    except Exception as e:
        conn.rollback()
        print(f"❌ 遷移失敗: {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    print("=" * 60)
    print("  Agent 配置數據庫遷移")
    print("=" * 60)
    print(f"\n數據庫位置: {DB_PATH}\n")
    
    migrate_database()
    
    print("\n遷移完成！")
