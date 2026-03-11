from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, Header, Form, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from database import User, Analysis, SessionLocal, engine, Base
from passlib.context import CryptContext
from jose import JWTError, jwt
from datetime import datetime, timedelta
from google import genai
from google.genai import types
from PIL import Image
import io
import os
import hmac
import httpx
import hashlib
import json
from pydantic import BaseModel
from dotenv import load_dotenv
load_dotenv()

Base.metadata.create_all(bind=engine)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
SECRET_KEY = os.getenv("SECRET_KEY", "fallback-secret-key")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 30
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
LEMONSQUEEZY_WEBHOOK_SECRET = os.getenv("LEMONSQUEEZY_WEBHOOK_SECRET")

VARIANT_PLAN_MAP = {
    "47621ebf-7c5e-4b6e-bbc9-d6bee626b2d4": "pro",
    "60423ba8-053a-4d04-a924-69b6aaae30e3": "pro",
}

PLAN_LIMITS = {
    "free": 3,
    "pro": 100000,
    "premium": 100000
}

client = genai.Client(api_key=GOOGLE_API_KEY)
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://www.tradeflowai.cloud"],
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

def check_and_reset_monthly(user, db):
    from datetime import datetime
    now = datetime.utcnow()
    last_reset = user.last_reset_at or user.plan_started_at or user.created_at
    if last_reset and (now - last_reset).days >= 30:
        user.analyses_used = 0
        user.last_reset_at = now
        db.commit()

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
async def register(name: str = Form(...), email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    verification_token = secrets.token_urlsafe(32)
    user = User(name=name, email=email, hashed_password=get_password_hash(password), is_verified=False, verification_token=verification_token)
    db.add(user)
    db.commit()
    db.refresh(user)
    verify_link = f"https://tradeflow-ai-backend-production.up.railway.app/verify-email?token={verification_token}"
    body = f"""<html><body><h2>Verify your email</h2><p>Click below to verify your TradeFlow AI account.</p><a href="{verify_link}" style="background:#f97316;color:white;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:bold;">Verify Email</a></body></html>"""
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
                json={"from": "TradeFlow AI <noreply@tradeflowai.cloud>", "to": [email], "subject": "Verify your TradeFlow AI account", "html": body}
            )
    except Exception as e:
        print(f"Verification email error: {e}")
    return {"message": "Registration successful. Please check your email to verify your account."}

@app.post("/login")
def login(username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == username).first()
    if not user or not verify_password(password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user.is_verified:
        raise HTTPException(status_code=403, detail="Please verify your email before logging in")
    token = create_access_token({"sub": user.email})
    return {"access_token": token, "token_type": "bearer"}

@app.get("/me")
def get_me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    check_and_reset_monthly(current_user, db)
    return {
        "email": current_user.email,
        "name": current_user.name,
        "plan": current_user.plan,
        "analyses_used": current_user.analyses_used,
        "analyses_limit": PLAN_LIMITS.get(current_user.plan, 3),
        "subscription_status": current_user.subscription_status,
        "subscription_id": current_user.subscription_id,
    }

@app.post("/analyze-image")
async def analyze_image(
    file: UploadFile = File(...),
    analysis_type: str = Form(default="swing"),
    account_size: str = Form(default=""),
    risk_percent: str = Form(default="2"),
    leverage: str = Form(default="1"),
    order_type: str = Form(default="market"),
    sl_type: str = Form(default="fixed"),
    indicators: str = Form(default=""),
    session: str = Form(default=""),
    asset_type: str = Form(default=""),
    rr_ratio: str = Form(default="1:2"),
    timeframe: str = Form(default=""),
    language: str = Form(default="en"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    check_and_reset_monthly(current_user, db)
    limit = PLAN_LIMITS.get(current_user.plan, 3)
    if current_user.analyses_used >= limit:
        raise HTTPException(status_code=403, detail="Monthly analysis limit reached")
    try:
        image_bytes = await file.read()
        image = Image.open(io.BytesIO(image_bytes))
        
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
        validation_response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[validation_prompt, types.Part.from_bytes(data=image_bytes, mime_type=file.content_type)]
    )
        validation_text = validation_response.text.strip().upper()
        if "NO" in validation_text or "NOT" in validation_text:
            raise HTTPException(
                status_code=400,
                detail="❌ This image does not appear to be a trading chart. Please upload a valid price chart, candlestick chart, or financial graph showing market data."
            )
        lang_instruction = "Respond in Turkish language." if language == "tr" else ""
        trading_params = ""
        try:
            params_parts = []
            if account_size:
                acc = float(account_size)
                risk = float(risk_percent) / 100
                lev = float(leverage)
                risk_amount = acc * risk
                position_size = risk_amount * lev
                params_parts.append(f"- Account Size: ${acc:,.0f}")
                params_parts.append(f"- Risk Per Trade: {risk_percent}% = ${risk_amount:,.0f}")
                params_parts.append(f"- Leverage: {lev}x")
                params_parts.append(f"- Max Position Size: ${position_size:,.0f}")
            if order_type:
                params_parts.append(f"- Order Type: {order_type.capitalize()}")
            if sl_type:
                params_parts.append(f"- Stop-Loss Type: {'ATR-based (dynamic)' if sl_type == 'atr' else 'Fixed (pips)'}")
            if indicators:
                params_parts.append(f"- Preferred Indicators: {indicators}")
            if session:
                params_parts.append(f"- Trading Session: {session.upper()}")
            if asset_type:
                params_parts.append(f"- Asset Type: {asset_type.capitalize()}")
            if rr_ratio:
                params_parts.append(f"- Desired R:R Ratio: {rr_ratio}")
            if timeframe:
                params_parts.append(f"- Chart Timeframe: {timeframe}")
            if params_parts:
                trading_params = "\nTRADER PARAMETERS (tailor your analysis to these):\n" + "\n".join(params_parts) + "\nUse these parameters to personalize entry, exit, position sizing and risk management."
        except:
            pass
        if analysis_type in ("scalp_premium", "swing_premium"):
            if analysis_type == "scalp_premium":
                analysis_prompt = f"""You are an expert scalp trader. Analyze this trading chart for PREMIUM SCALP TRADING analysis.
Analyze the chart and respond in this EXACT format (no extra text):
UPTREND or DOWNTREND or NEUTRAL
low or medium or high
Reference: [current price or entry zone]
Lower: [stop loss price - tight, 3-10 pips away]
Upper: [take profit price - realistic scalp target]
**Key Levels:**
* [immediate support level with price]
* [immediate resistance level with price]
* [any nearby liquidity zone]
**Pattern Analysis:**
* [candlestick pattern visible]
* [momentum signal]
* [microstructure - break of structure, liquidity grab]
**Breakout & Retest:**
* [any breakout level visible and direction]
* [retest confirmation - yes/no and explanation]
* [trend line break if visible]
**Indicators:**
* [RSI value estimate and signal - overbought/oversold/neutral]
* [MA/EMA alignment - price above/below key MAs]
* [Volume analysis - above/below average, climax volume]
**Fibonacci:**
* [key Fibonacci retracement level price if visible]
* [Fibonacci extension target if applicable]
**Risk Assessment:**
* [win probability % for this scalp setup]
* [risk/reward ratio]
* [recommended position size note]
**Psychology & Trade Plan:**
* [market sentiment - fear/greed/neutral]
* [recommended entry trigger - exact condition to enter]
* [trade management - when to move stop to breakeven]
* [invalidation level - when to cancel the trade]
{trading_params}
{lang_instruction}
Educational analysis only, not financial advice."""
            else:
                analysis_prompt = f"""You are an expert swing trader. Analyze this trading chart for PREMIUM SWING TRADING analysis.
Analyze the chart and respond in this EXACT format (no extra text):
UPTREND or DOWNTREND or NEUTRAL
low or medium or high
Reference: [current price or entry zone]
Lower: [stop loss price - below key support/resistance]
Upper: [take profit price - next major level]
**Key Levels:**
* [major support zone with price]
* [major resistance zone with price]
* [weekly/daily key level if visible]
**Pattern Analysis:**
* [chart pattern - bull flag, head & shoulders, double bottom, triangle]
* [trend indicator - MA alignment, trend line break]
* [confluence factors - multiple timeframe alignment]
**Breakout & Retest:**
* [any breakout level visible and direction]
* [retest confirmation - yes/no and explanation]
* [trend line break if visible]
**Indicators:**
* [RSI value estimate and signal - overbought/oversold/neutral]
* [MA/EMA alignment - price above/below 20/50/200 MA]
* [Volume analysis - confirmation or divergence]
**Fibonacci:**
* [key Fibonacci retracement level price]
* [Fibonacci extension target]
**Risk Assessment:**
* [win probability % for this swing setup]
* [risk/reward ratio]
* [market condition note - trending/ranging/choppy]
**Psychology & Trade Plan:**
* [market sentiment - fear/greed/neutral]
* [recommended entry trigger - exact condition to enter]
* [trade management - partial profits, trailing stop]
* [invalidation level - when to cancel the trade]
{trading_params}
{lang_instruction}
Educational analysis only, not financial advice."""
        elif analysis_type == "scalp":
            analysis_prompt = """You are an expert scalp trader. Analyze this trading chart for SCALP TRADING (1-15 minute timeframes).

SCALP TRADING RULES:
- Trades last 1-30 minutes maximum
- Target: 5-20 pips / 0.1-0.5% price move
- Stop loss: very tight, 3-10 pips
- High win rate required (60%+)
- Entry must be precise, momentum-based

Analyze the chart and respond in this EXACT format (no extra text):

UPTREND or DOWNTREND or NEUTRAL
low or medium or high
Reference: [current price or entry zone]
Lower: [stop loss price - tight, 3-10 pips away]
Upper: [take profit price - realistic scalp target]

**Key Levels:**
* [immediate support level with price]
* [immediate resistance level with price]
* [any nearby liquidity zone]

**Pattern Analysis:**
* [candlestick pattern visible - e.g. engulfing, pin bar, doji]
* [momentum signal - RSI overbought/oversold, MACD cross, volume spike]
* [microstructure - break of structure, liquidity grab, fake-out]

**Risk Assessment:**
* [win probability % for this scalp setup]
* [risk/reward ratio - e.g. 1:2]
* [recommended position size note - high/medium/low risk]
**Breakout & Retest:**
* [any breakout level visible and direction]
* [retest confirmation - yes/no]
* [trend line break if visible]
**Indicators:**
* [RSI value and signal - overbought/oversold/neutral]
* [MA/EMA alignment - price above/below key MAs]
* [Volume - above/below average]
**Fibonacci:**
* [key Fibonacci retracement level if visible]
* [Fibonacci extension target]
**Psychology & Trade Plan:**
* [market sentiment - fear/greed/neutral]
* [entry trigger - exact condition]
* [invalidation level]
**Smart Money Concepts:**
* [Order Blocks: nearest bullish/bearish OB with price level]
* [Fair Value Gap (FVG): any unfilled FVG visible and direction]
* [Liquidity Sweep: recent high/low swept - yes/no]
* [BOS or CHoCH visible - direction]
* [Partial TP1 at 1:1, TP2 at full target, move SL to breakeven after TP1]
{trading_params}
{lang_instruction}
Educational analysis only, not financial advice."""
        else:
            analysis_prompt = f"""You are an expert swing trader. Analyze this trading chart for SWING TRADING (holding positions 2-10 days).

SWING TRADING RULES:
- Trades last 2-10 days
- Target: 2-8% price move or 50-200 pips
- Stop loss: wider, below/above key structure
- Look for high-probability setups at key zones
- Trend confirmation required

Analyze the chart and respond in this EXACT format (no extra text):

UPTREND or DOWNTREND or NEUTRAL
low or medium or high
Reference: [current price or entry zone]
Lower: [stop loss price - below key support/resistance]
Upper: [take profit price - next major level]

**Key Levels:**
* [major support zone with price]
* [major resistance zone with price]
* [weekly/daily key level if visible]

**Pattern Analysis:**
* [chart pattern - e.g. bull flag, head & shoulders, double bottom, triangle]
* [trend indicator - MA alignment, trend line break, higher highs/lows]
* [confluence factors - multiple timeframe alignment, volume confirmation]

**Risk Assessment:**
* [win probability % for this swing setup]
* [risk/reward ratio - e.g. 1:3]
* [market condition note - trending/ranging/choppy]
**Breakout & Retest:**
* [any breakout level visible and direction]
* [retest confirmation - yes/no]
* [trend line break if visible]
**Indicators:**
* [RSI value and signal - overbought/oversold/neutral]
* [MA/EMA alignment - price above/below 20/50/200 MA]
* [Volume - confirmation or divergence]
**Fibonacci:**
* [key Fibonacci retracement level]
* [Fibonacci extension target]
**Psychology & Trade Plan:**
* [market sentiment - fear/greed/neutral]
* [entry trigger - exact condition]
* [trade management - partial profits, trailing stop]
* [invalidation level]
**Smart Money Concepts:**
* [Order Blocks: nearest bullish/bearish OB with price level]
* [Fair Value Gap (FVG): any unfilled FVG visible and direction]
* [Liquidity Sweep: recent high/low swept - yes/no]
* [Golden Pocket (0.618-0.65 Fib): price near this zone?]
* [Partial TP1 at 1:1, TP2 at full R:R, trail stop after TP1, invalidation level]
{trading_params}
{lang_instruction}
Educational analysis only, not financial advice."""
        response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[analysis_prompt, types.Part.from_bytes(data=image_bytes, mime_type=file.content_type)]
    )
        analysis_text = response.text
        lines = analysis_text.split('\n')
        trend_line = lines[0].strip().upper() if len(lines) > 0 else "NEUTRAL"
        confidence_line = lines[1].strip().lower() if len(lines) > 1 else "medium"
        trend_map = {"UPTREND": "bullish", "DOWNTREND": "bearish", "NEUTRAL": "sideways"}
        trend = trend_map.get(trend_line, "sideways")
        # Parse entry, SL, TP from analysis
        entry_price = 0.0
        sl_price = 0.0
        tp_price = 0.0
        for line in lines:
            l = line.strip()
            if l.startswith('Reference:') or l.startswith('Entry:'):
                try: entry_price = float(''.join(filter(lambda x: x.isdigit() or x == '.', l.split(':')[1].split()[0])))
                except: pass
            elif l.startswith('Lower:') or l.startswith('SL:'):
                try: sl_price = float(''.join(filter(lambda x: x.isdigit() or x == '.', l.split(':')[1].split()[0])))
                except: pass
            elif l.startswith('Upper:') or l.startswith('TP:'):
                try: tp_price = float(''.join(filter(lambda x: x.isdigit() or x == '.', l.split(':')[1].split()[0])))
                except: pass

        # Auto-signal disabled - user manually sends to bot

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

@app.post("/webhook/lemonsqueezy")
async def lemonsqueezy_webhook(request: Request, db: Session = Depends(get_db)):
    body = await request.body()
    
    if LEMONSQUEEZY_WEBHOOK_SECRET:
        signature = request.headers.get("x-signature", "")
        expected = hmac.new(
            LEMONSQUEEZY_WEBHOOK_SECRET.encode(),
            body,
            hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise HTTPException(status_code=401, detail="Invalid webhook signature")
    
    data = json.loads(body)
    event_name = data.get("meta", {}).get("event_name", "")
    attrs = data.get("data", {}).get("attributes", {})
    
    user_email = attrs.get("user_email") or data.get("meta", {}).get("custom_data", {}).get("email")
    subscription_id = str(data.get("data", {}).get("id", ""))
    variant_id = str(attrs.get("variant_id", ""))
    status = attrs.get("status", "")

    print(f"Webhook: {event_name} | email: {user_email} | variant: {variant_id} | status: {status}")

    if not user_email:
        return {"status": "ignored", "reason": "no email"}

    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        return {"status": "ignored", "reason": "user not found"}

    if event_name in ("subscription_created", "subscription_updated"):
        plan = VARIANT_PLAN_MAP.get(variant_id, "pro")
        if status == "active":
            user.plan = plan
            user.subscription_status = "active"
            user.subscription_id = subscription_id
            user.plan_started_at = datetime.utcnow()
            user.analyses_limit = PLAN_LIMITS.get(plan, 50)
            db.commit()

    elif event_name in ("subscription_cancelled", "subscription_expired", "subscription_paused"):
        user.plan = "free"
        user.subscription_status = "inactive"
        user.subscription_id = None
        user.analyses_limit = 3
        db.commit()

    return {"status": "ok"}

@app.post("/debug/upgrade-plan")
def upgrade_plan(email: str = Form(...), plan: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.plan = plan
    user.analyses_limit = PLAN_LIMITS.get(plan, 3)
    user.subscription_status = "active" if plan != "free" else "inactive"
    db.commit()
    return {"message": f"Plan updated to {plan}"}

@app.delete("/analysis/{analysis_id}")
def delete_analysis(analysis_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    analysis = db.query(Analysis).filter(Analysis.id == analysis_id, Analysis.user_email == current_user.email).first()
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")
    db.delete(analysis)
    db.commit()
    return {"message": "Analysis deleted"}

@app.delete("/delete-analysis/{analysis_id}")
def delete_analysis(analysis_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    analysis = db.query(Analysis).filter(Analysis.id == analysis_id, Analysis.user_email == current_user.email).first()
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")
    db.delete(analysis)
    db.commit()
    return {"message": "Analysis deleted"}

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

@app.post("/change-password")
def change_password(request: ChangePasswordRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    current_password = request.current_password
    new_password = request.new_password
    if not verify_password(current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if len(new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    current_user.hashed_password = get_password_hash(new_password)
    db.commit()
    return {"message": "Password updated successfully"}

import httpx
import xml.etree.ElementTree as ET

@app.get("/news")
async def get_crypto_news():
    try:
        feeds = [
            "https://cointelegraph.com/rss",
            "https://coindesk.com/arc/outboundfeeds/rss/",
        ]
        news = []
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            for feed_url in feeds:
                try:
                    response = await client.get(feed_url, headers={"User-Agent": "Mozilla/5.0"})
                    root = ET.fromstring(response.text)
                    channel = root.find("channel")
                    if channel is None:
                        continue
                    source_name = channel.findtext("title", "").strip()
                    for item in channel.findall("item")[:10]:
                        title = item.findtext("title", "").strip()
                        url = item.findtext("link", "").strip()
                        pub_date = item.findtext("pubDate", "").strip()
                        if title and url:
                            news.append({
                                "title": title,
                                "url": url,
                                "source": source_name,
                                "published_at": pub_date,
                                "currencies": [],
                            })
                except Exception:
                    continue
        return {"news": news[:25]}
    except Exception as e:
        return {"news": [], "error": str(e)}

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI = "https://tradeflow-ai-backend-production.up.railway.app/auth/google/callback"
FRONTEND_URL = "https://tradeflowai.cloud"

@app.get("/auth/google")
async def google_login():
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
    }
    from urllib.parse import urlencode
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url)

@app.get("/auth/google/callback")
async def google_callback(code: str, db: Session = Depends(get_db)):
    try:
        async with httpx.AsyncClient() as client:
            # Token al
            token_response = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "code": code,
                    "client_id": GOOGLE_CLIENT_ID,
                    "client_secret": GOOGLE_CLIENT_SECRET,
                    "redirect_uri": GOOGLE_REDIRECT_URI,
                    "grant_type": "authorization_code",
                }
            )
            token_data = token_response.json()
            access_token = token_data.get("access_token")
            if not access_token:
                from fastapi.responses import RedirectResponse
                return RedirectResponse(f"{FRONTEND_URL}/login?error=google_failed")

            # Kullanıcı bilgilerini al
            user_response = await client.get(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": f"Bearer {access_token}"}
            )
            user_info = user_response.json()
            email = user_info.get("email")
            name = user_info.get("name", email)

            if not email:
                from fastapi.responses import RedirectResponse
                return RedirectResponse(f"{FRONTEND_URL}/login?error=no_email")

            # Kullanıcıyı bul veya oluştur
            user = db.query(User).filter(User.email == email).first()
            if not user:
                user = User(
                    name=name,
                    email=email,
                    hashed_password=get_password_hash(os.urandom(32).hex()),
                    plan="free",
                    analyses_used=0,
                    analyses_limit=3,
                )
                db.add(user)
                db.commit()
                db.refresh(user)

            # JWT token oluştur
            jwt_token = create_access_token({"sub": user.email})
            from fastapi.responses import RedirectResponse
            return RedirectResponse(f"{FRONTEND_URL}/auth/callback?token={jwt_token}")

    except Exception as e:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(f"{FRONTEND_URL}/login?error={str(e)}")

@app.post("/update-profile")
async def update_profile(request: Request, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    data = await request.json()
    name = data.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name cannot be empty")
    current_user.name = name
    db.commit()
    return {"message": "Profile updated successfully"}

@app.post("/update-profile")
async def update_profile(request: Request, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    data = await request.json()
    name = data.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name cannot be empty")
    current_user.name = name
    db.commit()
    return {"message": "Profile updated successfully"}

@app.delete("/delete-account")
async def delete_account(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.query(Analysis).filter(Analysis.user_email == current_user.email).delete()
    db.delete(current_user)
    db.commit()
    return {"message": "Account deleted successfully"}

import secrets
import httpx
RESEND_API_KEY = os.getenv("RESEND_API_KEY")

@app.post("/forgot-password")
async def forgot_password(email: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == email).first()
    if not user:
        return {"message": "If this email exists, a reset link has been sent"}
    token = secrets.token_urlsafe(32)
    user.reset_token = token
    user.reset_token_expires = datetime.utcnow() + timedelta(hours=1)
    db.commit()
    reset_link = f"https://www.tradeflowai.cloud/reset-password?token={token}"
    body = f"""<html><body><h2>Password Reset</h2><p>Click below to reset your password. Expires in 1 hour.</p><a href="{reset_link}" style="background:#f97316;color:white;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:bold;">Reset Password</a><p>If you did not request this, ignore this email.</p></body></html>"""
    try:
        async with httpx.AsyncClient() as client:
            res = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
                json={"from": "TradeFlow AI <noreply@tradeflowai.cloud>", "to": [email], "subject": "TradeFlow AI - Password Reset", "html": body}
            )
            if res.status_code != 200:
                print(f"Resend error: {res.text}")
                raise HTTPException(status_code=500, detail="Failed to send email")
    except HTTPException:
        raise
    except Exception as e:
        print(f"Email error: {e}")
        raise HTTPException(status_code=500, detail="Failed to send email")
    return {"message": "If this email exists, a reset link has been sent"}
    
    return {"message": "If this email exists, a reset link has been sent"}

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

@app.post("/reset-password")
async def reset_password(data: ResetPasswordRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.reset_token == data.token).first()
    if not user or not user.reset_token_expires or user.reset_token_expires < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Invalid or expired token")
    
    if len(data.new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    
    user.hashed_password = get_password_hash(data.new_password)
    user.reset_token = None
    user.reset_token_expires = None
    db.commit()
    
    return {"message": "Password reset successfully"}

@app.on_event("startup")
async def migrate_db():
    from sqlalchemy import text
    with engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS reset_token VARCHAR"))
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS reset_token_expires TIMESTAMP"))
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_verified BOOLEAN DEFAULT FALSE"))
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS verification_token VARCHAR"))
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS reset_token_expires TIMESTAMP"))
            conn.commit()
            print("✅ Migration done")
        except Exception as e:
            print(f"Migration skipped: {e}")

@app.get("/verify-email")
def verify_email(token: str, db: Session = Depends(get_db)):
    from fastapi.responses import RedirectResponse
    user = db.query(User).filter(User.verification_token == token).first()
    if not user:
        raise HTTPException(status_code=400, detail="Invalid verification token")
    user.is_verified = True
    user.verification_token = None
    db.commit()
    jwt_token = create_access_token({"sub": user.email})
    return RedirectResponse(url=f"https://www.tradeflowai.cloud/auth/callback?token={jwt_token}")


# ============================================
# TRADING BOT ENTEGRASYONİ
# ============================================
from bot_service import (
    get_bot_health, create_bot, stop_bot, get_bot_summary,
    list_bots, get_positions, get_btc_price, get_eth_price,
    get_strategies, trigger_kill_switch, get_kill_switch_status,
)
import uuid as uuid_lib

class CreateBotModel(BaseModel):
    symbol: str = "BTCUSDT"
    strategy: str = "ema_crossover"
    mode: str = "paper"
    initial_balance: float = 10000.0

@app.get("/api/bot/health")
async def bot_health():
    return await get_bot_health()

@app.get("/api/bot/prices")
async def bot_prices():
    btc = await get_btc_price()
    eth = await get_eth_price()
    return {"BTC": btc.get("price"), "ETH": eth.get("price")}

@app.get("/api/bot/strategies")
async def bot_strategies():
    return await get_strategies()

@app.post("/api/bot/create")
async def bot_create(req: CreateBotModel):
    bot_id = f"bot-{str(uuid_lib.uuid4())[:8]}"
    return await create_bot(bot_id, "user-default", req.symbol, req.strategy, req.mode, req.initial_balance)

@app.get("/api/bot/list")
async def bot_list():
    return await list_bots()

@app.get("/api/bot/positions")
async def bot_positions(user_id: str = "user-123"):
    return await get_positions(user_id)

@app.get("/api/bot/summary/{bot_id}")
async def bot_summary(bot_id: str):
    return await get_bot_summary(bot_id)

@app.delete("/api/bot/{bot_id}/stop")
async def bot_stop(bot_id: str):
    return await stop_bot(bot_id)

@app.post("/api/bot/kill-switch")
async def bot_kill_switch(user_id: str = None):
    return await trigger_kill_switch(user_id)

@app.get("/api/bot/kill-switch/status")
async def bot_kill_status():
    return await get_kill_switch_status()

@app.post("/api/webhooks/bot-events")
async def bot_webhook(request: Request):
    body = await request.json()
    print(f"[BOT EVENT] {body.get('event_type')}: {body}")
    return {"received": True}

# ============ BOT SIGNAL ENDPOINTS ============
from pydantic import BaseModel as PydanticBase

class BotSignal(PydanticBase):
    action: str  # BUY, SELL, CLOSE
    symbol: str
    entry: float
    sl: float
    tp: float
    lot: float = 0.01

bot_signals = {}  # email -> list of signals

@app.post("/bot/signal/{email}")
async def receive_bot_signal(email: str, signal: BotSignal):
    import uuid, time
    signal_data = {
        "signal_id": str(uuid.uuid4())[:8],
        "action": signal.action,
        "symbol": signal.symbol,
        "entry": signal.entry,
        "sl": signal.sl,
        "tp": signal.tp,
        "lot": signal.lot,
        "timestamp": time.time()
    }
    if email not in bot_signals:
        bot_signals[email] = []
    bot_signals[email].append(signal_data)
    # Keep last 10 signals only
    bot_signals[email] = bot_signals[email][-10:]
    return {"status": "ok", "signal_id": signal_data["signal_id"]}

@app.get("/bot/signal/{email}")
async def get_bot_signal(email: str, last_id: str = ""):
    signals = bot_signals.get(email, [])
    if not signals:
        return Response(status_code=204)
    latest = signals[-1]
    if latest["signal_id"] == last_id:
        return Response(status_code=204)
    return latest

@app.get("/bot/signals/{email}")
async def get_all_signals(email: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return bot_signals.get(email, [])

# ============ BOT SETTINGS ============
bot_settings = {}  # email -> settings

@app.post("/bot/settings")
async def save_bot_settings(
    symbol: str = Form(default="XAUUSD"),
    lot_size: str = Form(default="0.01"),
    risk_percent: str = Form(default="1"),
    account_balance: str = Form(default="10000"),
    current_user: User = Depends(get_current_user)
):
    bot_settings[current_user.email] = {
        "symbol": symbol,
        "lot_size": lot_size,
        "risk_percent": risk_percent,
        "account_balance": account_balance
    }
    return {"status": "ok"}

@app.get("/bot/settings")
async def get_bot_settings(current_user: User = Depends(get_current_user)):
    return bot_settings.get(current_user.email, {"symbol": "XAUUSD", "lot_size": "0.01", "risk_percent": "1", "account_balance": "10000"})
