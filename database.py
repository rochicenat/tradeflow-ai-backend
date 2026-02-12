from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import os
from dotenv import load_dotenv

# .env dosyasını yükle
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

# Railway PostgreSQL URL'si postgresql:// ile başlar ama SQLAlchemy postgresql+psycopg2:// istiyor
if DATABASE_URL and DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# User Model - GÜNCELLENMIŞ
class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    hashed_password = Column(String, nullable=False)
    
    # Subscription bilgileri
    plan = Column(String, default="free")  # free, pro, premium
    subscription_id = Column(String, nullable=True)  # Lemon Squeezy subscription ID
    subscription_status = Column(String, default="inactive")  # active, cancelled, expired, inactive
    customer_id = Column(String, nullable=True)  # Lemon Squeezy customer ID
    
    # Tarihler
    plan_started_at = Column(DateTime, nullable=True)
    plan_ends_at = Column(DateTime, nullable=True)
    
    # Limit bilgileri
    analyses_used = Column(Integer, default=0)
    analyses_limit = Column(Integer, default=3)
    
    # Timestamp
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

# Database helper functions
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    """Create all tables"""
    Base.metadata.create_all(bind=engine)
    print("✅ Database tables created!")

if __name__ == "__main__":
    init_db()
