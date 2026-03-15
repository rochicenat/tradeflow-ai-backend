import yfinance as yf
import pandas as pd
from datetime import datetime

try:
    import ccxt
    CCXT_AVAILABLE = True
except:
    CCXT_AVAILABLE = False

def detect_asset_type(symbol: str) -> str:
    symbol = symbol.upper().strip()
    crypto_keywords = ["USDT","USDC","BTC","ETH","BNB","SOL","XRP","DOGE","ADA","DOT","MATIC","PEPE","SHIB","AVAX"]
    commodity_keywords = ["XAUUSD","XAGUSD","GC=F","SI=F","CL=F"]
    forex_keywords = ["USD","EUR","GBP","JPY","CHF","AUD","CAD","NZD"]
    
    if any(k in symbol for k in commodity_keywords) or symbol in ["XAUUSD","XAGUSD"]:
        return "commodity"
    for k in crypto_keywords:
        if symbol.endswith(k) or symbol.startswith(k):
            return "crypto"
    if any(k in symbol for k in forex_keywords) and len(symbol) == 6:
        return "forex"
    return "stock"

def get_crypto_data(symbol: str, timeframe: str = "1h") -> dict:
    if not CCXT_AVAILABLE:
        return {}
    try:
        exchange = ccxt.binance()
        pair = symbol
        if "/" not in symbol:
            if symbol.endswith("USDT"):
                pair = symbol[:-4] + "/USDT"
            elif symbol.endswith("BTC"):
                pair = symbol[:-3] + "/BTC"
            else:
                pair = symbol + "/USDT"
        
        ohlcv = exchange.fetch_ohlcv(pair, timeframe, limit=200)
        df = pd.DataFrame(ohlcv, columns=["timestamp","open","high","low","close","volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df.set_index("timestamp", inplace=True)
        return calculate_indicators(df, symbol)
    except Exception as e:
        print(f"Crypto data error: {e}")
        return {}

def get_yfinance_data(symbol: str, timeframe: str = "1h") -> dict:
    try:
        tf_map = {"1m":"1m","5m":"5m","15m":"15m","30m":"30m","1h":"1h","4h":"1h","1d":"1d","1w":"1wk","daily":"1d","weekly":"1wk"}
        period_map = {"1m":"1d","5m":"5d","15m":"5d","30m":"5d","1h":"1mo","4h":"3mo","1d":"6mo","1w":"2y","daily":"6mo","weekly":"2y"}
        
        yf_symbol = symbol.upper()
        symbol_map = {
            "XAUUSD":"GC=F","GOLD":"GC=F","XAGUSD":"SI=F",
            "EURUSD":"EURUSD=X","GBPUSD":"GBPUSD=X","USDJPY":"USDJPY=X",
            "AUDUSD":"AUDUSD=X","USDCAD":"USDCAD=X","USDCHF":"USDCHF=X",
            "NZDUSD":"NZDUSD=X","GBPJPY":"GBPJPY=X","EURJPY":"EURJPY=X","USDTRY":"USDTRY=X",
            "NASDAQ":"QQQ","SP500":"SPY","DOW":"DIA",
        }
        yf_symbol = symbol_map.get(yf_symbol, yf_symbol)
        
        tf_key = timeframe.lower()
        yf_tf = tf_map.get(tf_key, "1h")
        yf_period = period_map.get(tf_key, "1mo")
        
        ticker = yf.Ticker(yf_symbol)
        df = ticker.history(period=yf_period, interval=yf_tf)
        
        if df.empty:
            return {}
        
        df.columns = [c.lower() for c in df.columns]
        return calculate_indicators(df, symbol)
    except Exception as e:
        print(f"YFinance error: {e}")
        return {}

def calculate_indicators(df: pd.DataFrame, symbol: str) -> dict:
    try:
        close = df["close"]
        high = df["high"]
        low = df["low"]
        volume = df["volume"]
        
        # RSI
        delta = close.diff()
        gain = delta.where(delta > 0, 0).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        rsi = round(float((100 - (100 / (1 + rs))).iloc[-1]), 2)
        
        # EMA
        ema20 = round(float(close.ewm(span=20).mean().iloc[-1]), 5)
        ema200 = round(float(close.ewm(span=200).mean().iloc[-1]), 5)
        
        # MACD
        ema12 = close.ewm(span=12).mean()
        ema26 = close.ewm(span=26).mean()
        macd_line = ema12 - ema26
        signal_line = macd_line.ewm(span=9).mean()
        macd_text = "Bullish Cross" if float(macd_line.iloc[-1]) > float(signal_line.iloc[-1]) else "Bearish Cross"
        
        # ATR
        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low - close.shift()).abs()
        ], axis=1).max(axis=1)
        atr = round(float(tr.rolling(14).mean().iloc[-1]), 5)
        
        current_price = round(float(close.iloc[-1]), 5)
        daily_open = round(float(df["open"].iloc[0]), 5)
        support = round(float(low.tail(20).min()), 5)
        resistance = round(float(high.tail(20).max()), 5)
        vol_avg = float(volume.tail(10).mean())
        volume_trend = "Increasing" if float(volume.iloc[-1]) > vol_avg else "Decreasing"
        
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
    try:
        detected = detect_asset_type(symbol) if not asset_type else asset_type.lower()
        if detected == "crypto" and CCXT_AVAILABLE:
            data = get_crypto_data(symbol, timeframe)
            if data:
                return data
        return get_yfinance_data(symbol, timeframe)
    except Exception as e:
        print(f"Market data error: {e}")
        return {}
