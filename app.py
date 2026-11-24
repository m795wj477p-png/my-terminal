import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

st.set_page_config(page_title="My Terminal", layout="wide")

st.markdown("""
<style>
.stApp {background-color:#000; color:#ffb000;}
h1,h2,h3,label,p,span {color:#ffb000 !important; font-family:monospace;}
[data-testid="stMetricValue"] {color:#00ff66;}
</style>
""", unsafe_allow_html=True)

# ---------- Data helpers ----------
@st.cache_data(ttl=300)
def get_history(ticker, period, interval):
    df = yf.Ticker(ticker).history(period=period, interval=interval)
    return df.dropna()

@st.cache_data(ttl=300)
def get_quote(ticker):
    df = yf.Ticker(ticker).history(period="5d")
    if len(df) < 2:
        return None, None
    last, prev = df["Close"].iloc[-1], df["Close"].iloc[-2]
    return last, (last / prev - 1) * 100

@st.cache_data(ttl=600)
def get_news(ticker):
    try:
        return yf.Ticker(ticker).news[:8]
    except Exception:
        return []

def add_indicators(df):
    df["SMA20"] = df["Close"].rolling(20).mean()
    df["SMA50"] = df["Close"].rolling(50).mean()
    delta = df["Close"].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = -delta.clip(upper=0).rolling(14).mean()
    df["RSI"] = 100 - 100 / (1 + gain / loss)
    return df

# ---------- Command bar ----------
st.title("MY TERMINAL")
cmd = st.text_input("Command (e.g. AAPL GP, TSLA NEWS, MSFT FA)", "AAPL GP").upper().split()
ticker = cmd[0] if cmd else "AAPL"
function = cmd[1] if len(cmd) > 1 else "GP"

# ---------- Sidebar ----------
st.sidebar.header("Watchlist")
watchlist = st.sidebar.text_area("Tickers", "AAPL\nMSFT\nTSLA\n^GSPC\nGBPUSD=X\nBTC-USD").split()
for t in watchlist:
    price, chg = get_quote(t)
    if price is not None:
        st.sidebar.metric(t, f"{price:,.2f}", f"{chg:+.2f}%")

period = st.sidebar.selectbox("Period", ["1mo", "3mo", "6mo", "1y", "5y"], index=3)
interval = st.sidebar.selectbox("Interval", ["1d", "1wk", "1h"], index=0)

# ---------- Panels ----------
if function == "GP":
    df = add_indicators(get_history(ticker, period, interval))
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        row_heights=[0.75, 0.25], vertical_spacing=0.03)
    fig.add_trace(go.Candlestick(x=df.index, open=df["Open"], high=df["High"],
                                 low=df["Low"], close=df["Close"], name=ticker), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["SMA20"], name="SMA20",
                             line=dict(color="cyan", width=1)), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["SMA50"], name="SMA50",
                             line=dict(color="magenta", width=1)), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["RSI"], name="RSI",
                             line=dict(color="orange")), row=2, col=1)
    fig.add_hline(y=70, line_dash="dot", line_color="red", row=2, col=1)
    fig.add_hline(y=30, line_dash="dot", line_color="green", row=2, col=1)
    fig.update_layout(template="plotly_dark", height=700,
                      xaxis_rangeslider_visible=False, title=f"{ticker} Price Chart")
    st.plotly_chart(fig, use_container_width=True)

elif function == "NEWS":
    st.subheader(f"{ticker} News")
    for n in get_news(ticker):
        content = n.get("content", n)
        title = content.get("title", "No title")
        url = (content.get("canonicalUrl") or {}).get("url") or n.get("link", "")
        st.markdown(f"- [{title}]({url})")

elif function == "FA":
    st.subheader(f"{ticker} Fundamentals")
    info = yf.Ticker(ticker).info
    keys = ["longName", "sector", "marketCap", "trailingPE", "forwardPE",
            "dividendYield", "fiftyTwoWeekHigh", "fiftyTwoWeekLow"]
    st.table(pd.DataFrame({"Metric": keys, "Value": [info.get(k, "n/a") for k in keys]}))

else:
    st.warning("Unknown function. Try GP, NEWS or FA.")
