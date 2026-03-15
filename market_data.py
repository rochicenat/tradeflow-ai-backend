import ccxt
import yfinance as yf
import pandas as pd
import pandas_ta as ta
from datetime import datetime

def detect_asset_type(symbol: str) -> str:
    symbol = symbol.upper().strip()
    forex_keywords = ["=X", "USD", "EUR", "GBP", "JPY", "CHF", "AUD", "CAD", "NZD"]
    crypto_keywords = ["USDT", "BTC", "ETH", "BNB", "SOL", "XRP", "DOGE", "ADA"]
    commodity_keywords = ["GC=F", "SI=F", "CL=F", "NG=F", "XAUUSD", "XAGUSD"]
    
    if any(k in symbol for k in commodity_keywords) or symbol in ["XAUUSD", "XAGUSD"]:
        return "commodity"
    if any(k in symbol for k in crypto_keywords):
        return "crypto"
    if any(k in symbol for k in forex_keywords):
        return "forex"
    return "stock"

def get_crypto_data(symbol: str, timeframe: str = "1h") -> dict:
    try:
        exchange = ccxt.binance()
        pair = symbol.replace("USDT", "/USDT").replace("BTC", "/BTC") if "/" not in symbol else symbol
        if "/USDT" not in pair and "/BTC" not in pair:
            pair = f"{symbol}/USDT"
        
        ohlcv = exchange.fetch_ohlcv(pair, timeframe, limit=200)
        df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df.set_index("timestamp", inplace=True)
        return calculate_indicators(df, symbol)
    except Exception as e:
        print(f"Crypto data error: {e}")
        return {}

def get_yfinance_data(symbol: str, timeframe: str = "1h") -> dict:
    try:
        tf_map = {
            "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
            "1h": "1h", "4h": "1h", "1d": "1d", "1w": "1wk"
        }
        period_map = {
            "1m": "1d", "5m": "5d", "15m": "5d", "30m": "5d",
            "1h": "1mo", "4h": "3mo", "1d": "6mo", "1w": "2y"
        }
        
        yf_symbol = symbol
        if symbol.upper() in ["XAUUSD", "GOLD"]:
            yf_symbol = "GC=F"
        elif symbol.upper() in ["EURUSD"]:
            yf_symbol = "EURUSD=X"
        elif symbol.upper() in ["GBPUSD"]:
            yf_symbol = "GBPUSD=X"
        elif symbol.upper() in ["USDJPY"]:
            yf_symbol = "USDJPY=X"
        
        yf_tf = tf_map.get(timeframe, "1h")
        yf_period = period_map.get(timeframe, "1mo")
        
        ticker = yf.Ticker(yf_symbol)
        df = ticker.history(period=yf_period, interval=yf_tf)
        
        if df.empty:
            return {}
        
        df.columns = [c.lower() for c in df.columns]
        return calculate_indicators(df, symbol)
    except Exception as e:
        print(f"YFinance data error: {e}")
        return {}

def calculate_indicators(df: pd.DataFrame, symbol: str) -> dict:
    try:
        df.ta.rsi(length=14, append=True)
        df.ta.ema(length=20, append=True)
        df.ta.ema(length=200, append=True)
        df.ta.macd(append=True)
        df.ta.atr(length=14, append=True)
        
        latest = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else latest
        
        rsi = round(float(latest.get("RSI_14", 0)), 2)
        ema20 = round(float(latest.get("EMA_20", 0)), 5)
        ema200 = round(float(latest.get("EMA_200", 0)), 5)
        atr = round(float(latest.get("ATRr_14", latest.get("ATR_14", 0))), 5)
        
        macd_val = latest.get("MACD_12_26_9", 0)
        macd_signal = latest.get("MACDs_12_26_9", 0)
        macd_text = "Bullish Cross" if float(macd_val) > float(macd_signal) else "Bearish Cross"
        
        current_price = round(float(latest["close"]), 5)
        daily_open = round(float(df.iloc[0]["open"]), 5)
        
        support = round(float(df["low"].tail(20).min()), 5)
        resistance = round(float(df["high"].tail(20).max()), 5)
        
        volume_trend = "Increasing" if float(latest.get("volume", 0)) > float(df["volume"].tail(10).mean()) else "Decreasing"
        
        return {
            "asset_info": {
                "symbol": symbol.upper(),
                "current_price": current_price,
                "daily_open_price": daily_open
            },
            "multi_timeframe_context": {
                "short_term_trend": "Bullish" if current_price > ema20 else "Bearish",
                "long_term_trend": "Bullish" if current_price > ema200 else "Bearish"
            },
            "technical_indicators": {
                "rsi_14": rsi,
                "macd_signal": macd_text,
                "atr_14": atr,
                "ema_20": ema20,
                "ema_200": ema200
            },
            "market_sentiment": {
                "volume_trend": volume_trend,
                "price_vs_ema20": "Above" if current_price > ema20 else "Below",
                "price_vs_ema200": "Above" if current_price > ema200 else "Below"
            },
            "key_liquidity_levels": {
                "nearest_support": support,
                "nearest_resistance": resistance
            }
        }
    except Exception as e:
        print(f"Indicator calc error: {e}")
        return {}

def get_market_data(symbol: str, timeframe: str = "1h", asset_type: str = "") -> dict:
    if not symbol:
        return {}
    
    detected = detect_asset_type(symbol) if not asset_type else asset_type.lower()
    
    try:
        if detected == "crypto":
            data = get_crypto_data(symbol, timeframe)
        else:
            data = get_yfinance_data(symbol, timeframe)
        
        return data if data else {}
    except Exception as e:
        print(f"Market data error: {e}")
        return {}
