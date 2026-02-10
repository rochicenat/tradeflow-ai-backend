from fastapi import FastAPI, UploadFile, File, HTTPException, Header, Request
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
import iyzipay
import json

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

# İyzico Configuration
iyzico_options = {
    'api_key': os.getenv('IYZICO_API_KEY'),
    'secret_key': os.getenv('IYZICO_SECRET_KEY'),
    'base_url': os.getenv('IYZICO_BASE_URL', 'https://sandbox-api.iyzipay.com')
}

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

class PaymentRequest(BaseModel):
    plan: str
    card_holder_name: str
    card_number: str
    expire_month: str
    expire_year: str
    cvc: str

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def get_current_user_from_token(authorization: Optional[str] = None):
    if not authorization:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    try:
        token = authorization.replace("Bearer ", "")
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email = payload.get("sub")
        if email is None or email not in users_db:
            raise HTTPException(status_code=401, detail="Invalid token")
        return users_db[email]
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

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
        "hashed_password": hashed_password,
        "plan": "free",
        "analyses_used": 0
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
    user = get_current_user_from_token(authorization)
    result = user.copy()
    result.pop("hashed_password", None)
    return result

@app.post("/create-payment")
async def create_payment(
    payment: PaymentRequest,
    authorization: Optional[str] = Header(None)
):
    try:
        user = get_current_user_from_token(authorization)
        
        # Plan fiyatları
        plan_prices = {
            "pro": {"price": "9.99", "name": "Pro Plan"},
            "premium": {"price": "19.99", "name": "Premium Plan"}
        }
        
        if payment.plan not in plan_prices:
            raise HTTPException(status_code=400, detail="Invalid plan")
        
        plan_info = plan_prices[payment.plan]
        
        # İyzico ödeme isteği
        payment_request = {
            'locale': 'en',
            'conversationId': f"{user['email']}_{payment.plan}_{datetime.utcnow().timestamp()}",
            'price': plan_info['price'],
            'paidPrice': plan_info['price'],
            'currency': 'USD',
            'installment': '1',
            'basketId': f"basket_{user['email']}",
            'paymentChannel': 'WEB',
            'paymentGroup': 'SUBSCRIPTION',
            'paymentCard': {
                'cardHolderName': payment.card_holder_name,
                'cardNumber': payment.card_number,
                'expireMonth': payment.expire_month,
                'expireYear': payment.expire_year,
                'cvc': payment.cvc,
                'registerCard': '0'
            },
            'buyer': {
                'id': user['email'],
                'name': user['name'].split()[0] if ' ' in user['name'] else user['name'],
                'surname': user['name'].split()[-1] if ' ' in user['name'] else 'User',
                'email': user['email'],
                'identityNumber': '11111111111',
                'registrationAddress': 'Address',
                'city': 'City',
                'country': 'Turkey',
                'ip': '85.34.78.112'
            },
            'shippingAddress': {
                'contactName': user['name'],
                'city': 'City',
                'country': 'Turkey',
                'address': 'Address'
            },
            'billingAddress': {
                'contactName': user['name'],
                'city': 'City',
                'country': 'Turkey',
                'address': 'Address'
            },
            'basketItems': [
                {
                    'id': payment.plan,
                    'name': plan_info['name'],
                    'category1': 'Subscription',
                    'itemType': 'VIRTUAL',
                    'price': plan_info['price']
                }
            ]
        }
        
        # İyzico API çağrısı
        payment_result = iyzipay.Payment().create(payment_request, iyzico_options)
        
        result = json.loads(payment_result.read().decode('utf-8'))
        
        # Ödeme başarılı ise kullanıcı planını güncelle
        if result.get('status') == 'success':
            users_db[user['email']]['plan'] = payment.plan
            users_db[user['email']]['analyses_used'] = 0
            
            return {
                "success": True,
                "message": "Payment successful",
                "plan": payment.plan
            }
        else:
            return {
                "success": False,
                "message": result.get('errorMessage', 'Payment failed'),
                "error": result.get('errorCode')
            }
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Payment error: {str(e)}")

@app.post("/analyze-image", response_model=AnalysisResponse)
async def analyze_image(
    file: UploadFile = File(...),
    authorization: Optional[str] = Header(None)
):
    try:
        user = get_current_user_from_token(authorization)
        
        # Plan limitleri
        plan_limits = {
            "free": 3,
            "pro": 50,
            "premium": 999999
        }
        
        user_plan = user.get('plan', 'free')
        analyses_used = user.get('analyses_used', 0)
        limit = plan_limits.get(user_plan, 3)
        
        if analyses_used >= limit:
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
        
        # Kullanım sayısını artır
        users_db[user['email']]['analyses_used'] = analyses_used + 1
        
        return AnalysisResponse(
            analysis=analysis,
            trend=trend,
            confidence=confidence
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error analyzing image: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
