from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, Header, Form
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
Base.metadata.create_all(bind=engine)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
SECRET_KEY = os.getenv("SECRET_KEY", "fallback-secret-key")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 30

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
genai.configure(api_key=GOOGLE_API_KEY)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(authorization: str = Header(None), db: Session = Depends(get_db)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    token = authorization.replace("Bearer ", "")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email = payload.get("sub")
        if not email:
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user

@app.get("/")
def read_root():
    return {"message": "TradeFlow AI API", "status": "running"}

@app.post("/register")
def register(email: str = Form(...), password: str = Form(...), name: str = Form(...), db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    
    user = User(
        email=email,
        hashed_password=get_password_hash(password),
        name=name,
        plan="free",
        analyses_limit=3,
        analyses_used=0,
        subscription_status="inactive"
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"access_token": create_access_token(data={"sub": user.email}), "token_type": "bearer"}

@app.post("/login")
def login(email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {"access_token": create_access_token(data={"sub": user.email}), "token_type": "bearer"}

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
async def analyze_image(file: UploadFile = File(...), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    plan_limits = {"free": 3, "pro": 50, "premium": 999999}
    limit = plan_limits.get(current_user.plan, 3)
    
    if current_user.analyses_used >= limit:
        raise HTTPException(status_code=403, detail="Monthly analysis limit reached")
    
    try:
        image_bytes = await file.read()
        image = Image.open(io.BytesIO(image_bytes))
        
        # Gemini model
        model = genai.GenerativeModel('gemini-2.5-flash')
        
        # STEP 1: Validate if it's a trading chart
        validation_prompt = """Is this image a trading chart, price chart, candlestick chart, or financial market graph?

Answer ONLY "YES" or "NO".

YES if the image contains:
- Candlestick charts
- Line charts with price movements
- Bar charts with OHLC data
- Technical indicators (MA, RSI, etc.)
- Price levels and timeframes
- Forex, crypto, stock, or commodity charts

NO if the image is:
- A person's photo
- Random objects
- Food, animals, nature
- Screenshots without charts
- Text documents
- Non-financial content

Answer:"""
        
        validation_response = model.generate_content([validation_prompt, image])
        validation_text = validation_response.text.strip().upper()
        
        # Check if it's NOT a chart
        if "NO" in validation_text or "NOT" in validation_text:
            raise HTTPException(
                status_code=400,
                detail="❌ This image does not appear to be a trading chart. Please upload a valid price chart, candlestick chart, or financial graph showing market data."
            )
        
        # STEP 2: If validated, proceed with full analysis
        analysis_prompt = """Analyze this trading chart. Respond in this EXACT format:

Line 1: UPTREND or DOWNTREND or NEUTRAL
Line 2: low or medium or high
Line 3: Reference: [price]
Line 4: Lower: [price]
Line 5: Upper: [price]

**Key Levels:**
* [level 1]
* [level 2]

**Pattern Analysis:**
* [pattern]
* [indicator]

**Risk Assessment:**
* [probability]
* [ratio]

Educational analysis only, not financial advice."""
        
        response = model.generate_content([analysis_prompt, image])
        analysis_text = response.text
        
        lines = analysis_text.split('\n')
        trend_line = lines[0].strip().upper() if len(lines) > 0 else "NEUTRAL"
        confidence_line = lines[1].strip().lower() if len(lines) > 1 else "medium"
        
        trend_map = {"UPTREND": "bullish", "DOWNTREND": "bearish", "NEUTRAL": "sideways"}
        trend = trend_map.get(trend_line, "sideways")
        
        # Save to history
        record = Analysis(
            user_email=current_user.email,
            trend=trend,
            confidence=confidence_line,
            analysis_text=analysis_text
        )
        db.add(record)
        current_user.analyses_used += 1
        db.commit()
        
        return {"analysis": analysis_text, "trend": trend, "confidence": confidence_line}
        
    except HTTPException:
        # Re-raise validation errors
        raise
    except Exception as e:
        print(f"ERROR: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")

@app.get("/analysis-history")
def get_history(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    analyses = db.query(Analysis).filter(Analysis.user_email == current_user.email).order_by(Analysis.created_at.desc()).limit(50).all()
    return [{"id": a.id, "trend": a.trend, "confidence": a.confidence, "analysis_text": a.analysis_text[:200], "created_at": a.created_at.isoformat()} for a in analyses]

@app.post("/debug/upgrade-plan")
def upgrade_plan(plan: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    plan_limits = {"free": 3, "pro": 50, "premium": 999999}
    if plan not in plan_limits:
        raise HTTPException(status_code=400, detail="Invalid plan")
    
    current_user.plan = plan
    current_user.analyses_limit = plan_limits[plan]
    current_user.subscription_status = "active" if plan != "free" else "inactive"
    db.commit()
    return {"message": "Plan updated", "plan": plan}

if __name__ == "__main__":
    import uvicorn

@app.delete("/delete-analysis/{analysis_id}")
def delete_analysis(analysis_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    analysis = db.query(Analysis).filter(
        Analysis.id == analysis_id,
        Analysis.user_email == current_user.email
    ).first()
    
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")
    
    db.delete(analysis)
    db.commit()
    return {"message": "Analysis deleted successfully"}

@app.post("/update-profile")
def update_profile(name: str = Form(...), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    current_user.name = name
    db.commit()
    return {"message": "Profile updated successfully", "name": name}

@app.post("/update-profile")
def update_profile(name: str = Form(...), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    current_user.name = name
    db.commit()
    return {"message": "Profile updated successfully", "name": name}
