"""
🐸 模拟交易组合管理
支持虚拟买入/卖出、持仓追踪、收益统计
数据持久化到 portfolio.json
"""

import os
import json
from datetime import datetime

import pandas as pd

PORTFOLIO_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "portfolio.json")


def _default_portfolio():
    return {
        "cash": 1000000.0,       # 初始100万
        "positions": {},          # symbol -> {name, market, shares, avg_cost, buy_time, buy_price}
        "history": [],            # 交易记录
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


def load_portfolio():
    if os.path.exists(PORTFOLIO_FILE):
        with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return _default_portfolio()


def save_portfolio(pf):
    with open(PORTFOLIO_FILE, "w", encoding="utf-8") as f:
        json.dump(pf, f, ensure_ascii=False, indent=2)


def reset_portfolio():
    pf = _default_portfolio()
    save_portfolio(pf)
    return pf


def buy(pf, symbol, name, market, price, amount=None):
    """买入，amount=股数/数量，不传则用可用资金的1/4"""
    if amount is None:
        if market == "加密货币":
            amount = round(pf["cash"] / 4 / price, 4)
            if amount < 0.0001:
                return pf, False, "资金不足"
        else:
            amount = int(pf["cash"] / 4 / price / 100) * 100
            if amount == 0:
                amount = 100

    cost = price * amount
    if cost > pf["cash"]:
        if market == "加密货币":
            amount = round(pf["cash"] / price, 4)
        else:
            amount = int(pf["cash"] / price / 100) * 100
        if amount == 0:
            return pf, False, "资金不足"
        cost = price * amount

    pf["cash"] -= cost
    if symbol in pf["positions"]:
        pos = pf["positions"][symbol]
        total_shares = pos["shares"] + amount
        pos["avg_cost"] = (pos["avg_cost"] * pos["shares"] + cost) / total_shares
        pos["shares"] = total_shares
    else:
        pf["positions"][symbol] = {
            "name": name,
            "market": market,
            "shares": amount,
            "avg_cost": round(price, 3),
            "buy_time": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "buy_price": round(price, 3),
        }

    pf["history"].append({
        "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "action": "买入",
        "symbol": symbol,
        "name": name,
        "price": round(price, 3),
        "amount": amount,
        "cost": round(cost, 2),
    })
    save_portfolio(pf)
    return pf, True, f"买入 {name}({symbol}) {amount}股 @ {price:.3f}，花费 {cost:.2f}"


def sell(pf, symbol, price, amount=None):
    """卖出，amount不传则清仓"""
    if symbol not in pf["positions"]:
        return pf, False, "未持有该标的"

    pos = pf["positions"][symbol]
    if amount is None or amount >= pos["shares"]:
        amount = pos["shares"]

    revenue = price * amount
    profit = (price - pos["avg_cost"]) * amount
    profit_pct = (price / pos["avg_cost"] - 1) * 100

    pf["cash"] += revenue
    pos["shares"] -= amount
    if pos["shares"] <= 0:
        del pf["positions"][symbol]

    pf["history"].append({
        "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "action": "卖出",
        "symbol": symbol,
        "name": pos["name"],
        "price": round(price, 3),
        "amount": amount,
        "revenue": round(revenue, 2),
        "profit": round(profit, 2),
        "profit_pct": round(profit_pct, 2),
    })
    save_portfolio(pf)
    msg = f"卖出 {pos['name']}({symbol}) {amount}股 @ {price:.3f}，收入 {revenue:.2f}，盈亏 {profit:+.2f}({profit_pct:+.1f}%)"
    return pf, True, msg


def get_portfolio_summary(pf, current_prices=None):
    """组合概览"""
    current_prices = current_prices or {}
    total_cost = 0
    total_value = 0
    positions_list = []

    for symbol, pos in pf["positions"].items():
        cost_val = pos["avg_cost"] * pos["shares"]
        cur_price = current_prices.get(symbol, pos["avg_cost"])
        cur_val = cur_price * pos["shares"]
        profit = cur_val - cost_val
        profit_pct = (cur_price / pos["avg_cost"] - 1) * 100

        total_cost += cost_val
        total_value += cur_val

        positions_list.append({
            "代码": symbol,
            "名称": pos["name"],
            "市场": pos["market"],
            "持仓": pos["shares"],
            "成本价": round(pos["avg_cost"], 3),
            "现价": round(cur_price, 3),
            "市值": round(cur_val, 2),
            "盈亏": round(profit, 2),
            "盈亏%": f"{profit_pct:+.1f}%",
            "买入时间": pos["buy_time"],
        })

    total_assets = pf["cash"] + total_value
    initial = 1000000.0
    total_profit = total_assets - initial
    total_profit_pct = (total_assets / initial - 1) * 100

    return {
        "总资产": round(total_assets, 2),
        "现金": round(pf["cash"], 2),
        "持仓市值": round(total_value, 2),
        "总盈亏": round(total_profit, 2),
        "总收益率": f"{total_profit_pct:+.2f}%",
        "持仓数": len(pf["positions"]),
        "positions": positions_list,
    }
