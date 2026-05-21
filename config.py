# ===== A股扫描标的 =====
# 注意: ETF在baostock不支持，优先选个股
A_STOCKS = {
    "600519": "贵州茅台",
    "000858": "五粮液",
    "601318": "中国平安",
    "600036": "招商银行",
    "000001": "平安银行",
    "601012": "隆基绿能",
    "300750": "宁德时代",
    "002594": "比亚迪",
    "600900": "长江电力",
    "601899": "紫金矿业",
    "000333": "美的集团",
    "600276": "恒瑞医药",
    "601166": "兴业银行",
    "000651": "格力电器",
    "002475": "立讯精密",
    "600809": "山西汾酒",
    "601888": "中国中免",
    "300059": "东方财富",
    "002226": "江南化工",
    "000768": "中航西飞",
    "300438": "鹏辉能源",
    "512710": "军工龙头ETF",
}

# ===== 加密货币扫描标的 =====
CRYPTO = {
    "BTC/USDT": "比特币",
    "ETH/USDT": "以太坊",
    "SOL/USDT": "Solana",
    "BNB/USDT": "币安币",
    "XRP/USDT": "瑞波币",
    "ADA/USDT": "艾达币",
    "DOGE/USDT": "狗狗币",
}

# ===== 策略参数 =====
STRATEGY_PARAMS = {
    # 均线策略
    "ma_fast": 5,
    "ma_slow": 20,
    # RSI
    "rsi_period": 14,
    "rsi_overbought": 70,
    "rsi_oversold": 30,
    # 布林带
    "bb_period": 20,
    "bb_std": 2.0,
    # MACD
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,
    # 成交量异动
    "volume_ma_period": 20,
    "volume_spike_threshold": 2.0,
    # 动量
    "momentum_period": 10,
}

# ===== 评分权重 =====
STRATEGY_WEIGHTS = {
    "ma_cross": 1.5,
    "rsi": 1.0,
    "bollinger": 1.0,
    "macd": 1.5,
    "volume": 0.8,
    "momentum": 1.2,
    "position": 1.3,
}

# ===== 数据参数 =====
LOOKBACK_DAYS = 120
