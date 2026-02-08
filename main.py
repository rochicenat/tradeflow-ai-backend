from fastapi import FastAPI, UploadFile, File, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
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
        "https://tradeflow-ai-frontend-dkyc.vercel.app"
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

users_db = {}

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

@app.get("/")
async def root():
    return {"message": "Trading Chart Analysis API is running"}

@app.post("/register", response_model=Token)
async def register(user: UserCreate):
    if user.email in users_db:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    hashed_password = pwd_context.hash(user.password)
    users_db[user.email] = {
        "email": user.email,
        "name": user.name,
        "hashed_password": hashed_password
    }
    
    access_token = create_access_token(data={"sub": user.email})
    return {"access_token": access_token, "token_type": "bearer"}

@app.post("/login", response_model=Token)
async def login(user: UserLogin):
    if user.email not in users_db:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    stored_user = users_db[user.email]
    if not pwd_context.verify(user.password, stored_user["hashed_password"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    access_token = create_access_token(data={"sub": user.email})
    return {"access_token": access_token, "token_type": "bearer"}

@app.get("/me")
async def get_current_user(authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    try:
        token = authorization.replace("Bearer ", "")
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email = payload.get("sub")
        if email is None or email not in users_db:
            raise HTTPException(status_code=401, detail="Invalid token")
        user = users_db[email].copy()
        user.pop("hashed_password")
        return user
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

@app.post("/analyze-image", response_model=AnalysisResponse)
async def analyze_image(file: UploadFile = File(...)):
    try:
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
        
        return AnalysisResponse(
            analysis=analysis,
            trend=trend,
            confidence=confidence
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error analyzing image: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
