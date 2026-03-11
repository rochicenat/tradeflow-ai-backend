import httpx
import os
from typing import Optional
from dotenv import load_dotenv
load_dotenv()

_bots: dict = {}
_kill_switch = {"active": False, "reason": None}

async def get_bot_health():
    return {
        "status": "ok",
        "service": "standalone",
        "bots_active": len([b for b in _bots.values() if b.get("status") == "running"]),
        "bots_total": len(_bots),
        "kill_switch": _kill_switch["active"],
    }

async def _get_price(symbol: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}")
            if r.status_code == 200:
                data = r.json()
                return {"symbol": symbol, "price": float(data["price"]), "source": "binance"}
    except Exception as e:
        pass
    return {"symbol": symbol, "price": None, "error": "price unavailable"}

async def get_btc_price():
    return await _get_price("BTCUSDT")

async def get_eth_price():
    return await _get_price("ETHUSDT")

async def get_strategies():
    return {
        "strategies": [
            {"id": "ema_crossover", "name": "EMA Crossover", "description": "9/21 EMA crossover strategy", "risk": "medium"},
            {"id": "rsi_reversal", "name": "RSI Reversal", "description": "RSI oversold/overbought reversal", "risk": "medium"},
            {"id": "breakout", "name": "Breakout", "description": "Key level breakout strategy", "risk": "high"},
            {"id": "scalp_momentum", "name": "Scalp Momentum", "description": "Short-term momentum scalping", "risk": "high"},
            {"id": "swing_trend", "name": "Swing Trend", "description": "Multi-day trend following", "risk": "low"},
        ]
    }

async def create_bot(bot_id: str, user_id: str, symbol: str, strategy: str, mode: str = "paper", balance: float = 10000.0):
    import time
    _bots[bot_id] = {
        "bot_id": bot_id,
        "user_id": user_id,
        "symbol": symbol,
        "strategy": strategy,
        "mode": mode,
        "balance": balance,
        "initial_balance": balance,
        "status": "running",
        "pnl": 0.0,
        "trades": 0,
        "created_at": time.time(),
    }
    return {"status": "created", "bot_id": bot_id, "bot": _bots[bot_id]}

async def stop_bot(bot_id: str):
    if bot_id not in _bots:
        return {"error": "Bot not found"}
    _bots[bot_id]["status"] = "stopped"
    return {"status": "stopped", "bot_id": bot_id}

async def get_bot_summary(bot_id: str):
    if bot_id not in _bots:
        return {"error": "Bot not found"}
    bot = _bots[bot_id]
    initial = bot.get("initial_balance", 10000)
    pnl_pct = (bot["pnl"] / initial * 100) if initial else 0
    return {**bot, "pnl_percent": round(pnl_pct, 2), "win_rate": 0.0}

async def list_bots():
    return {"bots": list(_bots.values()), "total": len(_bots)}

async def get_positions(user_id: str):
    user_bots = [b for b in _bots.values() if b.get("user_id") == user_id]
    return {
        "user_id": user_id,
        "open_positions": [],
        "bots": user_bots,
        "total_pnl": sum(b.get("pnl", 0) for b in user_bots),
    }

async def trigger_kill_switch(user_id=None):
    _kill_switch["active"] = True
    _kill_switch["reason"] = "manual"
    stopped = 0
    for bot_id, bot in _bots.items():
        if bot["status"] == "running":
            bot["status"] = "stopped"
            stopped += 1
    return {"status": "triggered", "bots_stopped": stopped, "kill_switch": True}

async def get_kill_switch_status():
    return {"active": _kill_switch["active"], "reason": _kill_switch["reason"]}
