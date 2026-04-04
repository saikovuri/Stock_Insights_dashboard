import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
from stock_data import get_stock_data, get_key_metrics, format_large_number
from news_sentiment import fetch_news, aggregate_sentiment
from ai_summary import get_ai_summary
from portfolio import add_holding, remove_holding, get_holdings, get_portfolio_summary
from alerts import check_alerts

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(page_title="Stock Insights Dashboard", page_icon="📈", layout="wide")
st.title("📈 Stock Insights Dashboard")

# ── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Settings")
    ticker = st.text_input("Stock Ticker", value="AAPL", max_chars=10).upper().strip()
    period = st.selectbox("Time Period", ["1mo", "3mo", "6mo", "1y", "2y", "5y"], index=2)
    chart_type = st.selectbox("Chart Type", ["Candlestick", "Line"])
    st.divider()

    # Portfolio management
    st.header("Portfolio")
    with st.expander("Add Holding"):
        p_ticker = st.text_input("Ticker", key="p_ticker").upper().strip()
        p_shares = st.number_input("Shares", min_value=0.01, value=1.0, step=1.0, key="p_shares")
        p_price = st.number_input("Buy Price ($)", min_value=0.01, value=100.0, step=0.5, key="p_price")
        if st.button("Add to Portfolio"):
            if p_ticker:
                add_holding(p_ticker, p_shares, p_price)
                st.success(f"Added {p_shares} shares of {p_ticker} @ ${p_price}")

    with st.expander("Sell Holding"):
        s_ticker = st.text_input("Ticker", key="s_ticker").upper().strip()
        s_shares = st.number_input("Shares", min_value=0.01, value=1.0, step=1.0, key="s_shares")
        s_price = st.number_input("Sell Price ($)", min_value=0.01, value=100.0, step=0.5, key="s_price")
        if st.button("Sell"):
            if s_ticker:
                result = remove_holding(s_ticker, s_shares, s_price)
                if result:
                    st.success(f"Sold {result['shares']} shares of {s_ticker} @ ${s_price}")
                else:
                    st.error(f"{s_ticker} not found in portfolio")

# ── Main content ─────────────────────────────────────────────────────────────
if not ticker:
    st.info("Enter a stock ticker in the sidebar to get started.")
    st.stop()

# Fetch data
with st.spinner(f"Loading data for {ticker}..."):
    try:
        metrics = get_key_metrics(ticker)
        hist = get_stock_data(ticker, period=period)
        news = fetch_news(ticker, company_name=metrics.get("name", ""))
        sentiment = aggregate_sentiment(news)
        triggered_alerts = check_alerts(metrics)
    except Exception as e:
        st.error(f"Error fetching data: {e}")
        st.stop()

# ── Alerts banner ────────────────────────────────────────────────────────────
if triggered_alerts:
    for alert in triggered_alerts:
        icon = {"high": "🔴", "warning": "🟠", "medium": "🟡", "info": "🔵"}.get(alert["severity"], "ℹ️")
        st.warning(f"{icon} **{alert['type']}**: {alert['message']}")

# ── Key Metrics Row ──────────────────────────────────────────────────────────
st.subheader(f"{metrics['name']} ({ticker})")
st.caption(f"{metrics['sector']} · {metrics['industry']}")

col1, col2, col3, col4, col5, col6 = st.columns(6)
col1.metric("Price", f"${metrics['price']:.2f}", f"{metrics['change_pct']:+.2f}%")
col2.metric("Market Cap", format_large_number(metrics["market_cap"]))
col3.metric("P/E Ratio", f"{metrics['pe_ratio']:.1f}" if metrics["pe_ratio"] else "N/A")
col4.metric("EPS", f"${metrics['eps']:.2f}" if metrics["eps"] else "N/A")
col5.metric("52W High", f"${metrics['52w_high']:.2f}")
col6.metric("52W Low", f"${metrics['52w_low']:.2f}")

col7, col8, col9, col10 = st.columns(4)
col7.metric("Volume", f"{metrics['volume']:,}")
col8.metric("Avg Volume", f"{metrics['avg_volume']:,}")
col9.metric("50D Avg", f"${metrics['50d_avg']:.2f}")
col10.metric("200D Avg", f"${metrics['200d_avg']:.2f}")

# ── Price Chart ──────────────────────────────────────────────────────────────
st.subheader("Price Chart")

if chart_type == "Candlestick":
    fig = go.Figure(
        data=[
            go.Candlestick(
                x=hist.index,
                open=hist["Open"],
                high=hist["High"],
                low=hist["Low"],
                close=hist["Close"],
                name="OHLC",
            )
        ]
    )
else:
    fig = go.Figure(data=[go.Scatter(x=hist.index, y=hist["Close"], mode="lines", name="Close")])

# Add moving averages
if len(hist) >= 20:
    fig.add_trace(go.Scatter(x=hist.index, y=hist["Close"].rolling(20).mean(), mode="lines", name="20-Day MA", line=dict(dash="dash", width=1)))
if len(hist) >= 50:
    fig.add_trace(go.Scatter(x=hist.index, y=hist["Close"].rolling(50).mean(), mode="lines", name="50-Day MA", line=dict(dash="dot", width=1)))

fig.update_layout(xaxis_rangeslider_visible=False, height=450, margin=dict(l=0, r=0, t=30, b=0))
st.plotly_chart(fig, width="stretch")

# Volume chart
vol_fig = px.bar(hist, x=hist.index, y="Volume", title="Volume")
vol_fig.update_layout(height=200, margin=dict(l=0, r=0, t=30, b=0))
st.plotly_chart(vol_fig, width="stretch")

# ── Two-column layout: News + AI Summary ─────────────────────────────────────
left_col, right_col = st.columns([1, 1])

# ── News & Sentiment ─────────────────────────────────────────────────────────
with left_col:
    st.subheader("📰 News & Sentiment")

    sent_col1, sent_col2, sent_col3, sent_col4 = st.columns(4)
    sent_col1.metric("Overall", sentiment["label"])
    sent_col2.metric("Positive", sentiment["positive"])
    sent_col3.metric("Negative", sentiment["negative"])
    sent_col4.metric("Neutral", sentiment["neutral"])

    for article in news[:8]:
        color = {"Positive": "🟢", "Negative": "🔴", "Neutral": "⚪"}.get(article["sentiment_label"], "⚪")
        with st.container():
            if article["url"]:
                st.markdown(f"{color} [{article['title']}]({article['url']})  \n*{article['source']}* · Sentiment: {article['sentiment']:.2f}")
            else:
                st.markdown(f"{color} {article['title']}  \n*{article['source']}*")

# ── AI Analysis ──────────────────────────────────────────────────────────────
with right_col:
    st.subheader("🤖 AI Analysis")
    if st.button("Generate AI Summary", type="primary"):
        with st.spinner("Analyzing..."):
            summary = get_ai_summary(metrics, sentiment, news)
        st.markdown(summary)
    else:
        st.info("Click **Generate AI Summary** to get an AI-powered analysis with recommendation.")

# ── Portfolio Section ────────────────────────────────────────────────────────
st.divider()
st.subheader("💼 Portfolio")

holdings = get_holdings()
if holdings:
    # Fetch current prices for all holdings
    current_prices = {}
    tickers_in_portfolio = list({h["ticker"] for h in holdings})
    for t in tickers_in_portfolio:
        try:
            m = get_key_metrics(t)
            current_prices[t] = m["price"]
        except Exception:
            current_prices[t] = 0

    summary = get_portfolio_summary(current_prices)

    # Summary metrics
    pc1, pc2, pc3, pc4 = st.columns(4)
    pc1.metric("Total Invested", f"${summary['total_invested']:,.2f}")
    pc2.metric("Current Value", f"${summary['total_current']:,.2f}")
    pc3.metric("Total P/L", f"${summary['total_pnl']:,.2f}", f"{summary['total_pnl_pct']:+.2f}%")
    pc4.metric("Holdings", len(summary["holdings"]))

    # Holdings table
    if summary["holdings"]:
        df = pd.DataFrame(summary["holdings"])
        df.columns = ["Ticker", "Shares", "Buy Price", "Current", "Invested", "Value", "P/L ($)", "P/L (%)"]
        st.dataframe(
            df.style.applymap(
                lambda v: "color: green" if isinstance(v, (int, float)) and v > 0 else ("color: red" if isinstance(v, (int, float)) and v < 0 else ""),
                subset=["P/L ($)", "P/L (%)"],
            ),
            width="stretch",
            hide_index=True,
        )
else:
    st.info("No holdings yet. Add stocks via the sidebar to start tracking your portfolio.")

# ── Footer ───────────────────────────────────────────────────────────────────
st.divider()
st.caption("Data from Yahoo Finance · News from NewsAPI · AI by OpenAI · Not financial advice")
