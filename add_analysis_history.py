from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey
from sqlalchemy.orm import relationship
from database import Base, engine
from datetime import datetime

class Analysis(Base):
    __tablename__ = "analyses"
    
    id = Column(Integer, primary_key=True, index=True)
    user_email = Column(String, ForeignKey("users.email"))
    trend = Column(String)
    confidence = Column(String)
    analysis_text = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User", back_populates="analyses")

# Add relationship to User model
from database import User
User.analyses = relationship("Analysis", back_populates="user")

# Create table
Base.metadata.create_all(bind=engine)
print("Analysis table created!")
