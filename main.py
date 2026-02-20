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
from pydantic import BaseModel
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
def verify_password(plain, hashed):
    return pwd_context.verify(plain, hashed)
def get_password_hash(password):
    return pwd_context.hash(password)
def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
def get_current_user(authorization: str = Header(...), db: Session = Depends(get_db)):
    try:
        token = authorization.replace("Bearer ", "")
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email = payload.get("sub")
        if not email:
            raise HTTPException(status_code=401, detail="Invalid token")
        user = db.query(User).filter(User.email == email).first()
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return user
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
class RegisterRequest(BaseModel):
    name: str
    email: str
    password: str
@app.post("/register")
def register(name: str = Form(...), email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(name=name, email=email, hashed_password=get_password_hash(password))
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_access_token({"sub": user.email})
    return {"access_token": token, "token_type": "bearer"}
@app.post("/login")
def login(username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == username).first()
    if not user or not verify_password(password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_access_token({"sub": user.email})
    return {"access_token": token, "token_type": "bearer"}
@app.get("/me")
def get_me(current_user: User = Depends(get_current_user)):
    return {
        "email": current_user.email,
        "name": current_user.name,
        "plan": current_user.plan,
        "analyses_used": current_user.analyses_used,
        "analyses_limit": {"free": 3, "pro": 50, "premium": 999999}.get(current_user.plan, 3),
        "subscription_status": current_user.subscription_status if hasattr(current_user, 'subscription_status') else "inactive"
    }
@app.post("/analyze-image")
async def analyze_image(
    file: UploadFile = File(...),
    analysis_type: str = Form(default="swing"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    plan_limits = {"free": 3, "pro": 50, "premium": 999999}
    limit = plan_limits.get(current_user.plan, 3)
    if current_user.analyses_used >= limit:
        raise HTTPException(status_code=403, detail="Monthly analysis limit reached")
    try:
        image_bytes = await file.read()
        image = Image.open(io.BytesIO(image_bytes))
        model = genai.GenerativeModel('gemini-2.5-flash')
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
        if "NO" in validation_text or "NOT" in validation_text:
            raise HTTPException(
                status_code=400,
                detail="❌ This image does not appear to be a trading chart. Please upload a valid price chart, candlestick chart, or financial graph showing market data."
            )
        if analysis_type == "scalp":
            analysis_prompt = """Analyze this trading chart for SCALP TRADING (1-15 minute timeframes, quick entries and exits).
Focus on:
- Short-term momentum and micro price action
- Immediate support/resistance levels
- Quick entry and exit points
- Short-term indicators (RSI, MACD, volume spikes)
- Tight stop losses and small take profits
Respond in this EXACT format:
Line 1: UPTREND or DOWNTREND or NEUTRAL
Line 2: low or medium or high
Line 3: Reference: [price]
Line 4: Lower: [price]
Line 5: Upper: [price]
**Key Levels:**
* [level 1]
* [level 2]
**Pattern Analysis:**
* [short-term pattern or signal]
* [momentum indicator reading]
**Risk Assessment:**
* [win probability for scalp]
* [risk/reward ratio]
Educational analysis only, not financial advice."""
        else:
            analysis_prompt = """Analyze this trading chart for SWING TRADING (multi-day trends, holding positions days to weeks).
Focus on:
- Multi-day trend direction and strength
- Major support/resistance zones
- Swing highs and lows
- Trend-following indicators (MA crossovers, trend lines)
- Wider stop losses with larger take profit targets
Respond in this EXACT format:
Line 1: UPTREND or DOWNTREND or NEUTRAL
Line 2: low or medium or high
Line 3: Reference: [price]
Line 4: Lower: [price]
Line 5: Upper: [price]
**Key Levels:**
* [level 1]
* [level 2]
**Pattern Analysis:**
* [multi-day pattern or trend]
* [trend indicator reading]
**Risk Assessment:**
* [win probability for swing]
* [risk/reward ratio]
Educational analysis only, not financial advice."""
        response = model.generate_content([analysis_prompt, image])
        analysis_text = response.text
        lines = analysis_text.split('\n')
        trend_line = lines[0].strip().upper() if len(lines) > 0 else "NEUTRAL"
        confidence_line = lines[1].strip().lower() if len(lines) > 1 else "medium"
        trend_map = {"UPTREND": "bullish", "DOWNTREND": "bearish", "NEUTRAL": "sideways"}
        trend = trend_map.get(trend_line, "sideways")
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
        raise
    except Exception as e:
        print(f"ERROR: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")
@app.get("/analysis-history")
def get_history(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    analyses = db.query(Analysis).filter(Analysis.user_email == current_user.email).order_by(Analysis.created_at.desc()).limit(50).all()
    return [{"id": a.id, "trend": a.trend, "confidence": a.confidence, "analysis_text": a.analysis_text[:200], "created_at": a.created_at.isoformat()} for a in analyses]
@app.post("/debug/upgrade-plan")
def upgrade_plan(email: str = Form(...), plan: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.plan = plan
    db.commit()
    return {"message": f"Plan updated to {plan}"}
