from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from database import User, Analysis, SessionLocal, engine, Base
from passlib.context import CryptContext
from jose import JWTError, jwt
from datetime import datetime, timedelta
import google.generativeai as genai
from PIL import Image
import io
import os
from dotenv import load_dotenv

load_dotenv()

# Database
Base.metadata.create_all(bind=engine)

# Security
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 30

# Gemini AI
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
genai.configure(api_key=GOOGLE_API_KEY)

app = FastAPI()

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://tradeflow-ai-frontend.vercel.app",
        "https://tradeflowai.vercel.app",
        "https://tradeflowai.cloud",
        "https://www.tradeflowai.cloud"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def get_current_user(authorization: str = Header(None), db: Session = Depends(get_db)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    token = authorization.replace("Bearer ", "")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    user = db.query(User).filter(User.email == email).first()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    
    return user

@app.get("/")
def read_root():
    return {"message": "DataFlow Analytics API"}

@app.post("/register")
def register(email: str, password: str, name: str, db: Session = Depends(get_db)):
    existing_user = db.query(User).filter(User.email == email).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    hashed_password = get_password_hash(password)
    user = User(
        email=email,
        hashed_password=hashed_password,
        name=name,
        plan="free",
        analyses_limit=3,
        analyses_used=0,
        subscription_status="inactive"
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    
    access_token = create_access_token(data={"sub": user.email})
    return {"access_token": access_token, "token_type": "bearer"}

@app.post("/login")
def login(email: str, password: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    access_token = create_access_token(data={"sub": user.email})
    return {"access_token": access_token, "token_type": "bearer"}

@app.get("/me")
def get_me(current_user: User = Depends(get_current_user)):
    return {
        "email": current_user.email,
        "name": current_user.name,
        "plan": current_user.plan,
        "analyses_used": current_user.analyses_used,
        "analyses_limit": current_user.analyses_limit,
        "subscription_status": current_user.subscription_status
    }

@app.post("/analyze-image")
async def analyze_image(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Check limit
    plan_limits = {"free": 3, "pro": 50, "premium": 999999}
    limit = plan_limits.get(current_user.plan, 3)
    
    if current_user.analyses_used >= limit:
        raise HTTPException(status_code=403, detail="Monthly analysis limit reached. Please upgrade your plan.")
    
    # Process image
    try:
        image_data = await file.read()
        image = Image.open(io.BytesIO(image_data))
        
        model = genai.GenerativeModel('gemini-2.0-flash-exp')
        
        prompt = """Analyze this market chart and provide educational data analysis.

IMPORTANT: Your response must follow this EXACT format:

Line 1: ONLY one word - UPTREND, DOWNTREND, or NEUTRAL
Line 2: ONLY one word - low, medium, or high (statistical confidence level)
Line 3: Reference level (e.g., "Reference: 45,230")
Line 4: Lower boundary (e.g., "Lower: 44,800")
Line 5: Upper target (e.g., "Upper: 46,500")

Then provide brief educational analysis in these sections (max 2 bullet points each):

**Key Levels:**
* [Immediate support/resistance zones]
* [Critical price boundaries]

**Pattern Analysis:**
* [Why this pattern - one sentence]
* [Key indicator supporting this - one sentence]

**Risk Assessment:**
* [Probability level: Low/Medium/High]
* [Risk/Reward ratio if applicable]

Keep it SHORT, EDUCATIONAL, and DATA-FOCUSED. This is for research purposes only.
"""
        
        response = model.generate_content([prompt, image])
        analysis_text = response.text
        
        # Parse trend and confidence
        lines = analysis_text.split('\n')
        trend_line = lines[0].strip() if len(lines) > 0 else "NEUTRAL"
        confidence_line = lines[1].strip() if len(lines) > 1 else "medium"
        
        # Map to expected format
        trend_map = {
            "UPTREND": "bullish",
            "DOWNTREND": "bearish", 
            "NEUTRAL": "sideways"
        }
        trend = trend_map.get(trend_line.upper(), "sideways")
        
        # Save to history
        analysis_record = Analysis(
            user_email=current_user.email,
            trend=trend,
            confidence=confidence_line,
            analysis_text=analysis_text
        )
        db.add(analysis_record)
        
        # Increment usage
        current_user.analyses_used += 1
        db.commit()
        
        return {
            "analysis": analysis_text,
            "trend": trend,
            "confidence": confidence_line
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/analysis-history")
def get_analysis_history(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    analyses = db.query(Analysis).filter(
        Analysis.user_email == current_user.email
    ).order_by(Analysis.created_at.desc()).limit(50).all()
    
    return [
        {
            "id": analysis.id,
            "trend": analysis.trend,
            "confidence": analysis.confidence,
            "analysis_text": analysis.analysis_text[:200] if len(analysis.analysis_text) > 200 else analysis.analysis_text,
            "created_at": analysis.created_at.isoformat()
        }
        for analysis in analyses
    ]

@app.post("/debug/upgrade-plan")
def debug_upgrade_plan(
    plan: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    plan_limits = {"free": 3, "pro": 50, "premium": 999999}
    
    if plan not in plan_limits:
        raise HTTPException(status_code=400, detail="Invalid plan")
    
    current_user.plan = plan
    current_user.analyses_limit = plan_limits[plan]
    current_user.subscription_status = "active" if plan != "free" else "inactive"
    db.commit()
    
    return {
        "message": "Plan updated",
        "email": current_user.email,
        "plan": current_user.plan,
        "analyses_limit": current_user.analyses_limit
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
