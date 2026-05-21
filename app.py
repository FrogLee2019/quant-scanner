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
#  持久化：自选标的（云端用session_state）
# ============================================================

STOCKS_KEY = "my_stocks"

def _default_stocks():
    """默认自选列表，从config初始化"""
    return {
        "a_stock": dict(A_STOCKS),
        "crypto": dict(CRYPTO),
    }

def load_my_stocks():
    if STOCKS_KEY not in st.session_state:
        st.session_state[STOCKS_KEY] = _default_stocks()
    return st.session_state[STOCKS_KEY]

def save_my_stocks(data):
    st.session_state[STOCKS_KEY] = data

def add_stock(market, code, name):
    stocks = load_my_stocks()
    key = "a_stock" if market == "A股" else "crypto"
    stocks[key][code] = name
    save_my_stocks(stocks)

def remove_stock(code):
    stocks = load_my_stocks()
    for key in ["a_stock", "crypto"]:
        stocks[key].pop(code, None)
    save_my_stocks(stocks)

def get_all_stocks():
    stocks = load_my_stocks()
    return stocks.get("a_stock", {}), stocks.get("crypto", {})

def format_stock_label(code, name, market=""):
    """格式化下拉菜单显示"""
    return f"{name}（{code}）{market}"

def build_stock_options(all_a, all_crypto):
    """构建下拉选项，返回 {显示文本: 代码}"""
    options = {}
    for code, name in all_a.items():
        options[format_stock_label(code, name, "A股")] = code
    for code, name in all_crypto.items():
        options[format_stock_label(code, name, "加密")] = code
    return options


# ============================================================
#  模拟交易（云端用session_state）
# ============================================================

PF_KEY = "portfolio"

def load_pf():
    if PF_KEY not in st.session_state:
        st.session_state[PF_KEY] = {
            "cash": 1000000.0,
            "positions": {},
            "history": [],
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
    return st.session_state[PF_KEY]

def save_pf(pf):
    st.session_state[PF_KEY] = pf

def reset_pf():
    st.session_state[PF_KEY] = {
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

    page = st.radio("功能导航", ["📊 信号总览", "📈 个股分析", "💼 模拟交易", "⚙️ 自选管理"], index=0)

    st.markdown("---")
    st.subheader("策略权重")
    weights = {}
    label_map = {
        "ma_cross": "均线交叉", "rsi": "RSI", "bollinger": "布林带",
        "macd": "MACD", "volume": "成交量", "momentum": "动量",
        "position": "历史位置",
    }
    for k, default_v in STRATEGY_WEIGHTS.items():
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


def fetch_price(code, is_crypto=False):
    """获取最新价格"""
    try:
        df = fetch_crypto(code, 5) if is_crypto else fetch_a_stock(code, 5)
        if df is not None and len(df) > 0:
            return df["close"].iloc[-1]
    except Exception:
        pass
    return None


def lookup_stock_name(code):
    """通过代码自动查询股票名称"""
    is_crypto = "/" in code
    if is_crypto:
        # 加密货币：从交易对提取，如 BTC/USDT -> 比特币
        crypto_names = {
            "BTC/USDT": "比特币", "ETH/USDT": "以太坊", "SOL/USDT": "Solana",
            "BNB/USDT": "币安币", "XRP/USDT": "瑞波币", "ADA/USDT": "艾达币",
            "DOGE/USDT": "狗狗币", "AVAX/USDT": "雪崩", "DOT/USDT": "波卡",
            "LINK/USDT": "ChainLink", "MATIC/USDT": "Polygon", "SHIB/USDT": "柴犬币",
            "UNI/USDT": "Uniswap", "LTC/USDT": "莱特币", "ATOM/USDT": "Cosmos",
        }
        return crypto_names.get(code, code.split("/")[0])
    
    # A股：用baostock查
    try:
        import baostock as bs
        import io, contextlib
        prefix = "sh." if code.startswith("6") or code.startswith("51") else "sz."
        with contextlib.redirect_stdout(io.StringIO()):
            bs.login()
        rs = bs.query_stock_basic(code=prefix + code)
        name = None
        while (rs.error_code == "0") and rs.next():
            row = rs.get_row_data()
            if len(row) > 1:
                name = row[1]
                break
        with contextlib.redirect_stdout(io.StringIO()):
            bs.logout()
        if name:
            return name
    except Exception:
        pass
    
    return None


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

    if st.session_state.get("trigger_scan", False):
        market_arg = {"全部": "all", "A股": "a_stock", "加密货币": "crypto"}[market]
        all_a, all_crypto = get_all_stocks()
        import config as cfg_mod
        orig_a, orig_c = cfg_mod.A_STOCKS, cfg_mod.CRYPTO
        cfg_mod.A_STOCKS, cfg_mod.CRYPTO = all_a, all_crypto

        with st.spinner("🔍 扫描中，首次可能需要1-2分钟..."):
            results = scan_market(market_arg)
            st.session_state["scan_results"] = results
            st.session_state["scan_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            st.session_state["trigger_scan"] = False

        cfg_mod.A_STOCKS, cfg_mod.CRYPTO = orig_a, orig_c

    results = st.session_state.get("scan_results", [])
    scan_time = st.session_state.get("scan_time", "未扫描")

    if results:
        for r in results:
            r["score"] = compute_score(r.get("signals", {}), weights)
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
                        st.write(f"- **{label_map.get(k, k)}**: {v}")
        if sell:
            st.subheader("🔴 卖出信号")
            for r in sell:
                with st.expander(f"{r['name']}（{r['symbol']}）— 评分 {r['score']}"):
                    st.write(f"现价: {r['price']:.3f}")
                    for k, v in r["details"].items():
                        st.write(f"- **{label_map.get(k, k)}**: {v}")
    else:
        st.info("👆 点击「立即扫描」开始")

# ============================================================
#  页面2: 个股分析
# ============================================================
elif page == "📈 个股分析":
    st.header("📈 个股分析")

    all_a, all_crypto = get_all_stocks()
    options = build_stock_options(all_a, all_crypto)

    selected = st.selectbox("选择标的", list(options.keys()), index=0)
    code = options.get(selected, "")

    if code:
        is_crypto = "/" in code
        market_label = "加密货币" if is_crypto else "A股"
        name = all_crypto.get(code, code) if is_crypto else all_a.get(code, code)

        col_info, col_del = st.columns([5, 1])
        with col_info:
            pass
        with col_del:
            if st.button("🗑️ 移出自选"):
                remove_stock(code)
                st.success(f"已移除 {name}")
                st.rerun()

        with st.spinner(f"获取 {name} 数据..."):
            df = fetch_crypto(code, 250) if is_crypto else fetch_a_stock(code, 250)

        if df is None or len(df) < 30:
            st.error(f"无法获取 {code} 的数据")
        else:
            score, signals, details = analyze_one(df, STRATEGY_PARAMS, weights)

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("现价", f"{df['close'].iloc[-1]:.3f}")
            c2.metric("评分", f"{score}", f"{signal_emoji(score)} {signal_label(score)}")
            pct5 = (df['close'].iloc[-1] / df['close'].iloc[-5] - 1) * 100
            c3.metric("5日涨跌", f"{pct5:+.1f}%")
            c4.metric("止损参考", f"{df['low'].tail(20).min():.3f}")

            st.plotly_chart(draw_kline(df, f"{name}（{code}）"), use_container_width=True)

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
    with st.spinner("更新持仓价格..."):
        for sym, pos in pf["positions"].items():
            price = fetch_price(sym, pos["market"] == "加密货币")
            current_prices[sym] = price if price else pos["avg_cost"]

    summary = get_portfolio_summary(pf, current_prices)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("💰 总资产", f"¥{summary['总资产']:,.0f}")
    c2.metric("💵 现金", f"¥{summary['现金']:,.0f}")
    c3.metric("📊 持仓市值", f"¥{summary['持仓市值']:,.0f}")
    c4.metric("📈 总收益率", summary["总收益率"], delta=f"¥{summary['总盈亏']:+,.0f}")

    st.subheader("📋 当前持仓")
    if summary["positions"]:
        st.dataframe(pd.DataFrame(summary["positions"]), use_container_width=True, hide_index=True)
    else:
        st.info("暂无持仓，去买点吧 🐸")

    st.markdown("---")

    # 构建买卖用的下拉选项
    buy_options = build_stock_options(all_a, all_crypto)

    col_buy, col_sell = st.columns(2)

    with col_buy:
        st.subheader("🟢 买入")
        buy_selected = st.selectbox("选择标的", list(buy_options.keys()), key="buy_select")
        buy_code = buy_options.get(buy_selected, "")
        is_crypto_buy = "/" in buy_code
        buy_name = all_crypto.get(buy_code, buy_code) if is_crypto_buy else all_a.get(buy_code, buy_code)
        market_label_buy = "加密货币" if is_crypto_buy else "A股"

        # 显示当前价格
        if buy_code:
            with st.spinner("获取价格..."):
                cur_price = fetch_price(buy_code, is_crypto_buy)
            if cur_price:
                st.info(f"💡 {buy_name} 当前价格: **{cur_price:.3f}**")

        buy_amount = st.number_input("数量（0=自动1/4仓位）", min_value=0, value=0, step=100, key="buy_amount")
        if st.button("✅ 确认买入", key="buy_btn", use_container_width=True, type="primary"):
            if cur_price:
                amt = buy_amount if buy_amount > 0 else None
                pf, ok, msg = pf_buy(pf, buy_code, buy_name, market_label_buy, cur_price, amt)
                if ok:
                    save_pf(pf)
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)
            else:
                st.error("无法获取价格")

    with col_sell:
        st.subheader("🔴 卖出")
        sell_options = list(pf["positions"].keys())
        if sell_options:
            sell_code = st.selectbox("选择持仓", sell_options, key="sell_select",
                                      format_func=lambda x: f"{pf['positions'][x]['name']}({x}) {pf['positions'][x]['shares']}股")
            sell_name = pf["positions"][sell_code]["name"]
            is_crypto_sell = pf["positions"][sell_code]["market"] == "加密货币"
            cur_sell_price = fetch_price(sell_code, is_crypto_sell)
            if cur_sell_price:
                st.info(f"💡 {sell_name} 当前价格: **{cur_sell_price:.3f}**")

            sell_amount = st.number_input("数量（0=清仓）", min_value=0, value=0, step=100, key="sell_amount")
            if st.button("✅ 确认卖出", key="sell_btn", use_container_width=True, type="primary"):
                if cur_sell_price:
                    amt = sell_amount if sell_amount > 0 else None
                    pf, ok, msg = pf_sell(pf, sell_code, cur_sell_price, amt)
                    if ok:
                        save_pf(pf)
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)
                else:
                    st.error("无法获取价格")
        else:
            st.info("暂无持仓可卖")

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
#  页面4: 自选管理
# ============================================================
elif page == "⚙️ 自选管理":
    st.header("⚙️ 自选管理")
    st.caption("管理你的自选标的列表，移除不想看的、添加想关注的")

    all_a, all_crypto = get_all_stocks()

    # 当前自选列表
    st.subheader("📋 当前自选")

    tab_a, tab_c = st.tabs([f"🇨🇳 A股（{len(all_a)}只）", f"🪙 加密货币（{len(all_crypto)}个）"])

    with tab_a:
        if all_a:
            cols_per_row = 4
            codes = list(all_a.keys())
            names = list(all_a.values())
            for i in range(0, len(codes), cols_per_row):
                cols = st.columns(cols_per_row)
                for j, col in enumerate(cols):
                    if i + j < len(codes):
                        c = codes[i + j]
                        n = names[i + j]
                        col.markdown(f"**{n}** `{c}`")
                        if col.button("移除", key=f"rm_a_{c}"):
                            remove_stock(c)
                            st.rerun()
        else:
            st.info("暂无A股自选")

        st.markdown("---")
        st.markdown("**➕ 添加A股**")
        new_a_code = st.text_input("输入股票代码", placeholder="如 002226", key="new_a_code")
        if st.button("➕ 添加", key="add_a"):
            if new_a_code.strip():
                code = new_a_code.strip()
                with st.spinner("查询中..."):
                    name = lookup_stock_name(code)
                if name:
                    # 验证数据可用
                    df = fetch_a_stock(code, 30)
                    if df is not None and len(df) >= 30:
                        add_stock("A股", code, name)
                        st.success(f"✅ 已添加 **{name}**（{code}）")
                        st.rerun()
                    else:
                        st.error("❌ 无法获取该股票数据")
                else:
                    st.error("❌ 未找到该股票，请检查代码")

    with tab_c:
        if all_crypto:
            cols_per_row = 4
            codes = list(all_crypto.keys())
            names = list(all_crypto.values())
            for i in range(0, len(codes), cols_per_row):
                cols = st.columns(cols_per_row)
                for j, col in enumerate(cols):
                    if i + j < len(codes):
                        c = codes[i + j]
                        n = names[i + j]
                        col.markdown(f"**{n}** `{c}`")
                        if col.button("移除", key=f"rm_c_{c}"):
                            remove_stock(c)
                            st.rerun()
        else:
            st.info("暂无加密货币自选")

        st.markdown("---")
        st.markdown("**➕ 添加加密货币**")
        new_c_code = st.text_input("输入交易对", placeholder="如 LINK/USDT", key="new_c_code")
        if st.button("➕ 添加", key="add_c"):
            if new_c_code.strip():
                code = new_c_code.strip()
                with st.spinner("查询中..."):
                    name = lookup_stock_name(code)
                if name:
                    df = fetch_crypto(code, 30)
                    if df is not None and len(df) >= 30:
                        add_stock("加密货币", code, name)
                        st.success(f"✅ 已添加 **{name}**（{code}）")
                        st.rerun()
                    else:
                        st.error("❌ 无法获取该交易对数据")
                else:
                    st.error("❌ 未找到该交易对，请检查格式（如 LINK/USDT）")

    # 恢复默认
    st.markdown("---")
    if st.button("🔄 恢复默认自选列表"):
        st.session_state[STOCKS_KEY] = _default_stocks()
        st.success("已恢复默认列表")
        st.rerun()
