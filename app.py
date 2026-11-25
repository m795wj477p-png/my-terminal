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

@st.cache_data(ttl=30, show_spinner=False)
def get_quote(ticker):
    ticker = ticker.strip().upper()

    # Keep Yahoo-style index, forex, crypto and exchange symbols
    # on the existing Yahoo Finance route.
    use_yahoo = (
        ticker.startswith("^")
        or "=" in ticker
        or "-" in ticker
        or "." in ticker
    )

    if use_yahoo:
        try:
            df = yf.Ticker(ticker).history(period="5d")

            if df.empty or "Close" not in df.columns:
                return None, None

            closes = df["Close"].dropna()

            if len(closes) < 2:
                return None, None

            last = float(closes.iloc[-1])
            prev = float(closes.iloc[-2])

            if prev == 0:
                return last, None

            return last, (last / prev - 1) * 100

        except Exception:
            return None, None

    # Plain US stock symbols use Finnhub.
    api_key = st.secrets.get("FINNHUB_API_KEY", "")

    if not api_key:
        return None, None

    try:
        response = requests.get(
            "https://finnhub.io/api/v1/quote",
            params={"symbol": ticker},
            headers={"X-Finnhub-Token": api_key},
            timeout=10,
        )

        if response.status_code != 200:
            return None, None

        quote = response.json()

        if not isinstance(quote, dict) or quote.get("error"):
            return None, None

        price = quote.get("c")
        change_percent = quote.get("dp")
        previous_close = quote.get("pc")

        if price is None:
            return None, None

        price = float(price)

        if pd.isna(price) or price <= 0:
            return None, None

        if change_percent is not None:
            change_percent = float(change_percent)
        elif previous_close is not None and float(previous_close) > 0:
            previous_close = float(previous_close)
            change_percent = (
                (price / previous_close) - 1
            ) * 100
        else:
            return price, None

        if pd.isna(change_percent):
            return price, None

        return price, change_percent

    except (
        requests.exceptions.RequestException,
        TypeError,
        ValueError,
    ):
        return None, None

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

@st.fragment(run_every="10s")
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
                    checked_at = pd.Timestamp.now(
        tz="Europe/London"
    ).strftime("%H:%M:%S")

    st.caption(
        f"Last checked: {checked_at} London time · "
        "Refreshes every 10 seconds"
    )

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
@st.cache_data(ttl=900, show_spinner=False)
def fetch_earnings_calendar(start_date, end_date, symbol):
    api_key = st.secrets.get("FINNHUB_API_KEY", "")

    if not api_key:
        return [], "The FINNHUB_API_KEY secret is missing."

    params = {
        "from": start_date,
        "to": end_date,
    }

    if symbol:
        params["symbol"] = symbol

    try:
        response = requests.get(
            "https://finnhub.io/api/v1/calendar/earnings",
            params=params,
            headers={"X-Finnhub-Token": api_key},
            timeout=20,
        )

        if response.status_code in (401, 403):
            return [], (
                "Finnhub rejected the request. Check your API key "
                "and whether your plan includes this endpoint."
            )

        if response.status_code == 429:
            return [], (
                "Finnhub's request limit was reached. "
                "Please wait a minute and try again."
            )

        if response.status_code != 200:
            return [], (
                f"Finnhub returned status {response.status_code}. "
                "Please try again later."
            )

        payload = response.json()

        if not isinstance(payload, dict):
            return [], "Finnhub returned an unexpected response."

        if payload.get("error"):
            return [], (
                "Finnhub could not provide this calendar. "
                "Check your plan's access and selected date range."
            )

        events = payload.get("earningsCalendar", [])

        if not isinstance(events, list):
            return [], "Finnhub returned an unexpected calendar format."

        return [
            event for event in events if isinstance(event, dict)
        ], None

    except requests.exceptions.Timeout:
        return [], "The request timed out. Please try again."

    except (requests.exceptions.RequestException, ValueError):
        return [], "Unable to load the earnings calendar right now."


def show_earnings_calendar():
    st.subheader("Earnings Calendar")
    st.caption(
        "Upcoming and recent company earnings from Finnhub. "
        "Dates and estimates may change."
    )

    today = pd.Timestamp.now(tz="Europe/London").date()
    next_week = (
        pd.Timestamp(today) + pd.Timedelta(days=7)
    ).date()

    date_col1, date_col2, symbol_col = st.columns(3)

    with date_col1:
        start_date = st.date_input(
            "From",
            value=today,
            key="earnings_start",
        )

    with date_col2:
        end_date = st.date_input(
            "To",
            value=next_week,
            key="earnings_end",
        )

    with symbol_col:
        symbol = st.text_input(
            "Ticker filter (optional)",
            placeholder="Example: AAPL",
            key="earnings_symbol",
        ).strip().upper()

    if end_date < start_date:
        st.warning("The end date must be on or after the start date.")
        return

    if (end_date - start_date).days > 31:
        st.warning("Please select a range of 31 days or less.")
        return

    if st.button("Refresh calendar", key="refresh_earnings"):
        fetch_earnings_calendar.clear()

    with st.spinner("Loading earnings calendar..."):
        events, error = fetch_earnings_calendar(
            start_date.isoformat(),
            end_date.isoformat(),
            symbol,
        )

    if error:
        st.warning(error)
        return

    if not events:
        st.info(
            "No earnings releases were returned for this selection. "
            "Try another date range or clear the ticker filter. "
            "Coverage may also depend on your Finnhub plan."
        )
        return

    df = pd.DataFrame(events)

    required_columns = [
        "date",
        "symbol",
        "hour",
        "epsEstimate",
        "epsActual",
        "revenueEstimate",
        "revenueActual",
    ]

    for column in required_columns:
        if column not in df.columns:
            df[column] = None

    numeric_columns = [
        "epsEstimate",
        "epsActual",
        "revenueEstimate",
        "revenueActual",
    ]

    for column in numeric_columns:
        df[column] = pd.to_numeric(
            df[column], errors="coerce"
        )

    df["date"] = pd.to_datetime(
        df["date"], errors="coerce"
    )

    df = df.sort_values(
        ["date", "symbol"], na_position="last"
    )

    timing_labels = {
        "bmo": "Before market open",
        "amc": "After market close",
        "dmh": "During market hours",
    }

    df["Timing"] = df["hour"].map(
        timing_labels
    ).fillna("Not specified")

    metric_col1, metric_col2, metric_col3 = st.columns(3)

    metric_col1.metric("Scheduled releases", len(df))
    metric_col2.metric(
        "Before market open",
        int((df["hour"] == "bmo").sum()),
    )
    metric_col3.metric(
        "After market close",
        int((df["hour"] == "amc").sum()),
    )

    def format_eps(value):
        if pd.isna(value):
            return "—"
        return f"{value:,.2f}"

    def format_revenue(value):
        if pd.isna(value):
            return "—"

        magnitude = abs(value)

        if magnitude >= 1_000_000_000:
            return f"{value / 1_000_000_000:,.2f}B"

        if magnitude >= 1_000_000:
            return f"{value / 1_000_000:,.2f}M"

        return f"{value:,.0f}"

    display = pd.DataFrame({
        "Date": df["date"].dt.strftime("%d %b %Y"),
        "Ticker": df["symbol"],
        "Reporting time": df["Timing"],
        "Estimated EPS": df["epsEstimate"].map(format_eps),
        "Actual EPS": df["epsActual"].map(format_eps),
        "Estimated revenue": df["revenueEstimate"].map(
            format_revenue
        ),
        "Actual revenue": df["revenueActual"].map(
            format_revenue
        ),
    })

    st.dataframe(
        display,
        hide_index=True,
        use_container_width=True,
    )

    st.caption(
        "— means no figure was supplied. "
        "M = million; B = billion. "
        "Figures are displayed as supplied, without currency conversion. "
        "The response does not identify currency in this table."
    )

    st.download_button(
        "Download calendar as CSV",
        data=df[
            required_columns
        ].to_csv(index=False).encode("utf-8"),
        file_name="earnings_calendar.csv",
        mime="text/csv",
        key="download_earnings",
    )
@st.cache_data(ttl=900, show_spinner=False)
def fetch_basic_financials(symbol):
    api_key = st.secrets.get("FINNHUB_API_KEY", "")

    if not api_key:
        return None, "The FINNHUB_API_KEY secret is missing."

    try:
        response = requests.get(
            "https://finnhub.io/api/v1/stock/metric",
            params={
                "symbol": symbol,
                "metric": "all",
            },
            headers={"X-Finnhub-Token": api_key},
            timeout=20,
        )

        if response.status_code in (401, 403):
            return None, (
                "Finnhub rejected the request. Check your API key "
                "and whether your plan includes this endpoint."
            )

        if response.status_code == 429:
            return None, (
                "Finnhub's request limit was reached. "
                "Please wait a minute and try again."
            )

        if response.status_code != 200:
            return None, (
                f"Finnhub returned status {response.status_code}. "
                "Please try again later."
            )

        payload = response.json()

        if not isinstance(payload, dict):
            return None, "Finnhub returned an unexpected response."

        if payload.get("error"):
            return None, (
                "Finnhub could not provide basic financials for "
                f"{symbol}. Check the ticker and your plan's coverage."
            )

        metrics = payload.get("metric", {})

        if not isinstance(metrics, dict) or not metrics:
            return None, (
                f"No basic financials were returned for {symbol}. "
                "Try another ticker."
            )

        return metrics, None

    except requests.exceptions.Timeout:
        return None, "The request timed out. Please try again."

    except (requests.exceptions.RequestException, ValueError):
        return None, "Unable to load basic financials right now."


def show_basic_financials():
    st.subheader("Basic Financials")
    st.caption(
        "Key valuation, profitability, liquidity, growth and "
        "52-week price metrics from Finnhub. "
        "Figures may be unavailable for some companies."
    )

    ticker = st.text_input(
        "Ticker",
        value="AAPL",
        key="basic_financials_ticker",
    ).strip().upper()

    if not ticker:
        st.info("Enter a ticker to load basic financials.")
        return

    if st.button("Refresh financials", key="refresh_basic_financials"):
        fetch_basic_financials.clear()

    with st.spinner(f"Loading financials for {ticker}..."):
        metrics, error = fetch_basic_financials(ticker)

    if error:
        st.warning(error)
        return

    def get_metric(name):
        value = metrics.get(name)

        if value in (None, ""):
            return None

        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def format_percent(value):
        if value is None:
            return "—"
        return f"{value:,.2f}%"

    def format_ratio(value):
        if value is None:
            return "—"
        return f"{value:,.2f}"

    def format_large_number(value):
        if value is None:
            return "—"

        magnitude = abs(value)

        if magnitude >= 1_000_000_000:
            return f"{value / 1_000_000_000:,.2f}B"

        if magnitude >= 1_000_000:
            return f"{value / 1_000_000:,.2f}M"

        if magnitude >= 1_000:
            return f"{value / 1_000:,.2f}K"

        return f"{value:,.0f}"

    valuation_col1, valuation_col2, valuation_col3 = st.columns(3)

    valuation_col1.metric(
        "P/E ratio",
        format_ratio(get_metric("peBasicExcludingExtraItemsTTM")),
    )

    valuation_col2.metric(
        "P/B ratio",
        format_ratio(get_metric("pbAnnual")),
    )

    valuation_col3.metric(
        "P/S ratio",
        format_ratio(get_metric("psAnnual")),
    )

    profitability_col1, profitability_col2, profitability_col3 = st.columns(3)

    profitability_col1.metric(
        "Gross margin",
        format_percent(get_metric("grossMarginTTM")),
    )

    profitability_col2.metric(
        "Operating margin",
        format_percent(get_metric("operatingMarginTTM")),
    )

    profitability_col3.metric(
        "Net margin",
        format_percent(get_metric("netProfitMarginTTM")),
    )

    liquidity_col1, liquidity_col2, liquidity_col3 = st.columns(3)

    liquidity_col1.metric(
        "Current ratio",
        format_ratio(get_metric("currentRatioAnnual")),
    )

    liquidity_col2.metric(
        "Quick ratio",
        format_ratio(get_metric("quickRatioAnnual")),
    )

    liquidity_col3.metric(
        "Debt/equity",
        format_ratio(get_metric("totalDebt/totalEquityAnnual")),
    )

    growth_col1, growth_col2, growth_col3 = st.columns(3)

    growth_col1.metric(
        "Revenue growth",
        format_percent(get_metric("revenueGrowthTTMYoy")),
    )

    growth_col2.metric(
        "EPS growth",
        format_percent(get_metric("epsGrowthTTMYoy")),
    )

    growth_col3.metric(
        "Dividend yield",
        format_percent(get_metric("dividendYieldIndicatedAnnual")),
    )

    price_col1, price_col2, price_col3 = st.columns(3)

    price_col1.metric(
        "52-week high",
        format_ratio(get_metric("52WeekHigh")),
    )

    price_col2.metric(
        "52-week low",
        format_ratio(get_metric("52WeekLow")),
    )

    price_col3.metric(
        "Beta",
        format_ratio(get_metric("beta")),
    )

    volume_col1, volume_col2, volume_col3 = st.columns(3)

    volume_col1.metric(
        "10-day average volume",
        format_large_number(
            get_metric("10DayAverageTradingVolume")
        ),
    )

    volume_col2.metric(
        "3-month average volume",
        format_large_number(
            get_metric("3MonthAverageTradingVolume")
        ),
    )

    volume_col3.metric(
        "10-day average price",
        format_ratio(
            get_metric("10DayAverageTradingPrice")
        ),
    )

    st.caption(
        "— means Finnhub did not return that metric. "
        "Some figures may be annual rather than trailing-twelve-month "
        "values, depending on the metric. "
        "This panel is for research, not investment advice."
    )
# ---------- Toolbar and command bar ----------
if "terminal_command" not in st.session_state:
    st.session_state["terminal_command"] = "AAPL GP"

if "terminal_last_ticker" not in st.session_state:
    st.session_state["terminal_last_ticker"] = "AAPL"


def open_terminal_panel(panel):
    parts = (
        st.session_state["terminal_command"]
        .strip()
        .upper()
        .split()
    )

    reserved_commands = {
        "GP", "NEWS", "FA", "EARNINGS", "UK", "MACRO"
    }

    if parts and parts[0] not in reserved_commands:
        st.session_state["terminal_last_ticker"] = parts[0]

    selected_ticker = st.session_state["terminal_last_ticker"]

    if panel in {"UK", "MACRO", "EARNINGS"}:
        st.session_state["terminal_command"] = panel
    else:
        st.session_state["terminal_command"] = (
            f"{selected_ticker} {panel}"
        )


st.title("MY TERMINAL")

toolbar_items = [
    ("Chart", "GP"),
    ("UK", "UK"),
    ("Macro", "MACRO"),
    ("Company News", "NEWS"),
    ("Earnings", "EARNINGS"),
    ("Financials", "FA"),
]

toolbar_columns = st.columns(len(toolbar_items))

for column, (label, panel) in zip(
    toolbar_columns, toolbar_items
):
    with column:
        st.button(
            label,
            key=f"terminal_nav_{panel}",
            on_click=open_terminal_panel,
            args=(panel,),
            use_container_width=True,
        )

show_market_headlines()
st.divider()

command_text = st.text_input(
    "Command (e.g. AAPL GP, TSLA NEWS, MSFT FA)",
    key="terminal_command",
)

cmd = command_text.strip().upper().split()

ticker = cmd[0] if cmd else "AAPL"
function = cmd[1] if len(cmd) > 1 else "GP"

reserved_commands = {
    "GP", "NEWS", "FA", "EARNINGS", "UK", "MACRO"
}

if ticker not in reserved_commands:
    st.session_state["terminal_last_ticker"] = ticker
# ---------- Sidebar ----------
@st.fragment(run_every="10s")
def show_watchlist():
    st.header("Watchlist")

    watchlist = st.text_area(
        "Tickers",
        value=(
            "GC=F\n"
            "NQ=F\n"
            "EURUSD=X\n"
            "GBPUSD=X\n"
            "BTC-USD"
        ),
        height=230,
        key="watchlist_tickers",
    ).upper().split()

    for t in dict.fromkeys(watchlist):
        try:
            price, chg = get_quote(t)

            if price is not None:
                change_text = (
                    f"{chg:+.2f}%"
                    if chg is not None
                    else None
                )

                st.metric(
                    t,
                    f"{price:,.2f}",
                    change_text,
                )
            else:
                st.caption(f"{t}: price unavailable")

        except Exception:
            st.caption(f"{t}: unable to load price")

    checked_at = pd.Timestamp.now(
        tz="Europe/London"
    ).strftime("%H:%M:%S")

    st.caption(f"Last checked: {checked_at} London time")
    st.caption(
        "Checks every 10 seconds while this session is active. "
        "US stocks: Finnhub. Yahoo-style index, forex, crypto "
        "and exchange symbols: Yahoo Finance. "
        "Prices may be delayed or unchanged."
    )


with st.sidebar:
    show_watchlist()

period = st.sidebar.selectbox("Period", ["1mo", "3mo", "6mo", "1y", "5y"], index=3)
interval = st.sidebar.selectbox("Interval", ["1d", "1wk", "1h"], index=0)

# ---------- Panels ----------
if ticker == "FA" or function == "FA":
    show_basic_financials()

elif ticker == "EARNINGS" or function == "EARNINGS":
    show_earnings_calendar()

elif ticker == "UK" or function == "UK":
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
