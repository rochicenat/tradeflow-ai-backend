"""
Lemon Squeezy Payment Integration for TradeFlowAI
Backend: FastAPI
"""

import os
import hmac
import hashlib
import requests
from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel
from typing import Optional
import json
from database import get_db, User
from sqlalchemy.orm import Session
from datetime import datetime, timedelta

# Lemon Squeezy Configuration
LEMON_SQUEEZY_API_KEY = "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9.eyJhdWQiOiI5NGQ1OWNlZi1kYmI4LTRlYTUtYjE3OC1kMjU0MGZjZDY5MTkiLCJqdGkiOiJmM2U4MDk2YWQ0OTAzMmEwNmIwMjM2MjZjNDEzYWYxNGQ3ZDUwNTU5MTk2M2ZiYmU1NmM3MTBhYzQ3YzQ5N2NlMjVlYzY5MmJhYTZkNDRmNyIsImlhdCI6MTc3MDgyMjYyMC45NzA2MzYsIm5iZiI6MTc3MDgyMjYyMC45NzA2MzgsImV4cCI6MTc4NjQwNjQwMC4wMzY1LCJzdWIiOiI2NDk4NTM2Iiwic2NvcGVzIjpbXX0.lgwnlJ0tTtuUGCMPRdFDFJiKZYR124TUj7GYpm4Mrvwi6gpC2Sp7pfxzdaQ4J1jPLen1uaE9LUSbWJDUR76DNA1WwYjw_maRHudYyOhmW3g38Auk7reIuFva_563DYz8lpVHnAdK_3w-FoUQRbnl7EaYjsZcZLOUwYS82VqWgXOYeB4uaoWXTC8USxpwkswcipwSBBy4_Nskgr15TFLS-c7vK_RaYcxMekuC0VJXC4SimQ5NpJWwiVbsg8B9Am-3sS2eNCcpQx7FByTy-Lq6_oHVa3rB6DETCTrgr1EBoCrbE0-_uJEkHuu1MfZ9tXUHGH6TlOxSDFd-q2oKtQk0XAc5P7qf1MbCY0Cw2W8TUDyzhJq43nHg97ZlDPwXswzPZ8O4mwhvIrhQB33kecyeycpw2WSViWJYA-5ste4ksonvIqYWcvNFosZNAx1lttIObOWOk_0yhAzcSlyLpF4JEtHzFCNnufsJDLGih-PN5RQZTuH8zNhGwgAtWL9ymci9-pHrIZZHNgTSflpmSKDyNVTw-Z1H37kZvY9zt4CI7A0pxOuR-kzwbIGdh3eGF7rkU77peo1mUp_q9J75ZkOjlsQYoxQWRUAOjY5wgLNwcral1SQhMWLem8yuh9UlKchiCbiMXRRje1SRHYCH1bXRG3_TpnisSpLfviv49qVwJ_o"
STORE_ID = "290537"
WEBHOOK_SECRET = os.getenv("LEMON_SQUEEZY_WEBHOOK_SECRET", "")

# Plan Variant IDs
PLANS = {
    "pro": "1297946",
    "premium": "1297978"
}

router = APIRouter(prefix="/api/payment", tags=["payment"])

# Pydantic Models
class CheckoutRequest(BaseModel):
    plan: str
    user_email: str
    user_id: str

class WebhookPayload(BaseModel):
    meta: dict
    data: dict


def create_checkout_session(variant_id: str, user_email: str, user_id: str) -> dict:
    """Lemon Squeezy checkout session oluştur"""
    url = "https://api.lemonsqueezy.com/v1/checkouts"
    
    headers = {
        "Accept": "application/vnd.api+json",
        "Content-Type": "application/vnd.api+json",
        "Authorization": f"Bearer {LEMON_SQUEEZY_API_KEY}"
    }
    
    payload = {
        "data": {
            "type": "checkouts",
            "attributes": {
                "checkout_data": {
                    "email": user_email,
                    "custom": {
                        "user_id": user_id
                    }
                },
                "product_options": {
                    "redirect_url": "https://tradeflowai.cloud/dashboard?payment=success",
                    "receipt_link_url": "https://tradeflowai.cloud/dashboard",
                    "receipt_thank_you_note": "Thank you for subscribing to TradeFlowAI!"
                },
                "checkout_options": {
                    "embed": False,
                    "media": True,
                    "logo": True,
                    "desc": True,
                    "discount": True,
                    "dark": True,
                    "subscription_preview": True,
                    "button_color": "#3b82f6"
                }
            },
            "relationships": {
                "store": {
                    "data": {
                        "type": "stores",
                        "id": STORE_ID
                    }
                },
                "variant": {
                    "data": {
                        "type": "variants",
                        "id": variant_id
                    }
                }
            }
        }
    }
    
    response = requests.post(url, json=payload, headers=headers)
    
    if response.status_code != 201:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create checkout: {response.text}"
        )
    
    return response.json()


def verify_webhook_signature(request: Request, body: bytes) -> bool:
    """Webhook signature'ı doğrula"""
    if not WEBHOOK_SECRET:
        return True
    
    signature = request.headers.get("X-Signature")
    if not signature:
        return False
    
    computed_signature = hmac.new(
        WEBHOOK_SECRET.encode(),
        body,
        hashlib.sha256
    ).hexdigest()
    
    return hmac.compare_digest(signature, computed_signature)


@router.post("/create-checkout")
async def create_checkout(checkout_req: CheckoutRequest):
    """Checkout session oluştur"""
    try:
        variant_id = PLANS.get(checkout_req.plan.lower())
        if not variant_id:
            raise HTTPException(status_code=400, detail="Invalid plan")
        
        checkout_data = create_checkout_session(
            variant_id=variant_id,
            user_email=checkout_req.user_email,
            user_id=checkout_req.user_id
        )
        
        checkout_url = checkout_data["data"]["attributes"]["url"]
        
        return {
            "success": True,
            "checkout_url": checkout_url,
            "plan": checkout_req.plan
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/webhook")
async def lemon_squeezy_webhook(request: Request, db: Session = Depends(get_db)):
    """Lemon Squeezy webhook handler - FIXED VERSION"""
    try:
        body = await request.body()
        
        # # if not verify_webhook_signature(request, body):
            # # raise HTTPException(status_code=401, detail="Invalid signature")
        
        payload = json.loads(body)
        event_name = payload["meta"]["event_name"]
        data = payload["data"]
        
        # User bilgilerini çek
        user_email = data["attributes"].get("user_email")
        
        print(f"🔔 Webhook received: {event_name}")
        print(f"👤 User Email: {user_email}")
        
        if event_name == "subscription_created":
            subscription_id = data["id"]
            status = data["attributes"]["status"]
            variant_id = str(data["attributes"]["variant_id"])
            
            # Plan tipini belirle
            plan_type = "pro" if variant_id == PLANS["pro"] else "premium"
            
            print(f"📦 Plan: {plan_type}")
            print(f"🆔 Subscription ID: {subscription_id}")
            print(f"📊 Status: {status}")
            
            # ✅ VERİTABANINI GÜNCELLE
            user = db.query(User).filter(User.email == user_email).first()
            
            if user:
                user.plan = plan_type
                user.subscription_id = subscription_id
                user.subscription_status = "active"
                user.plan_started_at = datetime.utcnow()
                user.plan_ends_at = datetime.utcnow() + timedelta(days=30)
                user.analyses_limit = 50 if plan_type == "pro" else 999999
                user.analyses_used = 0  # Reset monthly usage
                
                db.commit()
                db.refresh(user)
                
                print(f"✅ Database updated: {user_email} -> {plan_type}")
                print(f"✅ New limit: {user.analyses_limit}")
            else:
                print(f"❌ User not found: {user_email}")
                raise HTTPException(status_code=404, detail="User not found")
            
        elif event_name == "subscription_updated":
            status = data["attributes"]["status"]
            
            user = db.query(User).filter(User.email == user_email).first()
            
            if user:
                user.subscription_status = status
                db.commit()
                print(f"🔄 Subscription updated: {user_email} -> {status}")
            else:
                print(f"❌ User not found: {user_email}")
                
        elif event_name == "subscription_cancelled":
            user = db.query(User).filter(User.email == user_email).first()
            
            if user:
                user.subscription_status = "cancelled"
                user.plan = "free"  # Downgrade to free
                user.analyses_limit = 3
                db.commit()
                print(f"❌ Subscription cancelled: {user_email}")
            else:
                print(f"❌ User not found: {user_email}")
            
        return {"success": True, "event": event_name}
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Webhook error: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/verify-subscription/{user_id}")
async def verify_subscription(user_id: str):
    """User'ın subscription durumunu kontrol et"""
    try:
        return {
            "success": True,
            "user_id": user_id,
            "subscription": {
                "active": False,
                "plan": None,
                "status": "inactive",
                "subscription_id": None
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
