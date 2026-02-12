from sqlalchemy import create_engine, text, inspect

# Direkt PUBLIC URL kullan
DATABASE_URL = "postgresql+psycopg2://postgres:dXfiHKBuQBLlXbwqheWXkbXcfkfeUwpR@maglev.proxy.rlwy.net:28024/railway"

print(f"🔗 Bağlanıyor...")

def add_missing_columns():
    engine = create_engine(DATABASE_URL)
    inspector = inspect(engine)
    
    # Mevcut kolonları al
    existing_columns = [col['name'] for col in inspector.get_columns('users')]
    print(f"\n✅ Mevcut kolonlar: {existing_columns}\n")
    
    # Eklenecek kolonlar
    new_columns = {
        'customer_id': 'VARCHAR(255)',
        'plan_started_at': 'TIMESTAMP',
        'plan_ends_at': 'TIMESTAMP',
        'analyses_limit': 'INTEGER DEFAULT 3'
    }
    
    with engine.connect() as conn:
        for col_name, col_type in new_columns.items():
            if col_name not in existing_columns:
                try:
                    sql = f"ALTER TABLE users ADD COLUMN {col_name} {col_type}"
                    conn.execute(text(sql))
                    conn.commit()
                    print(f"✅ Eklendi: {col_name} ({col_type})")
                except Exception as e:
                    print(f"❌ Hata ({col_name}): {e}")
            else:
                print(f"⚠️ Zaten var: {col_name}")
        
        # analyses_limit NULL olanları güncelle
        try:
            conn.execute(text("UPDATE users SET analyses_limit = 3 WHERE analyses_limit IS NULL"))
            conn.commit()
            print("\n✅ analyses_limit NULL değerleri güncellendi")
        except:
            pass
    
    print("\n🎉 Migration tamamlandı!")

if __name__ == "__main__":
    add_missing_columns()
