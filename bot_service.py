import httpx
import os
from typing import Optional
from dotenv import load_dotenv
load_dotenv()

BOT_SERVICE_URL = os.getenv("BOT_SERVICE_URL", "http://localhost:8001")
BOT_SERVICE_TOKEN = os.getenv("BOT_SERVICE_TOKEN", "internal-token-changethis")


async def bot_request(method: str, path: str, data: dict = None) -> dict:
    headers = {
        "X-Internal-Token": BOT_SERVICE_TOKEN,
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        url = f"{BOT_SERVICE_URL}{path}"
        try:
            if method == "GET":
                response = await client.get(url, headers=headers)
            elif method == "POST":
                response = await client.post(url, json=data, headers=headers)
            elif method == "DELETE":
                response = await client.delete(url, headers=headers)
            
            if response.status_code == 200:
                return response.json()
            else:
                return {"error": f"HTTP {response.status_code}", "detail": response.text}
        except Exception as e:
            return {"error": str(e)}


async def get_bot_health():
    return await bot_request("GET", "/health")

async def create_bot(bot_id, user_id, symbol, strategy, mode="paper", balance=10000.0):
    return await bot_request("POST", "/api/v1/bots/create", {
        "bot_id": bot_id, "user_id": user_id, "symbol": symbol,
        "strategy_name": strategy, "mode": mode, "initial_balance": balance,
    })

async def stop_bot(bot_id):
    return await bot_request("DELETE", f"/api/v1/bots/{bot_id}/stop")

async def get_bot_summary(bot_id):
    return await bot_request("GET", f"/api/v1/bots/{bot_id}/summary")

async def list_bots():
    return await bot_request("GET", "/api/v1/bots/list")

async def get_positions(user_id):
    return await bot_request("GET", f"/api/v1/positions/summary?user_id={user_id}")

async def get_btc_price():
    return await bot_request("GET", "/api/v1/binance/price/BTCUSDT")

async def get_eth_price():
    return await bot_request("GET", "/api/v1/binance/price/ETHUSDT")

async def get_strategies():
    return await bot_request("GET", "/api/v1/strategies/list")

async def trigger_kill_switch(user_id: Optional[str] = None):
    return await bot_request("POST", "/api/v1/kill-switch/trigger", {
        "reason": "manual", "user_id": user_id,
        "details": "TradeFlowAI üzerinden tetiklendi",
    })

async def get_kill_switch_status():
    return await bot_request("GET", "/api/v1/kill-switch/status")
