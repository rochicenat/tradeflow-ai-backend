from fastapi import FastAPI, UploadFile, File, HTTPException, Header, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from database import User, get_db, init_db
from sqlalchemy.orm import Session
import os
import google.generativeai as genai
from dotenv import load_dotenv
from PIL import Image
import io
from passlib.context import CryptContext
from jose import JWTError, jwt
from datetime import datetime, timedelta
from typing import Optional

load_dotenv()

app = FastAPI(title="Trading Chart Analysis API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://tradeflow-ai-frontend-dkyc.vercel.app",
        "https://tradeflowai.cloud",
        "https://www.tradeflowai.cloud"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
model = genai.GenerativeModel('gemini-2.5-flash')

SECRET_KEY = "trading-chart-secret-key-2026"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Pydantic Models
class AnalysisResponse(BaseModel):
    analysis: str
    trend: str
    confidence: str

class UserCreate(BaseModel):
    email: str
    password: str
    name: str

class UserLogin(BaseModel):
    email: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

# Initialize database on startup
@app.on_event("startup")
def startup_event():
    init_db()
    print("🗄️ Database initialized!")

@app.get("/")
async def root():
    return {"message": "Trading Chart Analysis API is running"}

@app.post("/register", response_model=Token)
async def register(user: UserCreate, db: Session = Depends(get_db)):
    existing_user = db.query(User).filter(User.email == user.email).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    hashed_password = pwd_context.hash(user.password)
    new_user = User(
        email=user.email,
        name=user.name,
        hashed_password=hashed_password,
        plan="free",
        analyses_used=0
    )
    
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    access_token = create_access_token(data={"sub": user.email})
    return {"access_token": access_token, "token_type": "bearer"}

@app.post("/login", response_model=Token)
async def login(user: UserLogin, db: Session = Depends(get_db)):
    db_user = db.query(User).filter(User.email == user.email).first()
    if not db_user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    if not pwd_context.verify(user.password, db_user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    access_token = create_access_token(data={"sub": user.email})
    return {"access_token": access_token, "token_type": "bearer"}

@app.get("/me")
async def get_current_user_endpoint(authorization: Optional[str] = Header(None), db: Session = Depends(get_db)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    try:
        token = authorization.replace("Bearer ", "")
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email = payload.get("sub")
        if email is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        
        user = db.query(User).filter(User.email == email).first()
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        
        return {
            "email": user.email,
            "name": user.name,
            "plan": user.plan,
            "analyses_used": user.analyses_used,
            "subscription_status": user.subscription_status,
            "analyses_limit": user.analyses_limit,
        }
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

@app.post("/analyze-image", response_model=AnalysisResponse)
async def analyze_image(
    file: UploadFile = File(...),
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    try:
        if not authorization:
            raise HTTPException(status_code=401, detail="Not authenticated")
        
        token = authorization.replace("Bearer ", "")
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email = payload.get("sub")
        
        user = db.query(User).filter(User.email == email).first()
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")
        
        plan_limits = {
            "free": 3,
            "pro": 50,
            "premium": 999999
        }
        
        limit = plan_limits.get(user.plan, 3)
        
        if user.analyses_used >= limit:
            raise HTTPException(
                status_code=403,
                detail=f"Monthly limit reached. Upgrade to continue."
            )
        
        if not file.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail="File must be an image")
        
        image_data = await file.read()
        image = Image.open(io.BytesIO(image_data))
        
        prompt = """Analyze this trading chart and provide a detailed technical analysis.
IMPORTANT: Format your response EXACTLY like this (use these exact section headers):
**Support/Resistance Zones:**
* Immediate Resistance: [price level and description]
* Key Support: [price level and description]
* Additional levels if relevant
**Possible Breakout Areas:**
* Bullish Breakout: [conditions and price targets]
* Bearish Breakdown: [conditions and price targets]
**RSI or Indicator Signals:**
* [Indicator name]: [current reading and interpretation]
* [Additional indicators if visible]
**Trading Idea:**
* Entry: [suggested entry strategy]
* Stop Loss: [suggested stop loss level]
* Target: [suggested profit target]
* Risk Warning: [brief risk assessment]
First line must be ONLY: bullish, bearish, or sideways
Second line must be ONLY: low, medium, or high
Then provide the detailed analysis using the sections above.
"""
        
        response = model.generate_content([prompt, image])
        
        ai_response = response.text.strip()
        lines = ai_response.split('\n')
        
        trend = lines[0].strip().lower() if len(lines) > 0 else "sideways"
        confidence = lines[1].strip().lower() if len(lines) > 1 else "medium"
        analysis = '\n'.join(lines[2:]).strip() if len(lines) > 2 else ai_response
        
        if trend not in ["bullish", "bearish", "sideways"]:
            trend = "sideways"
        if confidence not in ["low", "medium", "high"]:
            confidence = "medium"
        
        user.analyses_used += 1
        db.commit()
        
        return AnalysisResponse(
            analysis=analysis,
            trend=trend,
            confidence=confidence
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error analyzing image: {str(e)}")

# Lemon Squeezy Payment Integration (ESKİ - KALACAK)
from lemon_squeezy import router as payment_router
app.include_router(payment_router)

# Webhook Integration (YENİ)
from webhook import router as webhook_router
app.include_router(webhook_router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

@app.get("/dashboard")
async def get_dashboard(authorization: Optional[str] = Header(None), db: Session = Depends(get_db)):
    """Dashboard bilgileri"""
    if not authorization:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    try:
        token = authorization.replace("Bearer ", "")
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email = payload.get("sub")
        
        user = db.query(User).filter(User.email == email).first()
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        
        # Plan limitleri
        plan_names = {
            "free": "Free Plan",
            "pro": "Pro Plan",
            "premium": "Premium Plan"
        }
        
        return {
            "email": user.email,
            "name": user.name,
            "plan": user.plan,
            "plan_name": plan_names.get(user.plan, "Free Plan"),
            "subscription_status": user.subscription_status,
            "analyses_limit": user.analyses_limit,
            "analyses_used": user.analyses_used,
            "analyses_limit": user.analyses_limit,
            "plan_started_at": user.plan_started_at.isoformat() if user.plan_started_at else None,
            "plan_ends_at": user.plan_ends_at.isoformat() if user.plan_ends_at else None,
        }
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
@app.post("/debug/upgrade-plan")
async def debug_upgrade_plan(
    plan: str,
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    """Manuel plan upgrade - sadece test için"""
    if not authorization:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    token = authorization.replace("Bearer ", "")
    payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    email = payload.get("sub")
    
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    plan_limits = {"free": 3, "pro": 50, "premium": 999999}
    
    if plan not in plan_limits:
        raise HTTPException(status_code=400, detail="Invalid plan")
    
    user.plan = plan
    user.subscription_status = "active"
    user.analyses_limit = plan_limits[plan]
    user.analyses_used = 0
    user.plan_started_at = datetime.utcnow()
    user.plan_ends_at = datetime.utcnow() + timedelta(days=30)
    
    db.commit()
    db.refresh(user)
    
    return {
        "message": "Plan updated",
        "email": user.email,
        "plan": user.plan,
        "analyses_limit": user.analyses_limit
    }
