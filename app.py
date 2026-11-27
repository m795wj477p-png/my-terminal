import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import io
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

FRED_SERIES = {
    "1M": ("DGS1MO", 1/12), "3M": ("DGS3MO", 0.25), "6M": ("DGS6MO", 0.5),
    "1Y": ("DGS1", 1), "2Y": ("DGS2", 2), "3Y": ("DGS3", 3),
    "5Y": ("DGS5", 5), "7Y": ("DGS7", 7), "10Y": ("DGS10", 10),
    "20Y": ("DGS20", 20), "30Y": ("DGS30", 30),
}

@st.cache_data(ttl=3600)
def load_curve_data(days=120):
    key = st.secrets["FRED_API_KEY"]
    start = (pd.Timestamp.today() - pd.Timedelta(days=days)).strftime("%Y-%m-%d")
    frames = {}
    for label, (sid, _) in FRED_SERIES.items():
        r = requests.get(
            "https://api.stlouisfed.org/fred/series/observations",
            params={"series_id": sid, "api_key": key, "file_type": "json",
                    "observation_start": start},
            timeout=15,
        )
        r.raise_for_status()
        obs = pd.DataFrame(r.json()["observations"])
        obs["value"] = pd.to_numeric(obs["value"], errors="coerce")
        frames[label] = obs.set_index("date")["value"]
    df = pd.DataFrame(frames).dropna(how="all")
    df.index = pd.to_datetime(df.index)
    return df.sort_index()

def render_curve_panel():
    st.subheader("US TREASURY YIELD CURVE")
    days = st.selectbox("Lookback", [30, 60, 90, 180, 365], index=2)
    try:
        df = load_curve_data(max(days, 400)).dropna()
    except Exception as e:
        st.error(f"Could not load FRED data: {e}")
        return
    df = df[df.index >= df.index.max() - pd.Timedelta(days=days)]
    tenors = list(FRED_SERIES.keys())

    # 3D surface
    surf = go.Figure(go.Surface(
        x=tenors, y=df.index.strftime("%Y-%m-%d"), z=df[tenors].values,
        colorscale="Turbo", colorbar=dict(title="Yield %"),
    ))
    surf.update_layout(
        template="plotly_dark", height=550, margin=dict(l=0, r=0, t=30, b=0),
        scene=dict(xaxis_title="Maturity", yaxis_title="Date", zaxis_title="Yield %"),
    )
    st.plotly_chart(surf, use_container_width=True)

    # Curve snapshots
    c1, c2 = st.columns(2)
    latest = df.iloc[-1]
    week = df.iloc[max(-6, -len(df))]
    month = df.iloc[max(-22, -len(df))]
    snap = go.Figure()
    for name, row, col in [("Today", latest, "#00ff88"),
                           ("1W ago", week, "#ffaa00"),
                           ("1M ago", month, "#888888")]:
        snap.add_trace(go.Scatter(x=tenors, y=row[tenors], name=name,
                                  mode="lines+markers", line=dict(color=col)))
    snap.update_layout(template="plotly_dark", height=350,
                       title=f"Curve as of {df.index[-1].date()}",
                       yaxis_title="Yield %")
    c1.plotly_chart(snap, use_container_width=True)

    # 2s10s spread (bps)
    spread = (df["10Y"] - df["2Y"]) * 100
    sp = go.Figure(go.Scatter(x=df.index, y=spread, line=dict(color="#4da6ff")))
    sp.add_hline(y=0, line_dash="dot", line_color="red")
    sp.update_layout(template="plotly_dark", height=350,
                     title="2s10s spread (bps)", yaxis_title="bps")
    c2.plotly_chart(sp, use_container_width=True)

    # Change table
    chg = pd.DataFrame({
        "Yield %": latest[tenors],
        "1D chg (bp)": (latest - df.iloc[-2])[tenors] * 100,
        "1W chg (bp)": (latest - week)[tenors] * 100,
        "1M chg (bp)": (latest - month)[tenors] * 100,
    }).round(2)
    st.dataframe(
        chg.style.background_gradient(
            cmap="RdYlGn_r", subset=["1D chg (bp)", "1W chg (bp)", "1M chg (bp)"], axis=None
        ).format("{:.2f}"),
        use_container_width=True,
    )
    st.caption("Source: FRED (St. Louis Fed). Daily data, published with a one-day lag.")

BOE_SERIES = {
    "5Y": "IUDSNPY",
    "10Y": "IUDMNPY",
    "20Y": "IUDLNPY",
}
BOE_BANK_RATE = "IUDBEDR"

@st.cache_data(ttl=3600)
def load_gilt_data(days=400):
    start = (pd.Timestamp.today() - pd.Timedelta(days=days)).strftime("%d/%b/%Y")
    codes = ",".join(list(BOE_SERIES.values()) + [BOE_BANK_RATE])
    url = (
        "https://www.bankofengland.co.uk/boeapps/database/_iadb-fromshowcolumns.asp"
        f"?csv.x=yes&Datefrom={start}&Dateto=now&SeriesCodes={codes}"
        "&CSVF=TN&UsingCodes=Y&VPD=Y&VFD=N"
    )
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    df.columns = [c.strip() for c in df.columns]
    df["DATE"] = pd.to_datetime(df["DATE"], format="%d %b %Y", errors="coerce")
    df = df.dropna(subset=["DATE"]).set_index("DATE").sort_index()
    rename = {v: k for k, v in BOE_SERIES.items()}
    rename[BOE_BANK_RATE] = "Bank Rate"
    df = df.rename(columns=rename).apply(pd.to_numeric, errors="coerce")
    df["Bank Rate"] = df["Bank Rate"].ffill()
    return df.dropna(subset=list(BOE_SERIES.keys()))

def render_gilt_panel():
    st.subheader("UK GILT YIELDS")
    days = st.selectbox("Lookback", [30, 60, 90, 180, 365], index=2, key="gilt_days")
    try:
        df = load_gilt_data()
    except Exception as e:
        st.error(f"Could not load Bank of England data: {e}")
        return
    if len(df) < 2:
        st.warning("Not enough gilt data returned.")
        return
    full = df
    df = df[df.index >= df.index.max() - pd.Timedelta(days=days)]
    tenors = list(BOE_SERIES.keys())

    c1, c2 = st.columns(2)

    latest = full.iloc[-1]
    week = full.iloc[max(-6, -len(full))]
    month = full.iloc[max(-22, -len(full))]
    snap = go.Figure()
    for name, row, col in [("Latest", latest, "#00ff88"),
                           ("1W ago", week, "#ffaa00"),
                           ("1M ago", month, "#888888")]:
        snap.add_trace(go.Scatter(x=tenors, y=row[tenors], name=name,
                                  mode="lines+markers", line=dict(color=col)))
    snap.update_layout(template="plotly_dark", height=350,
                       title=f"Gilt curve as of {full.index[-1].date()}",
                       yaxis_title="Par yield %")
    c1.plotly_chart(snap, use_container_width=True)

    hist = go.Figure()
    for t in tenors:
        hist.add_trace(go.Scatter(x=df.index, y=df[t], name=t, mode="lines"))
    hist.update_layout(template="plotly_dark", height=350,
                       title="Yield history", yaxis_title="Par yield %")
    c2.plotly_chart(hist, use_container_width=True)

    spread = (df["20Y"] - df["5Y"]) * 100
    sp = go.Figure(go.Scatter(x=df.index, y=spread, line=dict(color="#4da6ff")))
    sp.add_hline(y=0, line_dash="dot", line_color="red")
    sp.update_layout(template="plotly_dark", height=300,
                     title="5s20s spread (bps)", yaxis_title="bps")
    st.plotly_chart(sp, use_container_width=True)

    cols = tenors + ["Bank Rate"]
    chg = pd.DataFrame({
        "Yield %": latest[cols],
        "1D chg (bp)": (latest - full.iloc[-2])[cols] * 100,
        "1W chg (bp)": (latest - week)[cols] * 100,
        "1M chg (bp)": (latest - month)[cols] * 100,
    }).round(2)
    st.dataframe(
        chg.style.background_gradient(
            cmap="RdYlGn_r", subset=["1D chg (bp)", "1W chg (bp)", "1M chg (bp)"], axis=None
        ).format("{:.2f}"),
        use_container_width=True,
    )
    st.caption("Source: Bank of England. Nominal par yields, estimated daily; latest figures can lag by a day or more.")

ECON_SERIES = {
    "CPI (YoY)": ("CPIAUCSL", "yoy"),
    "PPI (YoY)": ("PPIACO", "yoy"),
    "Jobless Claims": ("ICSA", "count"),
    "Unemployment": ("UNRATE", "pct"),
}

@st.cache_data(ttl=1800, show_spinner=False)
def get_econ_series(series_id, kind):
    key = st.secrets["FRED_API_KEY"]
    start = (pd.Timestamp.today() - pd.Timedelta(days=900)).strftime("%Y-%m-%d")
    r = requests.get(
        "https://api.stlouisfed.org/fred/series/observations",
        params={"series_id": series_id, "api_key": key,
                "file_type": "json", "observation_start": start},
        timeout=15,
    )
    r.raise_for_status()
    s = pd.DataFrame(r.json()["observations"])
    s["value"] = pd.to_numeric(s["value"], errors="coerce")
    s = s.dropna(subset=["value"])
    s.index = pd.to_datetime(s["date"])
    v = s["value"]
    if kind == "yoy":
        v = (v.pct_change(12) * 100).dropna()
    return float(v.iloc[-1]), float(v.iloc[-2]), v.index[-1].date()

REAL_SERIES = {
    "US 10Y Real Yield": ("DFII10", "pct"),
    "US 10Y Yield": ("DGS10", "pct"),
    "10Y Breakeven": ("T10YIE", "pct"),
    "Broad USD Index": ("DTWEXBGS", "index"),
}

@st.cache_data(ttl=3600, show_spinner=False)
def get_daily_series(series_id):
    key = st.secrets["FRED_API_KEY"]
    start = (pd.Timestamp.today() - pd.Timedelta(days=30)).strftime("%Y-%m-%d")
    r = requests.get(
        "https://api.stlouisfed.org/fred/series/observations",
        params={"series_id": series_id, "api_key": key,
                "file_type": "json", "observation_start": start},
        timeout=15,
    )
    r.raise_for_status()
    s = pd.DataFrame(r.json()["observations"])
    s["value"] = pd.to_numeric(s["value"], errors="coerce")
    s = s.dropna(subset=["value"])
    return float(s["value"].iloc[-1]), float(s["value"].iloc[-2]), s["date"].iloc[-1]

def show_real_yields_dollar():
    from html import escape

    st.markdown("### Real Yields & Dollar")
    cols = st.columns(len(REAL_SERIES))

    for col, (name, (sid, kind)) in zip(cols, REAL_SERIES.items()):
        safe_name = escape(str(name))
        try:
            latest, prev, d = get_daily_series(sid)
        except Exception:
            col.metric(name, "n/a")
            continue

        diff = latest - prev
        if kind == "pct":
            value_text = f"{latest:.2f}%"
            change_text = f"{diff * 100:+.0f} bp"
        else:
            value_text = f"{latest:.2f}"
            change_text = f"{diff / prev * 100:+.2f}%"

        if diff > 0:
            colour = "#22c55e"
        elif diff < 0:
            colour = "#ef4444"
        else:
            colour = "#9ca3af"
            change_text = "unchanged"

        col.html(
            f"""
            <div style="
                border: 1px solid rgba(128,128,128,0.25);
                border-radius: 10px;
                padding: 10px 12px;
                margin-bottom: 12px;
                box-sizing: border-box;
                width: 100%;
                overflow: hidden;
            ">
                <div style="
                    font-size: 13px;
                    margin-bottom: 6px;
                    white-space: nowrap;
                    overflow: hidden;
                    text-overflow: ellipsis;
                ">{safe_name}</div>
                <div style="font-size: 22px; font-weight: 600; color: {colour};">{value_text}</div>
                <div style="font-size: 13px; color: {colour};">{change_text}</div>
                <div style="font-size: 11px; opacity: 0.6; margin-top: 4px;">As of {d}</div>
            </div>
            """
        )
def show_econ_releases():
    from html import escape
        
    st.markdown("### Economic Releases")
    cols = st.columns(len(ECON_SERIES))

    for col, (name, (sid, kind)) in zip(cols, ECON_SERIES.items()):
        safe_name = escape(str(name))
        try:
            latest, prev, d = get_econ_series(sid, kind)
        except Exception:
            col.metric(name, "n/a")
            continue

        diff = latest - prev
        if kind == "count":
            value_text = f"{latest:,.0f}"
            change_text = f"{diff:+,.0f}"
        else:
            value_text = f"{latest:.2f}%"
            change_text = f"{diff:+.2f} pts"

        if diff > 0:
            colour = "#22c55e"
        elif diff < 0:
            colour = "#ef4444"
        else:
            colour = "#9ca3af"
            change_text = "unchanged"

        col.html(
            f"""
            <div style="
                border: 1px solid rgba(128,128,128,0.25);
                border-radius: 10px;
                padding: 10px 12px;
                margin-bottom: 12px;
                box-sizing: border-box;
                width: 100%;
                overflow: hidden;
            ">
                <div style="
                    font-size: 13px;
                    margin-bottom: 6px;
                    white-space: nowrap;
                    overflow: hidden;
                    text-overflow: ellipsis;
                ">{safe_name}</div>
                <div style="font-size: 22px; font-weight: 600; color: {colour};">{value_text}</div>
                <div style="font-size: 13px; color: {colour};">{change_text}</div>
                <div style="font-size: 11px; opacity: 0.6; margin-top: 4px;">Period: {d}</div>
            </div>
            """
        )

COT_MARKETS = {
    "EUR (Euro FX)": ("gpe5-46if", "099741", "lev_money_positions_long", "lev_money_positions_short"),
    "GBP (British Pound)": ("gpe5-46if", "096742", "lev_money_positions_long", "lev_money_positions_short"),
    "USD Index": ("gpe5-46if", "098662", "lev_money_positions_long", "lev_money_positions_short"),
    "Gold": ("72hh-3qpy", "088691", "m_money_positions_long_all", "m_money_positions_short_all"),
}

@st.cache_data(ttl=6 * 3600, show_spinner=False)
def load_cot(dataset, code, long_f, short_f, weeks=156):
    r = requests.get(
        f"https://publicreporting.cftc.gov/resource/{dataset}.json",
        params={
            "$where": f"cftc_contract_market_code='{code}'",
            "$order": "report_date_as_yyyy_mm_dd DESC",
            "$limit": weeks,
            "$select": f"report_date_as_yyyy_mm_dd,open_interest_all,{long_f},{short_f}",
        },
        timeout=20,
    )
    r.raise_for_status()
    df = pd.DataFrame(r.json())
    if df.empty:
        return df
    df = df.rename(columns={"report_date_as_yyyy_mm_dd": "date",
                            long_f: "long", short_f: "short",
                            "open_interest_all": "oi"})
    df["date"] = pd.to_datetime(df["date"])
    for c in ["long", "short", "oi"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna().sort_values("date").set_index("date")
    df["net"] = df["long"] - df["short"]
    return df

def render_cot_panel():
    st.subheader("COT POSITIONING (SPECULATORS)")
    rows, data = [], {}
    for name, (ds, code, lf, sf) in COT_MARKETS.items():
        try:
            df = load_cot(ds, code, lf, sf)
        except Exception:
            df = pd.DataFrame()
        if len(df) < 2:
            rows.append({"Market": name, "Report date": "n/a"})
            continue
        data[name] = df
        last, prev = df.iloc[-1], df.iloc[-2]
        year = df["net"].iloc[-52:]
        rng = year.max() - year.min()
        idx = (last["net"] - year.min()) / rng * 100 if rng else 50
        rows.append({
            "Market": name,
            "Report date": df.index[-1].date(),
            "Long": last["long"],
            "Short": last["short"],
            "Net": last["net"],
            "Net chg w/w": last["net"] - prev["net"],
            "Net % of OI": last["net"] / last["oi"] * 100,
            "52w index": idx,
        })
    table = pd.DataFrame(rows).set_index("Market")
    num = [c for c in ["Long", "Short", "Net", "Net chg w/w"] if c in table]
    st.dataframe(
        table.style
        .format({**{c: "{:,.0f}" for c in num},
                 "Net % of OI": "{:.1f}%", "52w index": "{:.0f}"}, na_rep="n/a")
        .background_gradient(cmap="RdYlGn", subset=["Net chg w/w"], axis=None),
        use_container_width=True,
    )
    st.caption("52w index: 0 = most bearish net position of the past year, 100 = most bullish.")

    if not data:
        st.warning("No COT data returned.")
        return
    pick = st.selectbox("Chart", list(data.keys()), key="cot_pick")
    df = data[pick]
    fig = go.Figure()
    fig.add_trace(go.Bar(x=df.index, y=df["net"], name="Net",
                         marker_color=["#22c55e" if v >= 0 else "#ef4444" for v in df["net"]]))
    fig.update_layout(template="plotly_dark", height=380,
                      title=f"{pick}: net speculative position (contracts)",
                      yaxis_title="Contracts")
    st.plotly_chart(fig, use_container_width=True)
    st.caption("Source: CFTC Commitments of Traders. Positions are as of Tuesday and published the following Friday.")

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

@st.cache_data(ttl=10, show_spinner=False)
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
    from html import escape

    st.subheader("Macro Overview")

    all_symbols = tuple(
        s
        for group in MACRO_GROUPS.values()
        for s in group.values()
    )

    quotes = get_macro_quotes(all_symbols)

    for group, items in MACRO_GROUPS.items():
        st.markdown(f"### {group}")
        cols = st.columns(len(items))

        for col, (name, sym) in zip(cols, items.items()):
            price, chg = quotes.get(sym, (None, None))

            price = pd.to_numeric(price, errors="coerce")
            chg = pd.to_numeric(chg, errors="coerce")

            if pd.isna(price):
                col.metric(name, "n/a")
                continue

            if pd.isna(chg):
                colour = "#9ca3af"
                change_text = "Change unavailable"
            elif chg > 0:
                colour = "#22c55e"
                change_text = f"+{chg:,.2f}%"
            elif chg < 0:
                colour = "#ef4444"
                change_text = f"{chg:,.2f}%"
            else:
                colour = "#9ca3af"
                change_text = "0.00%"

            safe_name = escape(str(name))

            col.html(
                f"""
                <div style="
                    border: 1px solid rgba(128,128,128,0.25);
                    border-radius: 10px;
                    padding: 10px 12px;
                    margin-bottom: 12px;
                    box-sizing: border-box;
                    width: 100%;
                    overflow: hidden;
                ">
                    <div style="
                        font-size: 13px;
                        margin-bottom: 6px;
                        white-space: nowrap;
                        overflow: hidden;
                        text-overflow: ellipsis;
                    ">{safe_name}</div>

                    <div style="
                        color: {colour};
                        font-size: clamp(16px, 1.7vw, 26px);
                        font-weight: 700;
                        line-height: 1.2;
                        white-space: nowrap;
                    ">{price:,.2f}</div>

                    <div style="
                        color: {colour};
                        font-size: clamp(12px, 1.1vw, 15px);
                        margin-top: 6px;
                        white-space: nowrap;
                    ">{change_text}</div>
                </div>
                """
            )

    checked_at = pd.Timestamp.now(
        tz="Europe/London"
    ).strftime("%H:%M:%S")

    st.caption(
        f"Last checked: {checked_at} London time · "
        "Panel refreshes every 10 seconds. "
        "Source data may be cached or delayed."
    )

    with st.expander("Cross-asset correlation"):
        render_correlation_panel()

    st.markdown("### Chart")

    names = {
        name: symbol
        for group in MACRO_GROUPS.values()
        for name, symbol in group.items()
    }

    choice = st.selectbox(
        "Pick an asset",
        list(names),
        key="macro_chart_asset",
    )

    hist = get_history(names[choice], "1y", "1d")

    if hist is None or hist.empty or "Close" not in hist.columns:
        st.info("Chart data is currently unavailable.")
        return

    fig = go.Figure(
        go.Scatter(
            x=hist.index,
            y=hist["Close"],
            line=dict(color="#00ff66"),
        )
    )

    fig.update_layout(
        template="plotly_dark",
        height=400,
        title=choice,
    )

    st.plotly_chart(
        fig,
        use_container_width=True,
    )

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

    for article in articles:
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
# ---------- Morning briefing ----------
def show_morning_briefing():
    from html import escape

    st.subheader("Morning Briefing")

    now = pd.Timestamp.now(tz="Europe/London")
    today = now.date()
    end_date = (now + pd.Timedelta(days=7)).date()

    st.caption(
        now.strftime("%A %d %B %Y · %H:%M:%S %Z")
        + " · On-demand market briefing"
    )

    st.caption(
        "A snapshot of available data—not an explanation of why "
        "markets moved. Figures can refer to different trading "
        "sessions and may be cached or delayed."
    )

    if st.button("Refresh briefing", key="refresh_briefing"):
        get_macro_quotes.clear()
        get_quote.clear()
        fetch_market_headlines.clear()
        fetch_earnings_calendar.clear()

    def safe_number(value):
        value = pd.to_numeric(value, errors="coerce")
        return None if pd.isna(value) else float(value)

    def draw_card(column, label, price, change):
        price = safe_number(price)
        change = safe_number(change)

        if change is None or change == 0:
            colour = "#9ca3af"
        elif change > 0:
            colour = "#22c55e"
        else:
            colour = "#ef4444"

        price_text = "n/a" if price is None else f"{price:,.2f}"
        change_text = (
            "Change unavailable"
            if change is None
            else f"{change:+.2f}%"
        )

        column.html(
            f"""
            <div style="
                border:1px solid rgba(128,128,128,0.3);
                border-radius:10px;
                padding:14px;
                margin-bottom:12px;
            ">
                <div style="font-size:14px;margin-bottom:8px;">
                    {escape(label)}
                </div>
                <div style="
                    color:{colour};
                    font-size:28px;
                    font-weight:700;
                ">{price_text}</div>
                <div style="color:{colour};margin-top:6px;">
                    {change_text}
                </div>
            </div>
            """
        )

    # Market snapshot
    st.markdown("### Market snapshot")

    focus_assets = {
        "Gold futures": "GC=F",
        "Nasdaq-100 futures": "NQ=F",
        "S&P 500": "^GSPC",
        "FTSE 100": "^FTSE",
        "GBP/USD": "GBPUSD=X",
        "EUR/USD": "EURUSD=X",
        "Brent futures": "BZ=F",
        "VIX": "^VIX",
    }

    quotes = {}
    snapshot_ok = True

    try:
        quotes = get_macro_quotes(tuple(focus_assets.values()))
        if not isinstance(quotes, dict):
            quotes = {}
            snapshot_ok = False
    except Exception:
        snapshot_ok = False
        st.warning("The market snapshot could not be loaded.")

    asset_items = list(focus_assets.items())

    for start in range(0, len(asset_items), 4):
        columns = st.columns(4)

        for column, (name, symbol) in zip(
            columns, asset_items[start:start + 4]
        ):
            price, change = quotes.get(symbol, (None, None))
            draw_card(column, name, price, change)

    st.caption(
        "Snapshot source: Yahoo Finance via your existing macro "
        "helper. Changes compare the last two available daily "
        "closes. Futures are not spot or broker CFD prices. "
        "VIX is an index level, not a percentage price."
    )

    # Factual summary: no inferred causes or trading signals
    available_moves = []

    for name, symbol in focus_assets.items():
        price, change = quotes.get(symbol, (None, None))
        price = safe_number(price)
        change = safe_number(change)

        if price is not None and change is not None:
            available_moves.append((name, change))

    st.markdown("### At a glance")

    if available_moves:
        higher = sum(change > 0 for _, change in available_moves)
        lower = sum(change < 0 for _, change in available_moves)
        flat = sum(change == 0 for _, change in available_moves)

        st.write(
            f"Of {len(available_moves)} instruments with available "
            f"change data: {higher} higher, {lower} lower and "
            f"{flat} unchanged."
        )

        largest_name, largest_change = max(
            available_moves,
            key=lambda item: abs(item[1]),
        )

        st.write(
            f"Largest absolute percentage move in this selected "
            f"snapshot: {largest_name} ({largest_change:+.2f}%)."
        )

        st.caption(
            "This compares a small, mixed set of instruments—not "
            "overall market breadth or comparable investment returns."
        )
    else:
        st.info("No market-change summary is available.")

    # Watchlist
    st.markdown("### Your watchlist")

    default_watchlist = (
        "GC=F\nNQ=F\nEURUSD=X\nGBPUSD=X\nBTC-USD"
    )

    watchlist_text = st.session_state.get(
        "watchlist_tickers", default_watchlist
    )

    symbols = list(
        dict.fromkeys(watchlist_text.upper().split())
    )

    watchlist_rows = []
    watchlist_unavailable = 0

    for symbol in symbols:
        try:
            price, change = get_quote(symbol)
        except Exception:
            price, change = None, None

        price = safe_number(price)
        change = safe_number(change)

        if price is None:
            watchlist_unavailable += 1

        watchlist_rows.append({
            "Ticker": symbol,
            "Price": price,
            "Change %": change,
        })

    if watchlist_rows:
        st.dataframe(
            pd.DataFrame(watchlist_rows),
            hide_index=True,
            use_container_width=True,
        )

        if watchlist_unavailable:
            st.caption(
                f"{watchlist_unavailable} watchlist quote(s) "
                "currently unavailable."
            )
    else:
        st.info("Add tickers to your sidebar watchlist.")

    st.caption(
        "Plain US stock symbols use Finnhub; Yahoo-style index, "
        "forex, futures, crypto and exchange symbols use Yahoo "
        "Finance. A missing value does not mean zero."
    )

    # Headlines
    st.markdown("### Latest market headlines")

    try:
        articles, news_error = fetch_market_headlines()
    except Exception:
        articles, news_error = [], "Market news is unavailable."

    if news_error:
        st.warning(news_error)
    elif not articles:
        st.info("No headlines were returned.")
    else:
        for article in articles:
            st.markdown("#### " + article["headline"])

            published = pd.to_datetime(
                article.get("datetime"),
                unit="s",
                utc=True,
                errors="coerce",
            )

            published_text = "Publication time unavailable"

            if pd.notna(published):
                published_text = published.tz_convert(
                    "Europe/London"
                ).strftime("%d %b %Y, %H:%M %Z")

            source = article.get("source") or "Unknown publisher"
            st.caption(f"{source} | {published_text}")

            url = article.get("url") or ""

            if isinstance(url, str) and url.startswith(
                ("https://", "http://")
            ):
                st.link_button("Read original article", url)

    # Earnings
    st.markdown("### Earnings: today and the next seven days")

    try:
        events, earnings_error = fetch_earnings_calendar(
            today.isoformat(),
            end_date.isoformat(),
            "",
        )
    except Exception:
        events, earnings_error = [], "Earnings data is unavailable."

    if earnings_error:
        st.warning(earnings_error)
    elif not events:
        st.info(
            "No earnings events were returned. This can reflect "
            "coverage or access limits, not necessarily no releases."
        )
    else:
        earnings = pd.DataFrame(events)

        required = [
            "date", "symbol", "hour",
            "epsEstimate", "epsActual",
        ]

        for column in required:
            if column not in earnings.columns:
                earnings[column] = None

        earnings["date"] = pd.to_datetime(
            earnings["date"], errors="coerce"
        )

        earnings = earnings[
            earnings["date"].notna()
            & (earnings["date"].dt.date >= today)
            & (earnings["date"].dt.date <= end_date)
        ].copy()

        earnings = earnings.sort_values(
            ["date", "symbol"], na_position="last"
        )

        if earnings.empty:
            st.info("No dated events matched the requested range.")
        else:
            today_count = int(
                (earnings["date"].dt.date == today).sum()
            )

            st.caption(
                f"{today_count} release(s) dated today; "
                f"{len(earnings)} in the displayed date range."
            )

            timing_labels = {
                "bmo": "Before market open",
                "amc": "After market close",
                "dmh": "During market hours",
            }

            def eps_text(value):
                value = safe_number(value)
                return "—" if value is None else f"{value:,.2f}"

            display = pd.DataFrame({
                "Date": earnings["date"].dt.strftime("%d %b %Y"),
                "Ticker": earnings["symbol"],
                "Reporting session": earnings["hour"].map(
                    timing_labels
                ).fillna("Not specified"),
                "Estimated EPS": earnings["epsEstimate"].map(
                    eps_text
                ),
                "Actual EPS": earnings["epsActual"].map(
                    eps_text
                ),
            })

            st.dataframe(
                display,
                hide_index=True,
                use_container_width=True,
            )

            st.caption(
                "Dates and figures are supplied by Finnhub. "
                "Reporting sessions refer to the relevant market, "
                "not London clock times. — means unavailable."
            )

    # Data-status information
    with st.expander("Data status and refresh details"):
        st.write(
            "Market snapshot: "
            + (
                f"{len(available_moves)} instruments with usable "
                "price-and-change data."
                if snapshot_ok
                else "Request unavailable."
            )
        )

        st.write(
            "Headlines: "
            + (
                "Unavailable."
                if news_error
                else f"{len(articles)} returned."
            )
        )

        st.write(
            "Earnings: "
            + (
                "Unavailable."
                if earnings_error
                else f"{len(events)} raw event(s) returned."
            )
        )

        st.write(
            "This briefing loads when opened or rerun. "
            "It does not refresh automatically on a timer."
        )

        st.write(
            "Existing caches: macro quotes up to 5 minutes, "
            "watchlist quotes up to 30 seconds, headlines up to "
            "60 seconds and earnings up to 15 minutes. "
            "Refresh briefing clears those caches, but cannot "
            "remove delays in the underlying sources."
        )

        st.write(
            "Sidebar watchlist changes are picked up when this "
            "briefing next reruns. It does not include an economic "
            "calendar, price forecasts or trading recommendations."
        )

# ---------- Session clock ----------
@st.fragment(run_every="10s")
def show_session_clock():
    from zoneinfo import ZoneInfo

    london_tz = ZoneInfo("Europe/London")
    now_london = pd.Timestamp.now(tz=london_tz)

    st.subheader("Session Clock")
    st.caption(
        now_london.strftime("%A %d %B %Y · %H:%M:%S %Z")
        + " · Updates every 10 seconds while this page is active"
    )

    sessions = [
        {
            "name": "London killzone",
            "start_hour": 7,
            "end_hour": 10,
        },
        {
            "name": "New York killzone",
            "start_hour": 13,
            "end_hour": 16,
        },
    ]

    active_sessions = []
    upcoming_sessions = []

    for session in sessions:
        start = now_london.replace(
            hour=session["start_hour"],
            minute=0,
            second=0,
            microsecond=0,
        )

        end = now_london.replace(
            hour=session["end_hour"],
            minute=0,
            second=0,
            microsecond=0,
        )

        if start <= now_london < end:
            active_sessions.append(
                {
                    "name": session["name"],
                    "ends_at": end,
                }
            )
        elif now_london < start:
            upcoming_sessions.append(
                {
                    "name": session["name"],
                    "starts_at": start,
                }
            )
        else:
            next_start = start + pd.Timedelta(days=1)

            upcoming_sessions.append(
                {
                    "name": session["name"],
                    "starts_at": next_start,
                }
            )

    if active_sessions:
        for session in active_sessions:
            minutes_left = int(
                (session["ends_at"] - now_london)
                .total_seconds()
                // 60
            )

            st.success(
                f"{session['name']} is active. "
                f"Ends in {minutes_left} minute(s)."
            )
    else:
        st.info("No selected killzone is currently active.")

    for session in upcoming_sessions:
        minutes_until = int(
            (session["starts_at"] - now_london)
            .total_seconds()
            // 60
        )

        hours, minutes = divmod(minutes_until, 60)

        st.write(
            f"Next {session['name']}: "
            f"{session['starts_at'].strftime('%H:%M %Z')} "
            f"(in {hours}h {minutes}m)"
        )

    broker_time = now_london + pd.Timedelta(hours=3)

    st.caption(
        "Broker server time: "
        + broker_time.strftime("%H:%M:%S")
        + " · Your broker server is 3 hours ahead of London. "
        "Use London time for session logic."
    )
    
# ---------- Toolbar and command bar ----------
if "terminal_command" not in st.session_state:
    st.session_state["terminal_command"] = "AAPL GP"

if "terminal_last_ticker" not in st.session_state:
    st.session_state["terminal_last_ticker"] = "AAPL"

RESERVED_COMMANDS = {
    "GP", "NEWS", "FA", "EARNINGS", "UK", "MACRO",
    "BRIEF", "SESSIONS"
}


def open_terminal_panel(panel):
    parts = (
        st.session_state["terminal_command"]
        .strip()
        .upper()
        .split()
    )

    if parts and parts[0] not in RESERVED_COMMANDS:
        st.session_state["terminal_last_ticker"] = parts[0]

    selected_ticker = st.session_state["terminal_last_ticker"]

    if panel in {"UK", "MACRO", "EARNINGS", "BRIEF", "SESSIONS"}:
        st.session_state["terminal_command"] = panel
    else:
        st.session_state["terminal_command"] = (
            f"{selected_ticker} {panel}"
        )


@st.fragment(run_every="1s")
def show_top_clock():
    from zoneinfo import ZoneInfo

    now_london = pd.Timestamp.now(
        tz=ZoneInfo("Europe/London")
    )

    st.markdown(
        f"""
        <div style="
            font-family: monospace;
            color: #ffb000;
            font-size: 18px;
            margin-bottom: 6px;
        ">
            {now_london.strftime("%H:%M:%S %Z")}
        </div>
        """,
        unsafe_allow_html=True,
    )
st.title("Tom's TERMINAL")
show_top_clock()

primary_items = [
    ("Briefing", "BRIEF"),
    ("Macro", "MACRO"),
    ("UK", "UK"),
    ("Chart", "GP"),
    ("Calendar", "CAL"),
]

secondary_items = [
    ("Sessions", "SESSIONS"),
    ("Company News", "NEWS"),
    ("Earnings", "EARNINGS"),
    ("Financials", "FA"),
    ("Curve", "CURVE"),
    ("COT", "COT"),
]

def draw_toolbar(items, row_number):
    columns = st.columns(len(items))

    for column, (label, panel) in zip(
        columns, items
    ):
        with column:
            st.button(
                label,
                key=f"terminal_nav_{panel}_{row_number}",
                on_click=open_terminal_panel,
                args=(panel,),
                use_container_width=True,
            )

draw_toolbar(primary_items, 1)
draw_toolbar(secondary_items, 2)

command_text = st.text_input(
    "Command (e.g. AAPL GP, TSLA NEWS, MSFT FA, BRIEF)",
    key="terminal_command",
)

cmd = command_text.strip().upper().split()

ticker = cmd[0] if cmd else "AAPL"
function = cmd[1] if len(cmd) > 1 else "GP"

if ticker not in RESERVED_COMMANDS:
    st.session_state["terminal_last_ticker"] = ticker

st.divider()

# ---------- Sidebar ----------
WATCHLIST_NAMES = {
    "^GSPC": "S&P 500",
    "^NDX": "Nasdaq",
    "GC=F": "Gold",
    "EURUSD=X": "EUR/USD",
    "GBPUSD=X": "GBP/USD",
    "^TNX": "US 10Y Yield",
    "^VIX": "VIX",
    "DX-Y.NYB": "US Dollar Index",
    "CL=F": "WTI Crude",
    "BZ=F": "Brent Crude",
    "SI=F": "Silver",
    "HG=F": "Copper",
    "NQ=F": "Nasdaq Futures",
    "ES=F": "S&P Futures",
    "BTC-USD": "Bitcoin",
}
CORR_SYMBOLS = ["^GSPC", "^IXIC", "GC=F", "EURUSD=X", "GBPUSD=X",
                "^TNX", "^VIX", "DX-Y.NYB", "CL=F"]


@st.cache_data(ttl=1800)
def load_corr_returns(symbols, period):
    px = yf.download(list(symbols), period=period, interval="1d",
                     progress=False, auto_adjust=True)["Close"]
    px = px.dropna(how="all").ffill()
    return px.pct_change().dropna(how="all")


def render_correlation_panel():
    st.subheader("CROSS-ASSET CORRELATION")
    period = st.radio("Window", ["3mo", "6mo", "1y"], index=1,
                      horizontal=True, key="corr_window")
    try:
        rets = load_corr_returns(tuple(CORR_SYMBOLS), period)
        corr = rets.corr()
    except Exception as e:
        st.caption(f"Correlation data unavailable: {type(e).__name__}")
        return

    labels = [WATCHLIST_NAMES.get(c, c) for c in corr.columns]
    fig = go.Figure(go.Heatmap(
        z=corr.values, x=labels, y=labels,
        zmin=-1, zmax=1, colorscale="RdYlGn",
        text=corr.round(2).values, texttemplate="%{text}",
    ))
    fig.update_layout(
        height=550, paper_bgcolor="#000", plot_bgcolor="#000",
        font=dict(color="#ffb000", family="monospace"),
        yaxis=dict(autorange="reversed"),
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption(
        "Correlation of daily percentage changes. +1 moves together, "
        "-1 moves opposite, 0 unrelated. Yields and VIX are levels, "
        "so their % changes are noisy. Different market hours blur "
        "the figures slightly."
    )
@st.fragment(run_every="10s")
def show_watchlist():
    st.header("Watchlist")

    watchlist = st.text_area(
        "Tickers",
        value=(
            "^GSPC\n"
            "^NDX\n"
            "GC=F\n"
            "EURUSD=X\n"
            "GBPUSD=X\n"
            "^TNX"
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
                    label=WATCHLIST_NAMES.get(t, t),
                    value=f"{price:,.2f}",
                    delta=change_text,
                    delta_color="normal",
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
        "Prices may be cached, delayed or unchanged."
    )


with st.sidebar:
    show_watchlist()

period = st.sidebar.selectbox(
    "Period",
    ["1mo", "3mo", "6mo", "1y", "5y"],
    index=3,
)

interval = st.sidebar.selectbox(
    "Interval",
    ["1d", "1wk", "1h"],
    index=0,
)


from zoneinfo import ZoneInfo
from datetime import datetime, date, time as dtime

CAL_RELEASES = {
    10: ("US CPI", "High"),
    50: ("US Non-Farm Payrolls / Unemployment", "High"),
    180: ("US Initial Jobless Claims", "Medium"),
    46: ("US PPI", "Medium"),
    53: ("US GDP", "High"),
    54: ("US PCE Inflation", "High"),
    9: ("US Retail Sales", "Medium"),
}

CAL_MANUAL = [
    ("2026-12-09", "14:00", "America/New_York", "FOMC rate decision", "High"),
    ("2026-12-17", "12:00", "Europe/London", "BoE rate decision", "High"),
]

@st.cache_data(ttl=6 * 3600, show_spinner=False)
def get_release_dates(release_id):
    r = requests.get(
        "https://api.stlouisfed.org/fred/release/dates",
        params={
            "release_id": release_id,
            "api_key": st.secrets["FRED_API_KEY"],
            "file_type": "json",
            "realtime_start": date.today().strftime("%Y-%m-%d"),
            "realtime_end": "9999-12-31",
            "include_release_dates_with_no_data": "true",
            "sort_order": "desc",
            "limit": 30,
        },
        timeout=15,
    )
    r.raise_for_status()
    return [d["date"] for d in r.json().get("release_dates", [])]

def build_calendar(days_ahead):
    london = ZoneInfo("Europe/London")
    now = datetime.now(london)
    end = now + pd.Timedelta(days=days_ahead)
    rows, missing = [], []

    for rid, (name, impact) in CAL_RELEASES.items():
        try:
            dates = get_release_dates(rid)
        except Exception:
            missing.append(name)
            continue
        for d in dates:
            dt = datetime.combine(
                date.fromisoformat(d), dtime(8, 30), tzinfo=ZoneInfo("America/New_York")
            ).astimezone(london)
            rows.append((dt, name, impact))

    for d, t, tz, name, impact in CAL_MANUAL:
        hh, mm = map(int, t.split(":"))
        dt = datetime.combine(date.fromisoformat(d), dtime(hh, mm), tzinfo=ZoneInfo(tz)).astimezone(london)
        rows.append((dt, name, impact))

    rows = sorted([r for r in rows if now - pd.Timedelta(hours=2) <= r[0] <= end])
    return rows, missing

def render_calendar_panel():
    st.subheader("ECONOMIC CALENDAR (LONDON TIME)")
    days = st.radio("Window", [7, 14, 30], index=1, horizontal=True,
                    format_func=lambda x: f"Next {x} days", key="cal_days")
    rows, missing = build_calendar(days)

    if not rows:
        st.info("No events found in this window.")
    else:
        table = pd.DataFrame(
            [{"Day": dt.strftime("%a %d %b"), "Time": dt.strftime("%H:%M"),
              "Event": name, "Impact": impact} for dt, name, impact in rows]
        )

        def colour(v):
            return {"High": "color: #ef4444; font-weight: 600",
                    "Medium": "color: #f59e0b"}.get(v, "")

        st.dataframe(table.style.map(colour, subset=["Impact"]),
                     use_container_width=True, hide_index=True)

    if missing:
        st.caption("Could not load: " + ", ".join(missing))
    st.caption("US data dates from FRED, assumed 08:30 ET. Central bank dates entered manually. No forecasts shown.")

def show_sidebar_calendar():
    with st.sidebar:
        with st.expander("Upcoming releases", expanded=True):
            try:
                rows, missing = build_calendar(7)
            except Exception:
                st.caption("Calendar unavailable")
                return

            keys = ("CPI", "PPI", "JOBLESS", "CLAIMS", "PAYROLL", "NFP")
            picked = [
                r for r in rows
                if r[2] == "High" or any(k in r[1].upper() for k in keys)
            ][:8]

            if not picked:
                st.caption("No major releases in the next 7 days")
            else:
                for dt, name, impact in picked:
                    st.caption(f"{dt.strftime('%a %d %b %H:%M')} · {name}")

            st.caption("London time")


show_sidebar_calendar()

import io

BOE_HEADERS = {"User-Agent": "My Terminal thomaslower2@gmail.com"}

@st.cache_data(ttl=3600, show_spinner=False)
def get_boe_series(code, days=45):
    start = (pd.Timestamp.today() - pd.Timedelta(days=days)).strftime("%d/%b/%Y")
    url = (
        "https://www.bankofengland.co.uk/boeapps/iadb/fromshowcolumns.asp"
        f"?csv.x=yes&Datefrom={start}&Dateto=now&SeriesCodes={code}"
        "&CSVF=TN&UsingCodes=Y&VPD=Y&VFD=N"
    )
    r = requests.get(url, headers=BOE_HEADERS, timeout=20)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    s = pd.Series(
        pd.to_numeric(df[code], errors="coerce").values,
        index=pd.to_datetime(df["DATE"], format="%d %b %Y"),
    ).dropna()
    if s.empty:
        raise ValueError("empty BoE series")
    return s

@st.cache_data(ttl=3600, show_spinner=False)
def get_fred_series(series_id, days=45):
    start = (pd.Timestamp.today() - pd.Timedelta(days=days)).strftime("%Y-%m-%d")
    r = requests.get(
        "https://api.stlouisfed.org/fred/series/observations",
        params={"series_id": series_id, "api_key": st.secrets["FRED_API_KEY"],
                "file_type": "json", "observation_start": start},
        timeout=15,
    )
    r.raise_for_status()
    df = pd.DataFrame(r.json()["observations"])
    s = pd.Series(pd.to_numeric(df["value"], errors="coerce").values,
                  index=pd.to_datetime(df["date"])).dropna()
    return s

def _spread_card(col, name, value_text, change_text, diff, as_of):
    from html import escape
    colour = "#22c55e" if diff > 0 else "#ef4444" if diff < 0 else "#9ca3af"
    col.html(
        f"""
        <div style="border: 1px solid rgba(128,128,128,0.25); border-radius: 10px;
            padding: 10px 12px; margin-bottom: 12px; box-sizing: border-box;
            width: 100%; overflow: hidden;">
            <div style="font-size: 13px; margin-bottom: 6px; white-space: nowrap;
                overflow: hidden; text-overflow: ellipsis;">{escape(name)}</div>
            <div style="font-size: 22px; font-weight: 600; color: {colour};">{value_text}</div>
            <div style="font-size: 13px; color: {colour};">{change_text}</div>
            <div style="font-size: 11px; opacity: 0.6; margin-top: 4px;">As of {as_of}</div>
        </div>
        """
    )

def show_uk_us_spread():
    st.markdown("### UK-US 10Y Spread")
    cols = st.columns(4)
    try:
        uk = get_boe_series("IUDMNZC")
        us = get_fred_series("DGS10")
        both = pd.concat([uk.rename("uk"), us.rename("us")], axis=1).dropna()
        spread = both["uk"] - both["us"]
        if len(both) < 2:
            raise ValueError("not enough overlapping dates")
    except Exception as e:
        cols[0].metric("UK-US 10Y Spread", "n/a")
        st.caption(f"UK data unavailable: {type(e).__name__}")
        return

    last_date = both.index[-1].date()
    for col, name, ser in [(cols[0], "UK 10Y Gilt", both["uk"]),
                           (cols[1], "US 10Y Treasury", both["us"])]:
        d = ser.iloc[-1] - ser.iloc[-2]
        _spread_card(col, name, f"{ser.iloc[-1]:.2f}%", f"{d * 100:+.0f} bp", d, last_date)

    d = spread.iloc[-1] - spread.iloc[-2]
    _spread_card(cols[2], "UK-US 10Y Spread", f"{spread.iloc[-1] * 100:+.0f} bp",
                 f"{d * 100:+.0f} bp d/d", d, last_date)
    st.caption("UK: BoE nominal 10Y spot yield. US: FRED DGS10. Dates matched; the UK series usually lags by about a day.")

def show_sidebar_uk_rates():
    with st.sidebar:
        with st.expander("UK rates", expanded=True):
            try:
                uk = get_boe_series("IUDMNZC")
                us = get_fred_series("DGS10")
                both = pd.concat(
                    [uk.rename("uk"), us.rename("us")], axis=1
                ).dropna()
                if len(both) < 2:
                    raise ValueError("not enough overlapping dates")
                spread = both["uk"] - both["us"]
            except Exception as e:
                st.caption(f"UK data unavailable: {type(e).__name__}")
                return

            d_uk = both["uk"].iloc[-1] - both["uk"].iloc[-2]
            d_sp = spread.iloc[-1] - spread.iloc[-2]

            st.metric(
                "UK 10Y Gilt",
                f"{both['uk'].iloc[-1]:.2f}%",
                f"{d_uk * 100:+.0f} bp",
            )
            st.metric(
                "UK-US 10Y Spread",
                f"{spread.iloc[-1] * 100:+.0f} bp",
                f"{d_sp * 100:+.0f} bp d/d",
            )
            st.caption(
                f"As of {both.index[-1].date()}. BoE nominal spot vs "
                "FRED par yield, so the level is approximate. "
                "The UK series usually lags by about a day."
            )


show_sidebar_uk_rates()
    
# ---------- Panels ----------
def show_selected_panel():
    if ticker == "SESSIONS" or function == "SESSIONS":
        show_session_clock()

    elif ticker == "CAL" or function == "CAL":
        render_calendar_panel()
    
    elif ticker == "BRIEF" or function == "BRIEF":
        show_morning_briefing()

    elif ticker == "FA" or function == "FA":
        show_basic_financials()

    elif ticker == "EARNINGS" or function == "EARNINGS":
        show_earnings_calendar()

    elif ticker == "UK" or function == "UK":
        show_uk()

    elif ticker == "MACRO" or function == "MACRO":
        show_macro()
        show_econ_releases()
        show_real_yields_dollar()

    elif ticker == "CURVE" or function == "CURVE":
        if st.button("Refresh curve data", key="curve_refresh"):
            st.cache_data.clear()
            st.rerun()

        market = st.radio(
            "Market", ["US Treasuries", "UK Gilts"],
            horizontal=True, key="curve_market",
        )
        if market == "UK Gilts":
            render_gilt_panel()
            show_uk_us_spread()
        else:
            render_curve_panel()
            
    elif ticker == "COT" or function == "COT":
        render_cot_panel()

    elif function == "GP":
        df = get_history(ticker, period, interval)

        if df is None or df.empty:
            st.warning("No chart data was returned for this ticker.")
            return

        df = add_indicators(df.copy())

        fig = make_subplots(
            rows=2,
            cols=1,
            shared_xaxes=True,
            row_heights=[0.75, 0.25],
            vertical_spacing=0.03,
        )

        fig.add_trace(
            go.Candlestick(
                x=df.index,
                open=df["Open"],
                high=df["High"],
                low=df["Low"],
                close=df["Close"],
                name=ticker,
            ),
            row=1,
            col=1,
        )

        fig.add_trace(
            go.Scatter(
                x=df.index,
                y=df["SMA20"],
                name="SMA20",
                line=dict(color="cyan", width=1),
            ),
            row=1,
            col=1,
        )

        fig.add_trace(
            go.Scatter(
                x=df.index,
                y=df["SMA50"],
                name="SMA50",
                line=dict(color="magenta", width=1),
            ),
            row=1,
            col=1,
        )

        fig.add_trace(
            go.Scatter(
                x=df.index,
                y=df["RSI"],
                name="RSI",
                line=dict(color="orange"),
            ),
            row=2,
            col=1,
        )

        fig.add_hline(
            y=70,
            line_dash="dot",
            line_color="red",
            row=2,
            col=1,
        )

        fig.add_hline(
            y=30,
            line_dash="dot",
            line_color="green",
            row=2,
            col=1,
        )

        fig.update_layout(
            template="plotly_dark",
            height=700,
            xaxis_rangeslider_visible=False,
            title=f"{ticker} Price Chart",
        )

        st.plotly_chart(fig, use_container_width=True)

    elif function == "NEWS":
        show_live_news(ticker)

    else:
        st.warning(
            "Unknown function. Try GP, NEWS, FA, EARNINGS, "
            "UK, MACRO, BRIEF or SESSIONS."
        )


is_briefing = ticker == "BRIEF" or function == "BRIEF"

if is_briefing:
    show_selected_panel()
else:
    main_area, news_area = st.columns([3, 1], gap="large")

    with main_area:
        show_selected_panel()

    with news_area:
        show_market_headlines()
st.divider()
render_curve_panel()
