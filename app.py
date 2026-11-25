import streamlit as st
import yfinance as yf
import pandas as pd
import requests
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

@st.cache_data(ttl=60)
def get_news(ticker):
    try:
        articles = yf.Ticker(ticker).get_news(count=15)
        return articles, None
    except Exception as error:
        return [], str(error)
@st.fragment(run_every="60s")
def show_live_news(symbol):
    st.subheader(f"{symbol} — Latest News")
    st.caption(
        "Checks for new headlines every 60 seconds while this page is active. "
        "Publisher updates may be delayed."
    )

    if st.button("Refresh news now", key="refresh_news"):
        get_news.clear()

    articles, error = get_news(symbol)

    st.caption(
        "Last checked: "
        + pd.Timestamp.now(tz="Europe/London").strftime(
            "%d %b %Y, %H:%M:%S %Z"
        )
    )

    if error:
        st.warning("The news provider could not be reached.")
        with st.expander("Show error details"):
            st.code(error)
        return

    if not articles:
        st.info(
            "No headlines were returned for this ticker. "
            "Try AAPL NEWS or MSFT NEWS. "
            "The provider may also be temporarily unavailable."
        )
        return

    for article in articles:
        content = article.get("content") or article

        title = content.get("title") or "Untitled article"

        canonical = content.get("canonicalUrl") or {}
        clickthrough = content.get("clickThroughUrl") or {}

        url = (
            canonical.get("url")
            or clickthrough.get("url")
            or article.get("link")
        )

        provider = content.get("provider") or {}
        source = (
            provider.get("displayName")
            or article.get("publisher")
            or "Unknown publisher"
        )

        published = content.get("pubDate")
        published_text = "Publication time unavailable"

        if published:
            timestamp = pd.to_datetime(
                published, utc=True, errors="coerce"
            )
            if pd.notna(timestamp):
                published_text = timestamp.tz_convert(
                    "Europe/London"
                ).strftime("%d %b %Y, %H:%M %Z")

        st.markdown("### " + title)
        st.caption(f"{source} | {published_text}")

        summary = content.get("summary")
        if summary:
            st.write(summary)

        if isinstance(url, str) and url.startswith(
            ("https://", "http://")
        ):
            st.link_button("Read original article", url)

        st.divider()

def add_indicators(df):
    df["SMA20"] = df["Close"].rolling(20).mean()
    df["SMA50"] = df["Close"].rolling(50).mean()
    delta = df["Close"].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = -delta.clip(upper=0).rolling(14).mean()
    df["RSI"] = 100 - 100 / (1 + gain / loss)
    return df
    
MACRO_GROUPS = {
    "Indices": {"S&P 500": "^GSPC", "Nasdaq": "^IXIC", "FTSE 100": "^FTSE",
                "DAX": "^GDAXI", "Nikkei 225": "^N225"},
    "FX": {"GBP/USD": "GBPUSD=X", "EUR/USD": "EURUSD=X",
           "USD/JPY": "USDJPY=X", "EUR/GBP": "EURGBP=X"},
    "Commodities": {"Gold": "GC=F", "Brent Oil": "BZ=F",
                    "WTI Oil": "CL=F", "Silver": "SI=F"},
    "Rates & Crypto": {"US 10Y Yield": "^TNX", "VIX": "^VIX",
                       "Bitcoin": "BTC-USD", "Ethereum": "ETH-USD"},
}

@st.cache_data(ttl=300)
def get_macro_quotes(symbols):
    data = yf.download(list(symbols), period="5d", progress=False)["Close"]
    out = {}
    for s in symbols:
        try:
            col = data[s].dropna()
            out[s] = (col.iloc[-1], (col.iloc[-1] / col.iloc[-2] - 1) * 100)
        except Exception:
            out[s] = (None, None)
    return out

def show_macro():
    st.subheader("Macro Overview")
    all_symbols = tuple(s for g in MACRO_GROUPS.values() for s in g.values())
    quotes = get_macro_quotes(all_symbols)
    for group, items in MACRO_GROUPS.items():
        st.markdown(f"### {group}")
        cols = st.columns(len(items))
        for col, (name, sym) in zip(cols, items.items()):
            price, chg = quotes[sym]
            if price is None:
                col.metric(name, "n/a")
            else:
                col.metric(name, f"{price:,.2f}", f"{chg:+.2f}%")

    st.markdown("### Chart")
    names = {n: s for g in MACRO_GROUPS.values() for n, s in g.items()}
    choice = st.selectbox("Pick an asset", list(names))
    hist = get_history(names[choice], "1y", "1d")
    fig = go.Figure(go.Scatter(x=hist.index, y=hist["Close"],
                               line=dict(color="#00ff66")))
    fig.update_layout(template="plotly_dark", height=400, title=choice)
    st.plotly_chart(fig, use_container_width=True)

UK_GROUPS = {
    "UK Indices": {"FTSE 100": "^FTSE", "FTSE 250": "^FTMC", "FTSE All-Share": "^FTAS"},
    "Sterling": {"GBP/USD": "GBPUSD=X", "GBP/EUR": "GBPEUR=X",
                 "GBP/JPY": "GBPJPY=X", "GBP/CHF": "GBPCHF=X"},
    "Gilts & Bonds (ETF proxies)": {"Core UK Gilts": "IGLT.L", "Short Gilts": "IGLS.L",
                                    "Index-linked Gilts": "INXG.L"},
}

UK_SECTORS = {
    "Banks": {"HSBC": "HSBA.L", "Barclays": "BARC.L", "Lloyds": "LLOY.L"},
    "Energy": {"Shell": "SHEL.L", "BP": "BP.L"},
    "Pharma": {"AstraZeneca": "AZN.L", "GSK": "GSK.L"},
    "Consumer": {"Unilever": "ULVR.L", "Diageo": "DGE.L", "Tesco": "TSCO.L"},
    "Mining": {"Rio Tinto": "RIO.L", "Glencore": "GLEN.L"},
    "Telecom/Tech": {"Vodafone": "VOD.L", "BT": "BT-A.L", "Sage": "SGE.L"},
}

def show_uk():
    st.subheader("UK Overview")
    symbols = tuple(s for g in UK_GROUPS.values() for s in g.values())
    quotes = get_macro_quotes(symbols)
    for group, items in UK_GROUPS.items():
        st.markdown(f"### {group}")
        cols = st.columns(len(items))
        for col, (name, sym) in zip(cols, items.items()):
            price, chg = quotes[sym]
            if price is None:
                col.metric(name, "n/a")
            else:
                col.metric(name, f"{price:,.2f}", f"{chg:+.2f}%")

    st.markdown("### Big FTSE stocks by sector (daily % change)")
    stock_symbols = tuple(s for g in UK_SECTORS.values() for s in g.values())
    stock_quotes = get_macro_quotes(stock_symbols)
    rows = []
    for sector, items in UK_SECTORS.items():
        for name, sym in items.items():
            price, chg = stock_quotes[sym]
            if chg is not None:
                rows.append({"Sector": sector, "Stock": name, "Price": price, "Change %": chg})
    if rows:
        df = pd.DataFrame(rows).sort_values("Change %")
        colors = ["#ff3b3b" if c < 0 else "#00ff66" for c in df["Change %"]]
        fig = go.Figure(go.Bar(x=df["Change %"], y=df["Stock"], orientation="h",
                               marker_color=colors))
        fig.update_layout(template="plotly_dark", height=550)
        st.plotly_chart(fig, use_container_width=True)
        sector_avg = df.groupby("Sector")["Change %"].mean().sort_values(ascending=False)
        st.markdown("### Average move by sector")
        st.table(sector_avg.round(2).rename("Avg Change %"))
    else:
        st.warning("No stock data came back. Try again in a minute.")

    st.markdown("### Chart")
    all_names = {n: s for g in UK_GROUPS.values() for n, s in g.items()}
    all_names.update({n: s for g in UK_SECTORS.values() for n, s in g.items()})
    choice = st.selectbox("Pick a UK asset", list(all_names))
    hist = get_history(all_names[choice], "1y", "1d")
    fig2 = go.Figure(go.Scatter(x=hist.index, y=hist["Close"], line=dict(color="#ffb000")))
    fig2.update_layout(template="plotly_dark", height=400, title=choice)
    st.plotly_chart(fig2, use_container_width=True)
@st.cache_data(ttl=60, show_spinner=False)
def fetch_market_headlines():
    api_key = st.secrets.get("FINNHUB_API_KEY", "")

    if not api_key:
        return [], "The FINNHUB_API_KEY secret is missing."

    try:
        response = requests.get(
            "https://finnhub.io/api/v1/news",
            params={"category": "general"},
            headers={"X-Finnhub-Token": api_key},
            timeout=15,
        )

        if response.status_code in (401, 403):
            return [], (
                "Finnhub rejected the request. Check your API key "
                "and whether your plan includes this endpoint."
            )

        if response.status_code == 429:
            return [], (
                "Finnhub's request limit was reached. "
                "Wait a minute before trying again."
            )

        if response.status_code != 200:
            return [], (
                f"Finnhub returned status {response.status_code}. "
                "Please try again later."
            )

        articles = response.json()

        if not isinstance(articles, list):
            return [], "Finnhub returned an unexpected response."

        articles = [
            article
            for article in articles
            if isinstance(article, dict) and article.get("headline")
        ]

        articles.sort(
            key=lambda article: article.get("datetime") or 0,
            reverse=True,
        )

        # Remove duplicate headlines.
        unique_articles = []
        seen = set()

        for article in articles:
            headline = article["headline"].strip().lower()

            if headline not in seen:
                seen.add(headline)
                unique_articles.append(article)

        return unique_articles[:6], None

    except requests.exceptions.Timeout:
        return [], "The news request timed out. Please try again."

    except (requests.exceptions.RequestException, ValueError):
        return [], "Unable to load market news at the moment."


@st.fragment(run_every="60s")
def show_market_headlines():
    st.subheader("Latest Market News")
    st.caption(
        "Recent market headlines from Finnhub. "
        "Checks for updates every 60 seconds while this page is active."
    )

    articles, error = fetch_market_headlines()

    if error:
        st.warning(error)
        return

    if not articles:
        st.info("No market headlines are available right now.")
        return

    checked_at = pd.Timestamp.now(
        tz="Europe/London"
    ).strftime("%d %b %Y, %H:%M:%S %Z")

    st.caption(f"Last checked: {checked_at}")

    # Six stories displayed in two rows of three.
    for start in range(0, len(articles), 3):
        columns = st.columns(3)

        for column, article in zip(
            columns, articles[start:start + 3]
        ):
            with column:
                st.markdown("#### " + article["headline"])

                source = article.get("source") or "Unknown publisher"

                published = pd.to_datetime(
                    article.get("datetime"),
                    unit="s",
                    utc=True,
                    errors="coerce",
                )

                if pd.notna(published):
                    published_text = published.tz_convert(
                        "Europe/London"
                    ).strftime("%d %b, %H:%M %Z")

                    st.caption(f"{source} | {published_text}")
                else:
                    st.caption(source)

                url = article.get("url") or ""

                if url.startswith(("https://", "http://")):
                    st.link_button("Read article", url)

        st.divider()
# ---------- Command bar ----------
st.title("MY TERMINAL")
show_market_headlines()
st.divider()
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
if ticker == "UK" or function == "UK":
    show_uk()

elif ticker == "MACRO" or function == "MACRO":
    show_macro()

elif function == "GP":
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
    show_live_news(ticker)

elif function == "FA":
    st.subheader(f"{ticker} Fundamentals")
    info = yf.Ticker(ticker).info
    keys = ["longName", "sector", "marketCap", "trailingPE", "forwardPE",
            "dividendYield", "fiftyTwoWeekHigh", "fiftyTwoWeekLow"]
    st.table(pd.DataFrame({"Metric": keys, "Value": [info.get(k, "n/a") for k in keys]}))

else:
    st.warning("Unknown function. Try GP, NEWS or FA.")
