import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import ccxt
import analysis_logic as logic

# --- Configuration ---
st.set_page_config(
    page_title="Bitcoin Trend Analysis",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- Custom CSS for Premium Feel ---
st.markdown("""
<style>
    /* Dark Mode Global Overrides */
    .stApp {
        background-color: #0E1117;
        color: #FAFAFA;
    }
    
    /* Metrics Card Style */
    div[data-testid="stMetric"] {
        background-color: #1E2127;
        padding: 15px;
        border-radius: 10px;
        border: 1px solid #333;
    }
    
    /* Header Gold Accent */
    h1, h2, h3 {
        color: #D4AF37 !important; 
    }
    
    /* Table Styling */
    div[data-testid="stDataFrame"] {
        border-radius: 10px;
        overflow: hidden;
    }
</style>
""", unsafe_allow_html=True)

# --- Sidebar ---
st.sidebar.title("設定")
symbol = st.sidebar.text_input("シンボル", value="BTC/USDT")
exchange_id = st.sidebar.selectbox("取引所", ["binance", "bybit", "bitget"], index=0)

st.sidebar.markdown("---")
st.sidebar.write("Developed based on Cycle & Trend Logic")

# --- Main Functions ---

@st.cache_data(ttl=300) # Cache data for 5 minutes
def load_data(exch_id, sym, tf, limit):
    exchange = getattr(ccxt, exch_id)()
    return logic.fetch_data(exchange, sym, tf, limit)

def plot_chart(df, timeframe):
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, 
                        vertical_spacing=0.03, subplot_titles=(f'{symbol} {timeframe} Chart', 'MACD'), 
                        row_width=[0.2, 0.7])

    # Candlestick
    fig.add_trace(go.Candlestick(x=df['timestamp'],
                open=df['open'], high=df['high'],
                low=df['low'], close=df['close'], name="Price"), row=1, col=1)

    # MAs
    colors = {'SMA7': 'yellow', 'SMA25': 'orange', 'SMA100': 'cyan', 'SMA200': 'purple', 'EMA20': 'white'}
    for ma, color in colors.items():
        if ma in df.columns:
            fig.add_trace(go.Scatter(x=df['timestamp'], y=df[ma], name=ma, line=dict(color=color, width=1)), row=1, col=1)

    # MACD
    if 'MACD' in df.columns:
        fig.add_trace(go.Scatter(x=df['timestamp'], y=df['MACD'], name='MACD', line=dict(color='blue', width=1)), row=2, col=1)
        fig.add_trace(go.Scatter(x=df['timestamp'], y=df['MACD_Signal'], name='Signal', line=dict(color='orange', width=1)), row=2, col=1)
        fig.add_trace(go.Bar(x=df['timestamp'], y=df['MACD_Hist'], name='Histogram'), row=2, col=1)

    fig.update_layout(height=800, xaxis_rangeslider_visible=False, template="plotly_dark")
    return fig

# --- App Layout ---

# Header
st.title("📈 Bitcoin Trend Analysis Tool")
st.markdown(f"**Symbol:** {symbol} | **Exchange:** {exchange_id.upper()}")

# 1. Environment (Anomaly)
phase, bias = logic.get_anomaly_phase()
col1, col2 = st.columns(2)
with col1:
    st.metric(label="サイクルフェーズ (4年周期)", value=phase)
with col2:
    st.metric(label="戦略的バイアス (大局)", value=bias, delta_color="off") # Delta color off to keep it neutral/custom

st.markdown("---")

# 2. Multi-Timeframe Analysis
st.subheader("マルチタイムフレーム分析")

# Fetch all data first to show table
tfs = logic.TIMEFRAMES
rows = []
all_signals = []

# Progress bar
progress_text = "データを取得中..."
my_bar = st.progress(0, text=progress_text)
percent_complete = 0
step = 100 // len(tfs)

# Store DataFrames for charting later
dfs = {}

for i, (tf_key, tf_val) in enumerate(tfs.items()):
    df = load_data(exchange_id, symbol, tf_val, logic.LIMIT)
    df = logic.calculate_indicators(df)
    dfs[tf_key] = df
    
    trend = logic.analyze_trend(df, tf_key)
    signals = logic.detect_signals(df, tf_key)
    all_signals.extend(signals)
    
    if df is not None and not df.empty:
         last_row = df.iloc[-1]
         price = last_row['close']
         sma200 = last_row.get('SMA200', 0)
         macd = last_row.get('MACD', 0)
         rows.append([tf_key, f"{price:,.2f}", trend, f"{sma200:,.2f}" if not pd.isna(sma200) else "N/A", f"{macd:.2f}" if not pd.isna(macd) else "N/A"])
    else:
        rows.append([tf_key, "N/A", "Error", "N/A", "N/A"])

    percent_complete += step
    my_bar.progress(min(percent_complete, 100), text=f"{tf_key} 完了")

my_bar.empty()

# Display Table
summary_df = pd.DataFrame(rows, columns=["時間足", "価格", "トレンド", "SMA200", "MACD"])

# Style the table: Color code trend
def color_trend(val):
    color = 'white'
    if val == "上昇トレンド":
        color = '#90EE90' # Light green
    elif val == "下降トレンド":
        color = '#FFB6C1' # Light pink
    return f'color: {color}'

st.dataframe(summary_df.style.map(color_trend, subset=['トレンド']), use_container_width=True)

# 3. Signals
st.subheader("🔥 検知されたシグナル")
if all_signals:
    for sig in all_signals:
        st.warning(sig, icon="⚠️")
else:
    st.info("現在、高確率なシグナルは検知されていません。", icon="✅")

st.markdown("---")

# 4. Detailed Charts
st.subheader("詳細チャート分析")
selected_tf = st.selectbox("チャートを表示する時間足を選択", list(tfs.keys()), index=2) # Default to Daily or 1d (index 2)

if selected_tf in dfs:
    st.plotly_chart(plot_chart(dfs[selected_tf], selected_tf), use_container_width=True)
else:
    st.error("データの読み込みに失敗しました。")

# Footer
st.markdown("---")
st.caption("Disclaimer: This tool is for informational purposes only. Trading cryptocurrencies involves significant risk.")
