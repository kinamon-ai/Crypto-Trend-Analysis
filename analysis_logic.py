import ccxt
import pandas as pd
import pandas_ta as ta
import datetime
import time
import sys
import numpy as np

# --- Configuration ---
SYMBOL = 'BTC/USDT'
TIMEFRAMES = {
    '1M': '1M',
    '1w': '1w',
    '1d': '1d',
    '4h': '4h',
    '1h': '1h'
}
LIMIT = 1000  # Fetch enough data for long-term MAs
EXCHANGE_ID = 'binance'

# --- Logic Constants ---
CYCLE_START_YEAR = 2022  # Reference point for 4-year cycle (2022 was the 'down' year)
# 2023, 2024, 2025 -> Up
# 2026 -> Down? (Based on 3 up 1 down rule)

def get_anomaly_phase():
    """
    Determines the current phase in the 4-year cycle.
    Rule: 3 years UP, 1 year DOWN.
    Reference: 2022 was a DOWN year.
    """
    current_year = datetime.datetime.now().year
    
    # 2022: Down (Start of cycle logic for calculation)
    # 2023: Up
    # 2024: Up
    # 2025: Up
    # 2026: Down
    
    cycle_position = (current_year - CYCLE_START_YEAR) % 4
    
    if cycle_position == 0 and current_year != CYCLE_START_YEAR:
         phase = "下降 (調整年)"
         bias = "ショート(売り)優先"
    elif cycle_position == 0 and current_year == CYCLE_START_YEAR:
         phase = "下降 (底打ち年)"
         bias = "ショート(売り)優先"
    else:
        phase = f"上昇 (Year {cycle_position})"
        bias = "ロング(買い)優先"
        
    return phase, bias

def fetch_data(exchange, symbol, timeframe, limit, retries=3):
    """Fetches OHLCV data from the exchange with retries. Returns (df, last_error)."""
    last_error = "Unknown error"
    for attempt in range(retries):
        try:
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            if not ohlcv or len(ohlcv) == 0:
                last_error = "Exchange returned 0 bars"
                time.sleep(1)
                continue
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            return df, None
        except Exception as e:
            last_error = str(e)
            print(f"Error fetching data for {timeframe} (Attempt {attempt+1}/{retries}): {e}")
            time.sleep(1 * (attempt + 1)) # Exponential backoff
    return None, last_error

def calculate_indicators(df):
    """Calculates SMA, EMA, MACD."""
    if df is None or len(df) < 200:
        return df

    # SMA
    df['SMA7'] = ta.sma(df['close'], length=7)
    df['SMA25'] = ta.sma(df['close'], length=25)
    df['SMA100'] = ta.sma(df['close'], length=100)
    df['SMA200'] = ta.sma(df['close'], length=200)

    # EMA
    df['EMA20'] = ta.ema(df['close'], length=20)

    # MACD (12, 26, 9)
    macd = ta.macd(df['close'], fast=12, slow=26, signal=9)
    df = pd.concat([df, macd], axis=1)
    # Rename columns for clarity (pandas_ta default names can be verbose)
    df.rename(columns={'MACD_12_26_9': 'MACD', 'MACDs_12_26_9': 'MACD_Signal', 'MACDh_12_26_9': 'MACD_Hist'}, inplace=True)

    return df

def analyze_trend(df, timeframe):
    """
    Analyzes trend based on MAs.
    UP Trend: Price > 200SMA and Price > 100SMA
    DOWN Trend: Price < 200SMA and Price < 100SMA
    """
    
    if df is None or df.empty:
        return "N/A"
    
    # Check if necessary columns exist
    if 'SMA200' not in df.columns or 'SMA100' not in df.columns:
        return "データ不足 (>200本必要)"
        
    last_row = df.iloc[-1]
    close = last_row['close']
    sma200 = last_row['SMA200']
    sma100 = last_row['SMA100']
    
    if pd.isna(sma200):
        return "データ不足"

    if close > sma200 and close > sma100:
        return "上昇トレンド"
    elif close < sma200 and close < sma100:
        return "下降トレンド"
    else:
        return "レンジ / 中立"

def detect_signals(df, timeframe):
    """
    Detects potential entry signals based on 'Return Move' and MACD.
    Logic:
    1. Return Move: Close is near EMA20 (within 1%?)
    2. MACD: 
       - LONG: MACD < 0 and (GC or Histogram turning up)
       - SHORT: MACD > 0 and (DC or Histogram turning down)
    """
    if df is None:
        return []

    signals = []
    last_row = df.iloc[-1]
    prev_row = df.iloc[-2]
    
    close = last_row['close']

    # --- Return Move Check (Price near EMA20) ---
    if 'EMA20' not in df.columns:
         return signals
    
    ema20 = last_row['EMA20']
    
    # Define "Near" as within 0.5% distance
    dist_to_ema20 = abs(close - ema20) / close
    is_near_ema20 = dist_to_ema20 < 0.005 

    # --- MACD Logic ---
    if 'MACD' not in df.columns:
        return signals

    macd = last_row['MACD']
    signal = last_row['MACD_Signal']
    hist = last_row['MACD_Hist']
    prev_hist = prev_row['MACD_Hist']
    
    # Golden Cross (GC): MACD crosses above Signal
    is_gc = (prev_row['MACD'] <= prev_row['MACD_Signal']) and (last_row['MACD'] > last_row['MACD_Signal'])
    # Dead Cross (DC): MACD crosses below Signal
    is_dc = (prev_row['MACD'] >= prev_row['MACD_Signal']) and (last_row['MACD'] < last_row['MACD_Signal'])
    
    # Histogram Reversal (Early signal)
    hist_improving = hist > prev_hist and hist < 0 # Improving in negative territory
    hist_deteriorating = hist < prev_hist and hist > 0 # Deteriorating in positive territory

    # --- Combine for Alerts ---
    
    # LONG Signal Suitability
    if macd < 0: # Deep zone (simplified as below zero for now, can refine depth)
        if is_gc:
            signals.append(f"[{timeframe}] MACD ゴールデンクロス (安値圏)")
        if is_near_ema20 and hist_improving:
            signals.append(f"[{timeframe}] リターンムーブ買いの可能性 (価格がEMA20に接近 + MACD好転)")

    # SHORT Signal Suitability
    if macd > 0: # High zone
        if is_dc:
            signals.append(f"[{timeframe}] MACD デッドクロス (高値圏)")
        if is_near_ema20 and hist_deteriorating:
             signals.append(f"[{timeframe}] リターンムーブ売りの可能性 (価格がEMA20に接近 + MACD悪化)")
             
    return signals

def main():
    print("ビットコイン・トレンド分析ツールを起動中...")
    print("---------------------------------------------")
    
    # 1. Environment Recognition (Anomaly)
    phase, bias = get_anomaly_phase()
    print(f"サイクルフェーズ: {phase}")
    print(f"戦略的バイアス (大局): {bias}")
    print("---------------------------------------------")

    # 2. Setup Exchange
    exchange = getattr(ccxt, EXCHANGE_ID)()
    
    # 3. Iterate Timeframes and Analyze
    trend_summary = {}
    all_signals = []
    
    rows = []

    for tf_key, tf_val in TIMEFRAMES.items():
        print(f"{tf_key}のデータを取得中...")
        df, error = fetch_data(exchange, SYMBOL, tf_val, LIMIT)
        
        if df is not None:
            df = calculate_indicators(df)
            trend = analyze_trend(df, tf_key)
            trend_summary[tf_key] = trend
            
            signals = detect_signals(df, tf_key)
            all_signals.extend(signals)
            
            # Prepare data for summary table
            last_price = df.iloc[-1]['close']
            sma200 = df.iloc[-1]['SMA200'] if 'SMA200' in df.columns and not pd.isna(df.iloc[-1]['SMA200']) else 0
            macd_val = df.iloc[-1]['MACD'] if 'MACD' in df.columns and not pd.isna(df.iloc[-1]['MACD']) else 0
            rows.append([tf_key, last_price, trend, f"{sma200:.2f}", f"{macd_val:.2f}"])
        else:
            print(f"Error fetching {tf_key}: {error}")
        time.sleep(0.5) # Avoid rate limits

    # 4. Output Summary
    print("\n--- マルチタイムフレーム分析 ---")
    summary_df = pd.DataFrame(rows, columns=["足", "価格", "トレンド", "SMA200", "MACD"])
    print(summary_df.to_string(index=False))
    
    print("\n--- 検知されたシグナル ---")
    if all_signals:
        for sig in all_signals:
            print(f"🔥 {sig}")
    else:
        print("現在、高確率なシグナルは検知されていません。")

    print("\n---------------------------------------------")
    print("確認: 『トレンドはフレンド』。大局の戦略的バイアスに逆らわないようにしましょう。")

if __name__ == "__main__":
    main()
