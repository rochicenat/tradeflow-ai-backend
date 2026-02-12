from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import os

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)

engine = create_engine(DATABASE_URL)

with engine.connect() as conn:
    result = conn.execute(text("""
        SELECT email, plan, subscription_status, analyses_limit, analyses_used 
        FROM users 
        WHERE email = 'hafisaydin31@gmail.com'
    """))
    
    for row in result:
        print(f"Email: {row[0]}")
        print(f"Plan: {row[1]}")
        print(f"Status: {row[2]}")
        print(f"Limit: {row[3]}")
        print(f"Used: {row[4]}")
