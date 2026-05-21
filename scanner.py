"""
🐸 多策略量化信号扫描工具
支持 A股 + 加密货币
策略：均线交叉、RSI、布林带、MACD、成交量异动、动量、历史位置
"""

import os
import sys
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd


# ============================================================
#  数据获取
# ============================================================

def _symbol_to_baostock(symbol):
    """A股代码转baostock格式: 600519->sh.600519, 000001->sz.000001, 512710->sh.512710"""
    if symbol.startswith("6") or symbol.startswith("51"):
        return f"sh.{symbol}"
    else:
        return f"sz.{symbol}"


def fetch_a_stock(symbol, days=120):
    """获取A股日线数据（前复权）— baostock优先，akshare备选"""
    import baostock as bs
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=days * 2)).strftime("%Y-%m-%d")
    bs_symbol = _symbol_to_baostock(symbol)

    # 尝试 baostock
    try:
        import io, contextlib
        with contextlib.redirect_stdout(io.StringIO()):
            bs.login()
        rs = bs.query_history_k_data_plus(
            bs_symbol,
            "date,open,high,low,close,volume",
            start_date=start_date, end_date=end_date,
            frequency="d", adjustflag="2"
        )
        rows = []
        while (rs.error_code == "0") and rs.next():
            rows.append(rs.get_row_data())
        with contextlib.redirect_stdout(io.StringIO()):
            bs.logout()
        if rows and len(rows) >= 30:
            df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date")
            for col in ["open", "high", "low", "close", "volume"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            df = df.dropna(subset=["close"])
            return df.tail(days)
    except Exception:
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                bs.logout()
        except Exception:
            pass

    # 备选 akshare（加重试）
    import akshare as ak
    for attempt in range(3):
        try:
            df = ak.stock_zh_a_hist(
                symbol=symbol, period="daily",
                start_date=start_date.replace("-", ""),
                end_date=end_date.replace("-", ""),
                adjust="qfq"
            )
            df = df.rename(columns={
                "日期": "date", "开盘": "open", "收盘": "close",
                "最高": "high", "最低": "low", "成交量": "volume"
            })
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date")
            df = df[["open", "high", "low", "close", "volume"]].astype(float)
            return df.tail(days)
        except Exception:
            import time
            time.sleep(2)

    print(f"  [ERROR] A股 {symbol}: 所有数据源均失败")
    return None


def fetch_crypto(symbol, days=120):
    """获取加密货币日线数据（Gate优先，Huobi备选）"""
    import ccxt
    for exchange_name in ["gate", "huobi"]:
        try:
            exchange = getattr(ccxt, exchange_name)({"timeout": 30000})
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe="1d", limit=days)
            if ohlcv and len(ohlcv) >= 30:
                df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
                df["date"] = pd.to_datetime(df["timestamp"], unit="ms")
                df = df.set_index("date")
                df = df[["open", "high", "low", "close", "volume"]]
                return df
        except Exception:
            continue
    print(f"  [ERROR] 加密货币 {symbol}: 所有数据源均失败")
    return None


# ============================================================
#  策略实现 — 每个返回 (score, detail)
#  score: -1~1 (负=看空，正=看多)，detail: 文字说明
# ============================================================

def strategy_ma_cross(df, params):
    """双均线交叉"""
    fast = df["close"].rolling(params["ma_fast"]).mean()
    slow = df["close"].rolling(params["ma_slow"]).mean()
    if pd.isna(fast.iloc[-1]) or pd.isna(slow.iloc[-1]):
        return 0, "数据不足"
    if fast.iloc[-1] > slow.iloc[-1] and fast.iloc[-2] <= slow.iloc[-2]:
        return 1, "金叉买入"
    elif fast.iloc[-1] < slow.iloc[-1] and fast.iloc[-2] >= slow.iloc[-2]:
        return -1, "死叉卖出"
    elif fast.iloc[-1] > slow.iloc[-1]:
        return 0.3, "均线多头排列"
    else:
        return -0.3, "均线空头排列"


def strategy_rsi(df, params):
    """RSI超买超卖"""
    delta = df["close"].diff()
    gain = delta.where(delta > 0, 0).rolling(params["rsi_period"]).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(params["rsi_period"]).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    cur = rsi.iloc[-1]
    if pd.isna(cur):
        return 0, "数据不足"
    cur = round(cur, 1)
    if cur < params["rsi_oversold"]:
        return 1, f"RSI={cur} 超卖"
    elif cur > params["rsi_overbought"]:
        return -1, f"RSI={cur} 超买"
    elif cur < 50:
        return 0.2, f"RSI={cur} 偏弱"
    else:
        return -0.2, f"RSI={cur} 偏强"


def strategy_bollinger(df, params):
    """布林带"""
    ma = df["close"].rolling(params["bb_period"]).mean()
    std = df["close"].rolling(params["bb_period"]).std()
    upper = ma + params["bb_std"] * std
    lower = ma - params["bb_std"] * std
    c = df["close"].iloc[-1]
    if pd.isna(upper.iloc[-1]):
        return 0, "数据不足"
    if c < lower.iloc[-1]:
        return 1, "触及布林下轨，超卖"
    elif c > upper.iloc[-1]:
        return -0.5, "触及布林上轨，注意回调"
    elif c < ma.iloc[-1]:
        return 0.2, "布林中轨下方"
    else:
        return -0.1, "布林中轨上方"


def strategy_macd(df, params):
    """MACD"""
    ema_fast = df["close"].ewm(span=params["macd_fast"], adjust=False).mean()
    ema_slow = df["close"].ewm(span=params["macd_slow"], adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=params["macd_signal"], adjust=False).mean()
    hist = 2 * (dif - dea)
    if pd.isna(dif.iloc[-1]) or pd.isna(dea.iloc[-1]):
        return 0, "数据不足"
    if dif.iloc[-1] > dea.iloc[-1] and dif.iloc[-2] <= dea.iloc[-2]:
        return 1, "MACD金叉"
    elif dif.iloc[-1] < dea.iloc[-1] and dif.iloc[-2] >= dea.iloc[-2]:
        return -1, "MACD死叉"
    elif hist.iloc[-1] > 0 and hist.iloc[-1] > hist.iloc[-2]:
        return 0.5, "MACD红柱放大"
    elif hist.iloc[-1] < 0 and hist.iloc[-1] < hist.iloc[-2]:
        return -0.5, "MACD绿柱放大"
    elif dif.iloc[-1] > dea.iloc[-1]:
        return 0.2, "MACD多头"
    else:
        return -0.2, "MACD空头"


def strategy_volume(df, params):
    """成交量异动"""
    vol_ma = df["volume"].rolling(params["volume_ma_period"]).mean()
    if vol_ma.iloc[-1] == 0 or pd.isna(vol_ma.iloc[-1]):
        return 0, "成交量数据异常"
    vol_ratio = df["volume"].iloc[-1] / vol_ma.iloc[-1]
    pct = (df["close"].iloc[-1] - df["close"].iloc[-2]) / df["close"].iloc[-2] * 100
    if vol_ratio > params["volume_spike_threshold"] and pct > 0:
        return 0.8, f"放量上涨（量比{vol_ratio:.1f}，涨{pct:.1f}%）"
    elif vol_ratio > params["volume_spike_threshold"] and pct < 0:
        return -0.8, f"放量下跌（量比{vol_ratio:.1f}，跌{pct:.1f}%）"
    elif vol_ratio < 0.5:
        return 0, f"缩量（量比{vol_ratio:.1f}）"
    else:
        return 0, f"量能正常（量比{vol_ratio:.1f}）"


def strategy_momentum(df, params):
    """动量"""
    p = params["momentum_period"]
    if len(df) < p + 1:
        return 0, "数据不足"
    mom = (df["close"].iloc[-1] / df["close"].iloc[-p] - 1) * 100
    if mom > 5:
        return 1, f"强动量上涨（{mom:.1f}%）"
    elif mom > 2:
        return 0.5, f"温和上涨（{mom:.1f}%）"
    elif mom < -5:
        return -1, f"强动量下跌（{mom:.1f}%）"
    elif mom < -2:
        return -0.5, f"温和下跌（{mom:.1f}%）"
    else:
        return 0, f"动量平淡（{mom:.1f}%）"


# ============================================================
#  评分 & 信号
# ============================================================

def strategy_position(df, params):
    """历史位置百分位（近1年），低位反转机会 vs 高位风险"""
    df_1y = df.tail(250)
    if len(df_1y) < 60:
        return 0, "数据不足"
    cur = df["close"].iloc[-1]
    pct = (df_1y["close"] < cur).sum() / len(df_1y) * 100
    pct = round(pct, 1)
    if pct < 10:
        return 0.8, f"1年低位（{pct}%分位），可能底部反转"
    elif pct < 25:
        return 0.5, f"1年偏低（{pct}%分位）"
    elif pct < 50:
        return 0.1, f"1年中低位（{pct}%分位）"
    elif pct < 75:
        return -0.1, f"1年中高位（{pct}%分位）"
    elif pct < 90:
        return -0.5, f"1年偏高（{pct}%分位）"
    else:
        return -0.8, f"1年高位（{pct}%分位），注意回调"


STRATEGIES = {
    "ma_cross": strategy_ma_cross,
    "rsi": strategy_rsi,
    "bollinger": strategy_bollinger,
    "macd": strategy_macd,
    "volume": strategy_volume,
    "momentum": strategy_momentum,
    "position": strategy_position,
}


def compute_score(signals, weights):
    total_w = sum(weights.values())
    weighted = sum(signals.get(k, 0) * weights[k] for k in weights if k in signals)
    return round(weighted / total_w * 100, 1)


def signal_emoji(score):
    if score >= 30:   return "🟢"
    elif score >= 10: return "🟡"
    elif score > -10: return "⚪"
    elif score > -30: return "🟠"
    else:             return "🔴"


def signal_label(score):
    if score >= 30:   return "强烈买入"
    elif score >= 10: return "偏多观望"
    elif score > -10: return "中性观望"
    elif score > -30: return "偏空观望"
    else:             return "强烈卖出"


# ============================================================
#  扫描引擎
# ============================================================

def _scan_one(df, name, symbol, market, params, weights):
    signals, details = {}, {}
    for sname, sfunc in STRATEGIES.items():
        try:
            s, d = sfunc(df, params)
        except Exception:
            s, d = 0, "计算异常"
        signals[sname] = s
        details[sname] = d
    score = compute_score(signals, weights)
    stop = df["low"].tail(20).min()
    price = df["close"].iloc[-1]
    return {
        "market": market, "symbol": symbol, "name": name,
        "price": price, "stop_loss": stop, "score": score,
        "signal": f"{signal_emoji(score)} {signal_label(score)}",
        "signals": signals, "details": details,
    }


def _fetch_and_scan(sym, name, market, params, weights, lookback):
    """单个标的：拉数据 + 扫描，供并发调用"""
    fetch_fn = fetch_crypto if market == "加密货币" else fetch_a_stock
    df = fetch_fn(sym, lookback)
    if df is None or len(df) < 30:
        return None
    return _scan_one(df, name, sym, market, params, weights)


def scan_market(market_type="all", max_workers=8, on_progress=None):
    """并发扫描市场，max_workers 控制并发数
    on_progress: 可选回调 on_progress(completed, total, symbol, name)
    """
    from config import A_STOCKS, CRYPTO, STRATEGY_PARAMS, STRATEGY_WEIGHTS, LOOKBACK_DAYS
    # 加载自定义标的
    custom_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "custom_stocks.json")
    if os.path.exists(custom_file):
        import json
        with open(custom_file, "r", encoding="utf-8") as f:
            custom = json.load(f)
        all_a = {**A_STOCKS, **custom.get("a_stock", {})}
        all_crypto = {**CRYPTO, **custom.get("crypto", {})}
    else:
        all_a = A_STOCKS
        all_crypto = CRYPTO
    results = []

    # 构建任务列表
    tasks = []
    if market_type in ("all", "a_stock"):
        for sym, name in all_a.items():
            tasks.append((sym, name, "A股"))
    if market_type in ("all", "crypto"):
        for sym, name in all_crypto.items():
            tasks.append((sym, name, "加密货币"))

    total = len(tasks)
    if on_progress:
        on_progress(0, total, "", "准备中...")

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {}
        for sym, name, market in tasks:
            f = pool.submit(_fetch_and_scan, sym, name, market, STRATEGY_PARAMS, STRATEGY_WEIGHTS, LOOKBACK_DAYS)
            futures[f] = (sym, name, market)

        completed = 0
        for f in as_completed(futures):
            sym, name, market = futures[f]
            completed += 1
            try:
                r = f.result(timeout=60)
                if r:
                    results.append(r)
            except Exception as e:
                pass
            if on_progress:
                try:
                    on_progress(completed, total, sym, name)
                except Exception:
                    pass

    return results


# ============================================================
#  股票搜索
# ============================================================

def search_a_stock(keyword, limit=20):
    """按代码或名称模糊搜索A股，返回 [{code, name}]"""
    import baostock as bs
    import io, contextlib
    keyword = keyword.strip()
    if not keyword:
        return []

    results = []
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            bs.login()
        rs = bs.query_stock_basic()
        while (rs.error_code == "0") and rs.next():
            row = rs.get_row_data()
            code_raw = row[0]  # sh.600519 或 sz.000001
            name = row[1] if len(row) > 1 else ""
            # 去掉 sh./sz. 前缀
            code = code_raw.split(".")[-1] if "." in code_raw else code_raw
            # 模糊匹配：代码包含关键词 或 名称包含关键词
            if keyword in code or keyword in name:
                results.append({"code": code, "name": name, "full_code": code_raw})
            if len(results) >= limit:
                break
        with contextlib.redirect_stdout(io.StringIO()):
            bs.logout()
    except Exception:
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                bs.logout()
        except Exception:
            pass
    return results


# 常见加密货币映射（用于搜索）
CRYPTO_NAME_MAP = {
    "BTC/USDT": "比特币", "ETH/USDT": "以太坊", "SOL/USDT": "Solana",
    "BNB/USDT": "币安币", "XRP/USDT": "瑞波币", "ADA/USDT": "艾达币",
    "DOGE/USDT": "狗狗币", "AVAX/USDT": "雪崩", "DOT/USDT": "波卡",
    "LINK/USDT": "ChainLink", "MATIC/USDT": "Polygon", "SHIB/USDT": "柴犬币",
    "UNI/USDT": "Uniswap", "LTC/USDT": "莱特币", "ATOM/USDT": "Cosmos",
    "FIL/USDT": "Filecoin", "APT/USDT": "Aptos", "ARB/USDT": "Arbitrum",
    "OP/USDT": "Optimism", "NEAR/USDT": "NEAR", "SUI/USDT": "Sui",
    "TIA/USDT": "Celestia", "SEI/USDT": "Sei", "INJ/USDT": "Injective",
    "FET/USDT": "Fetch.ai", "PEPE/USDT": "Pepe", "WIF/USDT": "dogwifhat",
    "FLOKI/USDT": "FLOKI", "TRX/USDT": "波场", "ETC/USDT": "以太经典",
    "BCH/USDT": "比特币现金", "ALGO/USDT": "Algorand", "VET/USDT": "VeChain",
    "ICP/USDT": "互联网计算机", "HBAR/USDT": "Hedera", "SAND/USDT": "Sandbox",
    "MANA/USDT": "Decentraland", "AAVE/USDT": "Aave", "MKR/USDT": "Maker",
}


def search_crypto(keyword, limit=20):
    """按代码或名称模糊搜索加密货币，返回 [{code, name}]"""
    keyword = keyword.strip().upper()
    if not keyword:
        return []
    results = []
    for pair, name in CRYPTO_NAME_MAP.items():
        # 匹配：币种符号 或 中文名
        base = pair.split("/")[0]  # BTC, ETH等
        if keyword in base or keyword in pair.upper() or keyword in name.upper():
            results.append({"code": pair, "name": name})
        if len(results) >= limit:
            break
    return results


# ============================================================
#  报告生成
# ============================================================

def generate_report(results):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    ranked = sorted(results, key=lambda x: x["score"], reverse=True)
    buy  = [r for r in ranked if r["score"] >= 30]
    sell = [r for r in ranked if r["score"] <= -30]
    mid  = [r for r in ranked if -30 < r["score"] < 30]

    md = f"# 🐸 量化信号扫描报告\n\n**扫描时间：** {now}\n\n"

    # 概览
    md += "## 📊 扫描概览\n\n"
    md += "| 类别 | 数量 |\n|------|------|\n"
    md += f"| 🟢 买入信号 | {len(buy)} |\n| 🔴 卖出信号 | {len(sell)} |\n| ⚪ 观望 | {len(mid)} |\n| 合计 | {len(results)} |\n\n"

    # 买入
    if buy:
        md += "## 🟢 买入信号\n\n"
        for r in buy:
            md += f"### {r['signal']} {r['name']}（{r['symbol']}）— 评分 {r['score']}\n\n"
            md += f"- **现价：** {r['price']:.2f}\n- **建议止损：** {r['stop_loss']:.2f}（近20日最低）\n- **市场：** {r['market']}\n\n**策略详情：**\n\n"
            for k, v in r["details"].items():
                md += f"- {k}: {v}\n"
            md += "\n"

    # 卖出
    if sell:
        md += "## 🔴 卖出信号\n\n"
        for r in sell:
            md += f"### {r['signal']} {r['name']}（{r['symbol']}）— 评分 {r['score']}\n\n"
            md += f"- **现价：** {r['price']:.2f}\n- **市场：** {r['market']}\n\n**策略详情：**\n\n"
            for k, v in r["details"].items():
                md += f"- {k}: {v}\n"
            md += "\n"

    # 全量表
    md += "## 📋 全部标的评分\n\n"
    md += "| 信号 | 市场 | 名称 | 代码 | 评分 | 现价 | 止损位 |\n|------|------|------|------|------|------|--------|\n"
    for r in ranked:
        e = signal_emoji(r["score"])
        md += f"| {e} | {r['market']} | {r['name']} | {r['symbol']} | {r['score']} | {r['price']:.2f} | {r['stop_loss']:.2f} |\n"
    md += "\n---\n\n⚠️ **免责声明：** 本报告仅供参考，不构成投资建议。技术面分析有局限性，历史表现不代表未来收益。投资有风险，决策需谨慎。\n"
    return md


# ============================================================
#  入口
# ============================================================

if __name__ == "__main__":
    market = sys.argv[1] if len(sys.argv) > 1 else "all"
    print("🐸 量化信号扫描工具启动")
    print(f"扫描范围: {market}")

    results = scan_market(market)
    if not results:
        print("❌ 未获取到任何数据")
        sys.exit(1)

    report = generate_report(results)

    report_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports")
    os.makedirs(report_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    path = os.path.join(report_dir, f"scan_{ts}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(report)

    n_buy  = sum(1 for r in results if r["score"] >= 30)
    n_sell = sum(1 for r in results if r["score"] <= -30)
    print(f"\n✅ 报告已保存: {path}")
    print(f"🟢 买入 {n_buy}  🔴 卖出 {n_sell}  ⚪ 观望 {len(results)-n_buy-n_sell}")
