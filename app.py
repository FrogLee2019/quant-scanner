"""
🐸 量化信号扫描工具 - 云端版
功能: 实时扫描、自定义股票、模拟买卖、K线图表
部署: Streamlit Community Cloud
"""

import os
import sys
import json
import threading
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
    search_a_stock, search_crypto, CRYPTO_NAME_MAP,
)
from config import A_STOCKS, CRYPTO, STRATEGY_PARAMS, STRATEGY_WEIGHTS
from portfolio import (
    load_portfolio, save_portfolio, reset_portfolio,
    buy as pf_buy, sell as pf_sell, get_portfolio_summary,
)

# ============================================================
#  策略中文说明（小白友好版）
# ============================================================
STRATEGY_INFO = {
    "ma_cross": {
        "name": "均线交叉",
        "weight_key": "均线交叉",
        "explain": "短期均线上穿长期均线叫"金叉"（看涨），下穿叫"死叉"（看跌）。就像两条河流交叉，短期趋势超过长期趋势就是变盘信号。",
        "params": "快线MA5 / 慢线MA20",
    },
    "rsi": {
        "name": "RSI强弱指标",
        "weight_key": "RSI强弱",
        "explain": "衡量近期涨跌力度，0-100之间。>70为超买（涨太多可能要跌），<30为超卖（跌太多可能要涨）。就像弹簧，压得太狠会弹回来。",
        "params": "周期14天，超买70，超卖30",
    },
    "bollinger": {
        "name": "布林带",
        "weight_key": "布林带",
        "explain": "在均线基础上画上下两条"轨道"。价格触及上轨可能要回调，触及下轨可能要反弹。就像皮筋拉太紧会回弹。",
        "params": "中轨MA20，上下2倍标准差",
    },
    "macd": {
        "name": "MACD趋势",
        "weight_key": "MACD趋势",
        "explain": "判断趋势方向的经典指标。DIF上穿DEA叫金叉（看涨），红柱放大说明多头变强。相当于更灵敏的均线系统。",
        "params": "快线12 / 慢线26 / 信号9",
    },
    "volume": {
        "name": "成交量异动",
        "weight_key": "成交量",
        "explain": "量价配合：放量上涨是真的涨，放量下跌是真的跌。缩量说明市场冷淡，方向不明。就像人多力量大。",
        "params": "量比阈值2.0倍",
    },
    "momentum": {
        "name": "动量强度",
        "weight_key": "动量强度",
        "explain": "最近一段时间的涨跌幅度。动量>5%说明涨势很强，<-5%说明跌势很猛。趋势一旦形成，短期容易延续。",
        "params": "观察期20天",
    },
    "position": {
        "name": "历史位置",
        "weight_key": "历史位置",
        "explain": "当前价格在过去1年的位置百分位。10%分位=近1年最低区域（可能见底），90%分位=近1年最高区域（注意风险）。好货便宜了才值得买。",
        "params": "观察1年（250个交易日）",
    },
}

label_map = {k: v["weight_key"] for k, v in STRATEGY_INFO.items()}

# ============================================================
#  后台扫描状态管理（模块级，跨rerun持久）
# ============================================================
_scan_state = {
    "is_scanning": False,
    "total": 0,
    "completed": 0,
    "last_stock": "",
    "error": None,
}

AUTO_SCAN_INTERVAL = 30 * 60  # 30分钟自动扫描


def _on_scan_progress(completed, total, symbol, name):
    _scan_state["completed"] = completed
    _scan_state["total"] = total
    _scan_state["last_stock"] = f"{name}（{symbol}）"


def _run_bg_scan(market_type, all_a, all_crypto):
    _scan_state["is_scanning"] = True
    _scan_state["total"] = 0
    _scan_state["completed"] = 0
    _scan_state["last_stock"] = "准备中..."
    _scan_state["error"] = None

    import config as cfg_mod
    orig_a, orig_c = cfg_mod.A_STOCKS, cfg_mod.CRYPTO
    cfg_mod.A_STOCKS, cfg_mod.CRYPTO = all_a, all_crypto

    try:
        results = scan_market(market_type, on_progress=_on_scan_progress)
        st.session_state["scan_results"] = results
        st.session_state["scan_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    except Exception as e:
        _scan_state["error"] = str(e)
    finally:
        _scan_state["is_scanning"] = False
        cfg_mod.A_STOCKS, cfg_mod.CRYPTO = orig_a, orig_c


def start_bg_scan(market_type="all"):
    if _scan_state["is_scanning"]:
        return
    all_a, all_crypto = get_all_stocks()
    thread = threading.Thread(target=_run_bg_scan, args=(market_type, all_a, all_crypto), daemon=True)
    thread.start()


def should_auto_scan():
    if _scan_state["is_scanning"]:
        return False
    last = st.session_state.get("scan_time")
    if not last:
        return True
    try:
        last_dt = datetime.strptime(last, "%Y-%m-%d %H:%M:%S")
        return (datetime.now() - last_dt).total_seconds() >= AUTO_SCAN_INTERVAL
    except Exception:
        return True


# ============================================================
#  持久化：自选标的（云端用session_state）
# ============================================================

STOCKS_KEY = "my_stocks"

def _default_stocks():
    return {"a_stock": dict(A_STOCKS), "crypto": dict(CRYPTO)}

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
    return f"{name}（{code}）{market}"

def build_stock_options(all_a, all_crypto):
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
            "cash": 1000000.0, "positions": {}, "history": [],
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
    return st.session_state[PF_KEY]

def save_pf(pf):
    st.session_state[PF_KEY] = pf

def reset_pf():
    st.session_state[PF_KEY] = {
        "cash": 1000000.0, "positions": {}, "history": [],
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


# ============================================================
#  页面配置
# ============================================================
st.set_page_config(
    page_title="🐸 量化信号扫描",
    page_icon="🐸",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# ============================================================
#  顶部导航栏
# ============================================================
st.markdown("""
<style>
    .stTabs [data-baseweb="tab-list"] { gap: 8px; }
    .stTabs [data-baseweb="tab"] { padding: 8px 16px; font-size: 15px; }
    div[data-testid="stMetricValue"] { font-size: 18px; }
    div[data-testid="stMetricDelta"] { font-size: 13px; }
    .compact-metric { text-align: center; }
</style>
""", unsafe_allow_html=True)

# 标题行：logo + 扫描状态 + 按钮
col_logo, col_status, col_btn = st.columns([2, 3, 1])
with col_logo:
    st.markdown("### 🐸 量化信号扫描")
with col_status:
    if _scan_state["is_scanning"]:
        pct = _scan_state["completed"] / max(_scan_state["total"], 1)
        st.progress(pct)
        st.caption(f"🔍 {_scan_state['last_stock']} | {_scan_state['completed']}/{_scan_state['total']}")
    else:
        last_t = st.session_state.get("scan_time", "未扫描")
        st.caption(f"⏰ 上次扫描: {last_t}")
with col_btn:
    if st.button("🔄 扫描", type="primary", use_container_width=True):
        start_bg_scan("all")

# 顶部选项卡
tab_names = ["📊 信号总览", "📈 个股分析", "💼 模拟交易", "⚙️ 自选管理", "🎛️ 策略设置"]
tabs = st.tabs(tab_names)

# 自动扫描检查
if should_auto_scan():
    start_bg_scan("all")


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
    fig.update_layout(height=480, xaxis_rangeslider_visible=False, showlegend=True, title=title,
                      paper_bgcolor="#1a1a2e", plot_bgcolor="#0e1117",
                      font=dict(color="#ffffff"), margin=dict(l=40, r=20, t=40, b=20))
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
    try:
        df = fetch_crypto(code, 5) if is_crypto else fetch_a_stock(code, 5)
        if df is not None and len(df) > 0:
            return df["close"].iloc[-1]
    except Exception:
        pass
    return None


# ============================================================
#  Tab 1: 信号总览（紧凑表格 + 排序 + 展开）
# ============================================================
with tabs[0]:
    # 扫描进行中：定时刷新
    if _scan_state["is_scanning"]:
        # 用meta标签实现自动刷新（5秒），纯HTML不需要额外包
        st.markdown('<meta http-equiv="refresh" content="5">', unsafe_allow_html=True)

    results = st.session_state.get("scan_results", [])
    scan_time = st.session_state.get("scan_time", "未扫描")

    # 读取当前权重
    weights = st.session_state.get("custom_weights", dict(STRATEGY_WEIGHTS))

    if results and not _scan_state["is_scanning"]:
        for r in results:
            r["score"] = compute_score(r.get("signals", {}), weights)

        # 排序控件
        col_sort, col_market = st.columns([1, 2])
        with col_sort:
            sort_by = st.selectbox("排序", ["评分↓", "评分↑", "名称A-Z", "名称Z-A", "5日涨幅↓", "5日涨幅↑"], index=0, key="sort_sel")
        with col_market:
            filter_market = st.selectbox("筛选", ["全部", "A股", "加密货币"], key="filter_market")

        # 过滤
        if filter_market != "全部":
            filtered = [r for r in results if r["market"] == filter_market]
        else:
            filtered = results

        # 排序
        sort_map = {
            "评分↓": lambda x: -x["score"],
            "评分↑": lambda x: x["score"],
            "名称A-Z": lambda x: x["name"],
            "名称Z-A": lambda x: x["name"],
        }
        if sort_by in sort_map:
            ranked = sorted(filtered, key=sort_map[sort_by])
        elif "5日涨幅↓" in sort_by:
            ranked = sorted(filtered, key=lambda x: -x.get("momentum_pct", 0))
        elif "5日涨幅↑" in sort_by:
            ranked = sorted(filtered, key=lambda x: x.get("momentum_pct", 0))
        else:
            ranked = sorted(filtered, key=lambda x: -x["score"])

        buy = [r for r in ranked if r["score"] >= 30]
        sell = [r for r in ranked if r["score"] <= -30]

        # 紧凑概览条
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("🟢 买入", len(buy))
        c2.metric("🔴 卖出", len(sell))
        c3.metric("⚪ 观望", len(ranked) - len(buy) - len(sell))
        c4.caption(f"⏰ {scan_time}")

        # 主表格：紧凑、可排序、一行一标的
        table_rows = []
        for r in ranked:
            # 计算5日涨跌
            pct5_str = ""
            pct5_val = 0
            if "signals" in r:
                mom_detail = r.get("details", {}).get("momentum", "")
                if "%" in mom_detail:
                    import re
                    m = re.search(r'([+-]?\d+\.?\d*)%', mom_detail)
                    if m:
                        pct5_val = float(m.group(1))
                        pct5_str = f"{pct5_val:+.1f}%"
            r["momentum_pct"] = pct5_val

            table_rows.append({
                "信号": f"{signal_emoji(r['score'])}",
                "名称": r["name"],
                "代码": r["symbol"],
                "市场": r["market"],
                "现价": round(r["price"], 3),
                "5日涨幅": pct5_str,
                "评分": r["score"],
                "止损位": round(r["stop_loss"], 3),
            })

        df_table = pd.DataFrame(table_rows)

        st.dataframe(
            df_table,
            use_container_width=True,
            hide_index=True,
            height=min(500, len(table_rows) * 35 + 40),
            column_config={
                "评分": st.column_config.NumberColumn(format="%.1f"),
                "现价": st.column_config.NumberColumn(format="%.3f"),
                "止损位": st.column_config.NumberColumn(format="%.3f"),
            },
        )

        # 展开详情
        st.markdown("---")
        st.markdown("**📋 点击展开评分详情**")

        # 买入信号
        if buy:
            for r in buy:
                with st.expander(f"🟢 {r['name']}（{r['symbol']}）— 评分 {r['score']}", expanded=False):
                    detail_cols = st.columns(3)
                    detail_cols[0].write(f"**现价:** {r['price']:.3f}")
                    detail_cols[1].write(f"**止损位:** {r['stop_loss']:.3f}")
                    detail_cols[2].write(f"**市场:** {r['market']}")
                    for k, v in r["details"].items():
                        info = STRATEGY_INFO.get(k, {})
                        label = info.get("name", k)
                        st.write(f"- **{label}**: {v}")

        # 卖出信号
        if sell:
            for r in sell:
                with st.expander(f"🔴 {r['name']}（{r['symbol']}）— 评分 {r['score']}", expanded=False):
                    detail_cols = st.columns(3)
                    detail_cols[0].write(f"**现价:** {r['price']:.3f}")
                    detail_cols[1].write(f"**止损位:** {r['stop_loss']:.3f}")
                    detail_cols[2].write(f"**市场:** {r['market']}")
                    for k, v in r["details"].items():
                        info = STRATEGY_INFO.get(k, {})
                        label = info.get("name", k)
                        st.write(f"- **{label}**: {v}")

        # 其他标的（折叠）
        mid = [r for r in ranked if -30 < r["score"] < 30]
        if mid:
            with st.expander(f"⚪ 观望标的（{len(mid)}个）", expanded=False):
                for r in mid:
                    brief = " | ".join([f"{STRATEGY_INFO.get(k,{}).get('name',k)}:{v}" for k, v in r["details"].items() if v != "数据不足" and v != "量能正常" and v != "动量平淡"])
                    st.write(f"**{r['name']}** `{r['symbol']}` — 评分 {r['score']} | {brief}")

    elif results and _scan_state["is_scanning"]:
        with st.expander("📋 上次扫描结果（新扫描完成后自动更新）", expanded=False):
            st.caption(f"⏰ {scan_time}")
            rows = []
            for r in sorted(results, key=lambda x: x.get("score", 0), reverse=True):
                r["score"] = compute_score(r.get("signals", {}), weights)
                rows.append({
                    "信号": f"{signal_emoji(r['score'])}",
                    "名称": r["name"], "代码": r["symbol"],
                    "市场": r["market"], "评分": r["score"], "现价": round(r["price"], 3),
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    elif not _scan_state["is_scanning"]:
        st.info("👆 点击右上角「扫描」按钮开始扫描")


# ============================================================
#  Tab 2: 个股分析
# ============================================================
with tabs[1]:
    all_a, all_crypto = get_all_stocks()
    options = build_stock_options(all_a, all_crypto)

    col_sel, col_del = st.columns([5, 1])
    with col_sel:
        selected = st.selectbox("选择标的", list(options.keys()), index=0, key="stock_select")
    with col_del:
        st.markdown("<br>", unsafe_allow_html=True)
        code = options.get(selected, "")
        if code:
            is_crypto = "/" in code
            name = all_crypto.get(code, code) if is_crypto else all_a.get(code, code)
            if st.button("🗑️ 移出自选", key="rm_stock"):
                remove_stock(code)
                st.success(f"已移除 {name}")
                st.rerun()

    if code:
        is_crypto = "/" in code
        name = all_crypto.get(code, code) if is_crypto else all_a.get(code, code)
        weights = st.session_state.get("custom_weights", dict(STRATEGY_WEIGHTS))

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
            detail_rows = []
            for k in STRATEGIES:
                info = STRATEGY_INFO.get(k, {})
                detail_rows.append({
                    "策略": info.get("name", k),
                    "信号": details.get(k, ""),
                    "得分": signals.get(k, 0),
                    "说明": info.get("explain", ""),
                })
            st.dataframe(pd.DataFrame(detail_rows), use_container_width=True, hide_index=True)


# ============================================================
#  Tab 3: 模拟交易
# ============================================================
with tabs[2]:
    pf = load_pf()
    all_a, all_crypto = get_all_stocks()

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

    buy_options = build_stock_options(all_a, all_crypto)

    col_buy, col_sell = st.columns(2)

    with col_buy:
        st.subheader("🟢 买入")
        buy_selected = st.selectbox("选择标的", list(buy_options.keys()), key="buy_select")
        buy_code = buy_options.get(buy_selected, "")
        is_crypto_buy = "/" in buy_code
        buy_name = all_crypto.get(buy_code, buy_code) if is_crypto_buy else all_a.get(buy_code, buy_code)
        market_label_buy = "加密货币" if is_crypto_buy else "A股"

        cur_price = None
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
#  Tab 4: 自选管理
# ============================================================
with tabs[3]:
    st.subheader("📋 当前自选")
    all_a, all_crypto = get_all_stocks()

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
        st.markdown("**➕ 搜索添加A股**")
        a_keyword = st.text_input("输入股票代码或名称", placeholder="如 002226 或 江南", key="a_search_kw")
        if st.button("🔍 搜索A股", key="a_search_btn"):
            if a_keyword.strip():
                with st.spinner("搜索中..."):
                    search_results = search_a_stock(a_keyword.strip())
                if search_results:
                    st.session_state["a_search_results"] = search_results
                else:
                    st.warning("未找到匹配的股票")
                    st.session_state.pop("a_search_results", None)

        if "a_search_results" in st.session_state and st.session_state["a_search_results"]:
            st.markdown("**搜索结果：**")
            for item in st.session_state["a_search_results"]:
                c = item["code"]
                n = item["name"]
                already = c in all_a
                col_info, col_btn = st.columns([4, 1])
                with col_info:
                    tag = " ✅已添加" if already else ""
                    st.markdown(f"**{n}** `{c}`{tag}")
                with col_btn:
                    if already:
                        st.markdown("已存在")
                    else:
                        if st.button("添加", key=f"add_a_{c}"):
                            with st.spinner(f"验证 {n} 数据..."):
                                df = fetch_a_stock(c, 30)
                            if df is not None and len(df) >= 30:
                                add_stock("A股", c, n)
                                st.success(f"✅ 已添加 **{n}**（{c}）")
                                st.session_state.pop("a_search_results", None)
                                st.rerun()
                            else:
                                st.error("❌ 无法获取该股票数据")

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
        st.markdown("**➕ 搜索添加加密货币**")
        c_keyword = st.text_input("输入币种符号或名称", placeholder="如 BTC 或 比特币", key="c_search_kw")
        if st.button("🔍 搜索加密货币", key="c_search_btn"):
            if c_keyword.strip():
                search_results = search_crypto(c_keyword.strip())
                if search_results:
                    st.session_state["c_search_results"] = search_results
                else:
                    st.warning("未找到匹配的币种")
                    st.session_state.pop("c_search_results", None)

        if "c_search_results" in st.session_state and st.session_state["c_search_results"]:
            st.markdown("**搜索结果：**")
            for item in st.session_state["c_search_results"]:
                c = item["code"]
                n = item["name"]
                already = c in all_crypto
                col_info, col_btn = st.columns([4, 1])
                with col_info:
                    tag = " ✅已添加" if already else ""
                    st.markdown(f"**{n}** `{c}`{tag}")
                with col_btn:
                    if already:
                        st.markdown("已存在")
                    else:
                        if st.button("添加", key=f"add_c_{c.replace('/', '_')}"):
                            with st.spinner(f"验证 {n} 数据..."):
                                df = fetch_crypto(c, 30)
                            if df is not None and len(df) >= 30:
                                add_stock("加密货币", c, n)
                                st.success(f"✅ 已添加 **{n}**（{c}）")
                                st.session_state.pop("c_search_results", None)
                                st.rerun()
                            else:
                                st.error("❌ 无法获取该交易对数据")

    st.markdown("---")
    if st.button("🔄 恢复默认自选列表"):
        st.session_state[STOCKS_KEY] = _default_stocks()
        st.success("已恢复默认列表")
        st.rerun()


# ============================================================
#  Tab 5: 策略设置（含小白友好注解）
# ============================================================
with tabs[4]:
    st.subheader("🎛️ 策略权重设置")
    st.caption("调整各策略对评分的影响力度。权重越大，该策略对最终评分影响越大。设为0则忽略该策略。")

    weights = {}
    for k, default_v in STRATEGY_WEIGHTS.items():
        info = STRATEGY_INFO.get(k, {})
        name = info.get("weight_key", k)
        explain = info.get("explain", "")
        params_desc = info.get("params", "")

        with st.container():
            col_slider, col_info = st.columns([3, 2])
            with col_slider:
                weights[k] = st.slider(
                    name, 0.0, 3.0, default_v, 0.1,
                    key=f"w_{k}",
                    help=f"{params_desc}",
                )
            with col_info:
                st.caption(f"💡 {explain}")

    # 保存权重到session_state
    st.session_state["custom_weights"] = weights

    st.markdown("---")
    st.subheader("📖 策略速查手册")
    for k, info in STRATEGY_INFO.items():
        with st.expander(f"{info.get('name', k)} — {info.get('params', '')}"):
            st.write(info.get("explain", ""))

    st.markdown("---")
    st.caption("⚠️ 所有策略仅供参考，不构成投资建议。投资有风险，决策需谨慎。")
