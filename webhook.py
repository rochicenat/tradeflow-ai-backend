from fastapi import APIRouter, Request, HTTPException, Header
from sqlalchemy.orm import Session
from database import User, SessionLocal
from typing import Optional
import hmac
import hashlib
import json
from datetime import datetime, timedelta
import os

router = APIRouter(prefix="/webhook", tags=["Webhooks"])

LEMON_SQUEEZY_WEBHOOK_SECRET = os.getenv("LEMON_SQUEEZY_WEBHOOK_SECRET", "")

# Plan limitleri
PLAN_LIMITS = {
    "free": 3,
    "pro": 50,
    "premium": 999999
}

@router.post("/lemon-squeezy")
async def lemon_squeezy_webhook(request: Request, x_signature: Optional[str] = Header(None)):
    """Lemon Squeezy webhook handler"""
    body = await request.body()
    
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    
    event_name = data.get("meta", {}).get("event_name")
    
    print(f"🔔 Webhook received: {event_name}")
    
    if event_name == "order_created":
        await handle_order_created(data)
    elif event_name == "subscription_created":
        await handle_subscription_created(data)
    
    return {"status": "success"}


async def handle_order_created(data: dict):
    """Tek seferlik ödeme"""
    db = SessionLocal()
    try:
        attributes = data["data"]["attributes"]
        customer_email = attributes["user_email"]
        product_name = attributes["first_order_item"]["product_name"]
        
        plan = "premium" if "Premium" in product_name else "pro"
        
        user = db.query(User).filter(User.email == customer_email).first()
        if user:
            user.plan = plan
            user.subscription_status = "active"
            user.plan_started_at = datetime.utcnow()
            user.plan_ends_at = datetime.utcnow() + timedelta(days=30)
            user.analyses_limit = PLAN_LIMITS[plan]
            user.analyses_used = 0
            db.commit()
            print(f"✅ Order: {customer_email} → {plan}")
    finally:
        db.close()


async def handle_subscription_created(data: dict):
    """Yeni subscription"""
    db = SessionLocal()
    try:
        attributes = data["data"]["attributes"]
        customer_email = attributes["user_email"]
        subscription_id = data["data"]["id"]
        product_name = attributes["product_name"]
        
        plan = "premium" if "Premium" in product_name else "pro"
        
        user = db.query(User).filter(User.email == customer_email).first()
        if user:
            user.plan = plan
            user.subscription_status = "active"
            user.subscription_id = subscription_id
            user.analyses_limit = PLAN_LIMITS[plan]
            user.analyses_used = 0
            db.commit()
            print(f"✅ Subscription: {customer_email} → {plan}")
    finally:
        db.close()


@router.post("/test")
async def test_webhook():
    """Test endpoint"""
    return {"status": "webhook endpoint working!"}
