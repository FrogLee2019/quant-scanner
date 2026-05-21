"""
🐸 量化信号扫描工具 - 云端版
功能: 实时扫描、自定义股票、模拟买卖、K线图表
部署: Streamlit Community Cloud
"""

import os
import sys
import json
from datetime import datetime

import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scanner import (
    fetch_a_stock, fetch_crypto,
    STRATEGIES, compute_score, signal_emoji, signal_label,
    scan_market, generate_report,
)
from config import A_STOCKS, CRYPTO, STRATEGY_PARAMS, STRATEGY_WEIGHTS
from portfolio import (
    load_portfolio, save_portfolio, reset_portfolio,
    buy as pf_buy, sell as pf_sell, get_portfolio_summary,
)

# ============================================================
#  持久化：自定义标的（云端用session_state代替文件）
# ============================================================

def load_custom_stocks():
    """云端版：自定义标的存在session_state"""
    if "custom_stocks" not in st.session_state:
        st.session_state.custom_stocks = {"a_stock": {}, "crypto": {}}
    return st.session_state.custom_stocks

def save_custom_stocks(data):
    st.session_state.custom_stocks = data

def get_all_stocks():
    custom = load_custom_stocks()
    all_a = {**A_STOCKS, **custom.get("a_stock", {})}
    all_crypto = {**CRYPTO, **custom.get("crypto", {})}
    return all_a, all_crypto


# ============================================================
#  模拟交易（云端用session_state）
# ============================================================

def load_pf():
    if "portfolio" not in st.session_state:
        st.session_state.portfolio = {
            "cash": 1000000.0,
            "positions": {},
            "history": [],
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
    return st.session_state.portfolio

def save_pf(pf):
    st.session_state.portfolio = pf

def reset_pf():
    st.session_state.portfolio = {
        "cash": 1000000.0,
        "positions": {},
        "history": [],
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


# ============================================================
#  页面配置
# ============================================================
st.set_page_config(
    page_title="🐸 量化信号扫描",
    page_icon="🐸",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============================================================
#  侧边栏
# ============================================================
with st.sidebar:
    st.header("🐸 量化信号扫描")
    st.markdown("A股 + 加密货币 · 多策略评分")
    st.markdown("---")

    page = st.radio("功能导航", ["📊 信号总览", "📈 个股分析", "💼 模拟交易", "⚙️ 自定义标的"], index=0)

    st.markdown("---")
    st.subheader("策略权重")
    weights = {}
    for k, default_v in STRATEGY_WEIGHTS.items():
        label_map = {
            "ma_cross": "均线交叉", "rsi": "RSI", "bollinger": "布林带",
            "macd": "MACD", "volume": "成交量", "momentum": "动量",
            "position": "历史位置",
        }
        weights[k] = st.slider(label_map.get(k, k), 0.0, 3.0, default_v, 0.1, key=f"w_{k}")

    st.markdown("---")
    st.caption("⚠️ 仅供参考，不构成投资建议")


# ============================================================
#  工具函数
# ============================================================

def draw_kline(df, title=""):
    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=True,
        row_heights=[0.6, 0.2, 0.2],
        vertical_spacing=0.03,
        subplot_titles=["K线+均线", "成交量", "RSI"],
    )
    fig.add_trace(go.Candlestick(
        x=df.index, open=df["open"], high=df["high"],
        low=df["low"], close=df["close"], name="K线",
        increasing_line_color="#ef5350", decreasing_line_color="#26a69a",
    ), row=1, col=1)
    for period, color, width in [(5, "#ff9800", 1.2), (20, "#2196f3", 1.2), (60, "#9c27b0", 1)]:
        if len(df) >= period:
            ma = df["close"].rolling(period).mean()
            fig.add_trace(go.Scatter(x=df.index, y=ma, name=f"MA{period}", line=dict(color=color, width=width)), row=1, col=1)
    colors = ["#ef5350" if c >= o else "#26a69a" for c, o in zip(df["close"], df["open"])]
    fig.add_trace(go.Bar(x=df.index, y=df["volume"], name="成交量", marker_color=colors, opacity=0.7), row=2, col=1)
    delta = df["close"].diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss_r = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss_r.replace(0, float("nan"))
    rsi = 100 - (100 / (1 + rs))
    fig.add_trace(go.Scatter(x=df.index, y=rsi, name="RSI", line=dict(color="#ff5722", width=1.5)), row=3, col=1)
    fig.add_hline(y=70, line_dash="dash", line_color="red", row=3, col=1, annotation_text="超买")
    fig.add_hline(y=30, line_dash="dash", line_color="green", row=3, col=1, annotation_text="超卖")
    fig.update_layout(height=520, xaxis_rangeslider_visible=False, showlegend=True, title=title,
                      paper_bgcolor="#1a1a2e", plot_bgcolor="#0e1117",
                      font=dict(color="#ffffff"))
    for r in [1, 2, 3]:
        fig.update_xaxes(type="category", row=r, col=1, showgrid=True, gridcolor="#333")
        fig.update_yaxes(showgrid=True, gridcolor="#333", row=r, col=1)
    return fig


def analyze_one(df, params, wt):
    signals, details = {}, {}
    for sname, sfunc in STRATEGIES.items():
        try:
            s, d = sfunc(df, params)
        except Exception:
            s, d = 0, "异常"
        signals[sname] = s
        details[sname] = d
    score = compute_score(signals, wt)
    return score, signals, details


# ============================================================
#  页面1: 信号总览
# ============================================================
if page == "📊 信号总览":
    st.header("📊 信号总览")

    col1, col2 = st.columns([1, 4])
    with col1:
        market = st.radio("扫描范围", ["全部", "A股", "加密货币"], horizontal=False)
    with col2:
        if st.button("🔄 立即扫描", use_container_width=True, type="primary"):
            st.session_state["trigger_scan"] = True

    if st.session_state.get("trigger_scan", False) or "scan_results" not in st.session_state:
        market_arg = {"全部": "all", "A股": "a_stock", "加密货币": "crypto"}[market]
        all_a, all_crypto = get_all_stocks()
        import config as cfg_mod
        orig_a, orig_c = cfg_mod.A_STOCKS, cfg_mod.CRYPTO
        cfg_mod.A_STOCKS, cfg_mod.CRYPTO = all_a, all_crypto

        with st.spinner("🔍 扫描中，请稍候..."):
            results = scan_market(market_arg)
            st.session_state["scan_results"] = results
            st.session_state["scan_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            st.session_state["trigger_scan"] = False

        cfg_mod.A_STOCKS, cfg_mod.CRYPTO = orig_a, orig_c

    results = st.session_state.get("scan_results", [])
    scan_time = st.session_state.get("scan_time", "未扫描")

    if results:
        for r in results:
            r["score"] = compute_score({k: v for k, v in r.get("details", {}).items()}, weights)
            r["signal"] = f"{signal_emoji(r['score'])} {signal_label(r['score'])}"

        ranked = sorted(results, key=lambda x: x["score"], reverse=True)
        buy = [r for r in ranked if r["score"] >= 30]
        sell = [r for r in ranked if r["score"] <= -30]

        st.caption(f"⏰ {scan_time}")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("🟢 买入", len(buy))
        c2.metric("🔴 卖出", len(sell))
        c3.metric("⚪ 观望", len(results) - len(buy) - len(sell))
        c4.metric("标的数", len(results))

        st.subheader("评分排行")
        rows = []
        for r in ranked:
            rows.append({
                "信号": f"{signal_emoji(r['score'])} {signal_label(r['score'])}",
                "市场": r["market"], "名称": r["name"], "代码": r["symbol"],
                "评分": r["score"], "现价": f"{r['price']:.3f}", "止损位": f"{r['stop_loss']:.3f}",
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True, height=min(400, len(rows)*35+40))

        if buy:
            st.subheader("🟢 买入信号")
            for r in buy:
                with st.expander(f"{r['name']}（{r['symbol']}）— 评分 {r['score']}"):
                    st.write(f"现价: {r['price']:.3f} | 止损: {r['stop_loss']:.3f}")
                    for k, v in r["details"].items():
                        st.write(f"- **{k}**: {v}")
        if sell:
            st.subheader("🔴 卖出信号")
            for r in sell:
                with st.expander(f"{r['name']}（{r['symbol']}）— 评分 {r['score']}"):
                    st.write(f"现价: {r['price']:.3f}")
                    for k, v in r["details"].items():
                        st.write(f"- **{k}**: {v}")
    else:
        st.info("👆 点击「立即扫描」开始")

# ============================================================
#  页面2: 个股分析
# ============================================================
elif page == "📈 个股分析":
    st.header("📈 个股分析")

    all_a, all_crypto = get_all_stocks()
    all_options = {**{f"{v}（{k}）A股": k for k, v in all_a.items()},
                   **{f"{v}（{k}）加密": k for k, v in all_crypto.items()}}

    col1, col2 = st.columns([3, 2])
    with col1:
        selected = st.selectbox("选择标的", list(all_options.keys()), index=0)
    with col2:
        custom_code = st.text_input("或输入代码", placeholder="如 600519 或 BTC/USDT")

    code = custom_code.strip() if custom_code.strip() else all_options.get(selected, "")
    if code:
        is_crypto = "/" in code
        with st.spinner(f"获取 {code} 数据..."):
            df = fetch_crypto(code, 250) if is_crypto else fetch_a_stock(code, 250)

        if df is None or len(df) < 30:
            st.error(f"无法获取 {code} 的数据")
        else:
            score, signals, details = analyze_one(df, STRATEGY_PARAMS, weights)
            name = all_crypto.get(code, code) if is_crypto else all_a.get(code, code)

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("现价", f"{df['close'].iloc[-1]:.3f}")
            c2.metric("评分", f"{score}", f"{signal_emoji(score)} {signal_label(score)}")
            pct5 = (df['close'].iloc[-1] / df['close'].iloc[-5] - 1) * 100
            c3.metric("5日涨跌", f"{pct5:+.1f}%")
            c4.metric("止损参考", f"{df['low'].tail(20).min():.3f}")

            st.plotly_chart(draw_kline(df, f"{name}（{code}）"), use_container_width=True)

            label_map = {
                "ma_cross": "均线交叉", "rsi": "RSI", "bollinger": "布林带",
                "macd": "MACD", "volume": "成交量", "momentum": "动量",
                "position": "历史位置",
            }
            st.subheader("策略详情")
            detail_rows = [{"策略": label_map.get(k, k), "信号": details.get(k, ""), "得分": signals.get(k, 0)} for k in STRATEGIES]
            st.dataframe(pd.DataFrame(detail_rows), use_container_width=True, hide_index=True)

# ============================================================
#  页面3: 模拟交易
# ============================================================
elif page == "💼 模拟交易":
    st.header("💼 模拟交易")

    pf = load_pf()
    all_a, all_crypto = get_all_stocks()

    # 获取当前价格
    current_prices = {}
    price_placeholder = st.empty()
    with st.spinner("更新持仓价格..."):
        for sym, pos in pf["positions"].items():
            try:
                df = fetch_crypto(sym, 5) if pos["market"] == "加密货币" else fetch_a_stock(sym, 5)
                if df is not None and len(df) > 0:
                    current_prices[sym] = df["close"].iloc[-1]
                else:
                    current_prices[sym] = pos["avg_cost"]
            except Exception:
                current_prices[sym] = pos["avg_cost"]

    summary = get_portfolio_summary(pf, current_prices)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("💰 总资产", f"¥{summary['总资产']:,.0f}")
    c2.metric("💵 现金", f"¥{summary['现金']:,.0f}")
    c3.metric("📊 持仓市值", f"¥{summary['持仓市值']:,.0f}")
    c4.metric("📈 总收益率", summary["总收益率"], delta=f"¥{summary['总盈亏']:+,.0f}")

    st.subheader("📋 当前持仓")
    if summary["positions"]:
        pos_df = pd.DataFrame(summary["positions"])
        # 颜色标记盈亏
        def color_profit(val):
            if isinstance(val, str) and val.startswith("+"):
                return "color: #4CAF50"
            elif isinstance(val, str) and val.startswith("-"):
                return "color: #f44336"
            return ""
        styled = pos_df.style.map(color_profit, subset=["盈亏%"])
        st.dataframe(pos_df, use_container_width=True, hide_index=True)
    else:
        st.info("暂无持仓，去买入吧 🐸")

    st.markdown("---")
    col_buy, col_sell = st.columns(2)

    with col_buy:
        st.subheader("🟢 买入")
        buy_code = st.text_input("代码", placeholder="600519 或 BTC/USDT", key="buy_code")
        buy_amount = st.number_input("数量（0=自动1/4仓位）", min_value=0, value=0, step=100, key="buy_amount")
        if st.button("✅ 确认买入", key="buy_btn", use_container_width=True):
            if not buy_code.strip():
                st.warning("请输入代码")
            else:
                code = buy_code.strip()
                is_crypto = "/" in code
                name = all_crypto.get(code, code) if is_crypto else all_a.get(code, code)
                market_label = "加密货币" if is_crypto else "A股"
                df = fetch_crypto(code, 5) if is_crypto else fetch_a_stock(code, 5)
                if df is not None and len(df) > 0:
                    price = df["close"].iloc[-1]
                    amt = buy_amount if buy_amount > 0 else None
                    pf, ok, msg = pf_buy(pf, code, name, market_label, price, amt)
                    if ok:
                        save_pf(pf)
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)
                else:
                    st.error("无法获取数据")

    with col_sell:
        st.subheader("🔴 卖出")
        sell_options = list(pf["positions"].keys())
        if sell_options:
            sell_code = st.selectbox("卖出标的", sell_options, key="sell_code",
                                      format_func=lambda x: f"{pf['positions'][x]['name']}({x}) {pf['positions'][x]['shares']}股")
            sell_amount = st.number_input("数量（0=清仓）", min_value=0, value=0, step=100, key="sell_amount")
            if st.button("✅ 确认卖出", key="sell_btn", use_container_width=True):
                df = fetch_crypto(sell_code, 5) if "/" in sell_code else fetch_a_stock(sell_code, 5)
                if df is not None and len(df) > 0:
                    price = df["close"].iloc[-1]
                    amt = sell_amount if sell_amount > 0 else None
                    pf, ok, msg = pf_sell(pf, sell_code, price, amt)
                    if ok:
                        save_pf(pf)
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)
                else:
                    st.error("无法获取数据")
        else:
            st.info("暂无持仓")

    st.markdown("---")
    col_hist, col_reset = st.columns([4, 1])
    with col_hist:
        st.subheader("📜 交易记录")
        if pf["history"]:
            st.dataframe(pd.DataFrame(pf["history"]), use_container_width=True, hide_index=True, height=250)
        else:
            st.info("暂无交易记录")
    with col_reset:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("⚠️ 重置账户"):
            reset_pf()
            st.rerun()

# ============================================================
#  页面4: 自定义标的
# ============================================================
elif page == "⚙️ 自定义标的":
    st.header("⚙️ 自定义标的")
    st.caption("添加的标的会在下次扫描时自动纳入")

    custom = load_custom_stocks()
    col_a, col_c = st.columns(2)

    with col_a:
        st.subheader("🇨🇳 A股")
        if custom.get("a_stock"):
            for code, name in list(custom["a_stock"].items()):
                c1, c2 = st.columns([4, 1])
                c1.text(f"📌 {name}（{code}）")
                if c2.button("🗑️", key=f"del_a_{code}"):
                    del custom["a_stock"][code]
                    save_custom_stocks(custom)
                    st.rerun()
        else:
            st.info("暂无自定义A股")

        st.markdown("---")
        st.markdown("**➕ 添加A股**")
        new_a_code = st.text_input("股票代码", placeholder="如 002226", key="new_a_code")
        new_a_name = st.text_input("股票名称", placeholder="如 江南化工", key="new_a_name")
        if st.button("➕ 添加", key="add_a"):
            if new_a_code.strip() and new_a_name.strip():
                with st.spinner("验证数据..."):
                    df = fetch_a_stock(new_a_code.strip(), 30)
                if df is not None and len(df) >= 30:
                    if "a_stock" not in custom:
                        custom["a_stock"] = {}
                    custom["a_stock"][new_a_code.strip()] = new_a_name.strip()
                    save_custom_stocks(custom)
                    st.success(f"✅ 已添加 {new_a_name.strip()}（{new_a_code.strip()}）")
                    st.rerun()
                else:
                    st.error("❌ 无法获取该股票数据")
            else:
                st.warning("请输入代码和名称")

    with col_c:
        st.subheader("🪙 加密货币")
        if custom.get("crypto"):
            for code, name in list(custom["crypto"].items()):
                c1, c2 = st.columns([4, 1])
                c1.text(f"📌 {name}（{code}）")
                if c2.button("🗑️", key=f"del_c_{code}"):
                    del custom["crypto"][code]
                    save_custom_stocks(custom)
                    st.rerun()
        else:
            st.info("暂无自定义加密货币")

        st.markdown("---")
        st.markdown("**➕ 添加加密货币**")
        new_c_code = st.text_input("交易对", placeholder="如 LINK/USDT", key="new_c_code")
        new_c_name = st.text_input("名称", placeholder="如 ChainLink", key="new_c_name")
        if st.button("➕ 添加", key="add_c"):
            if new_c_code.strip() and new_c_name.strip():
                with st.spinner("验证数据..."):
                    df = fetch_crypto(new_c_code.strip(), 30)
                if df is not None and len(df) >= 30:
                    if "crypto" not in custom:
                        custom["crypto"] = {}
                    custom["crypto"][new_c_code.strip()] = new_c_name.strip()
                    save_custom_stocks(custom)
                    st.success(f"✅ 已添加 {new_c_name.strip()}（{new_c_code.strip()}）")
                    st.rerun()
                else:
                    st.error("❌ 无法获取该交易对数据")
            else:
                st.warning("请输入交易对和名称")
