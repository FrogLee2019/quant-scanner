# 🐸 量化信号扫描工具

多策略量化信号扫描，支持 A股 + 加密货币，手机电脑浏览器直接访问。

## 功能

| 功能 | 说明 |
|------|------|
| 📊 信号总览 | 7大策略综合评分，一键扫描全部标的 |
| 📈 个股分析 | K线+均线+RSI图表，任意代码实时分析 |
| 💼 模拟交易 | 100万虚拟资金，买卖持仓盈亏追踪 |
| ⚙️ 自定义标的 | 随时添加A股/加密货币到扫描池 |

## 部署到 Streamlit Community Cloud（免费）

### 前置条件
- 一个 GitHub 账号
- 一个 Streamlit 账号（可以用 GitHub 登录）

### 步骤

1. **创建 GitHub 仓库**
   ```bash
   # 在本地
   mkdir quant-scanner && cd quant-scanner
   # 把 cloud_deploy 里所有文件复制进去
   git init
   git add .
   git commit -m "🐸 量化信号扫描工具"
   git remote add origin https://github.com/你的用户名/quant-scanner.git
   git push -u origin main
   ```

2. **部署到 Streamlit Cloud**
   - 打开 https://streamlit.io/cloud
   - 用 GitHub 登录
   - 点击 "New app"
   - 选择你的仓库 `quant-scanner`
   - Main file path 填 `app.py`
   - 点击 "Deploy"
   - 等几分钟，部署完成后会给你一个 URL

3. **访问**
   - 手机电脑浏览器打开那个 URL 就行了
   - 地址格式: `https://你的应用名.streamlit.app`

### 也可以用其他平台

| 平台 | 免费额度 | 说明 |
|------|---------|------|
| Streamlit Cloud | 完全免费 | 最简单，推荐 |
| Railway | $5/月额度 | Docker部署 |
| Render | 750小时/月 | 需Dockerfile |
| Fly.io | 免费额度 | 需Dockerfile |

## 文件结构

```
├── app.py                    # Streamlit主程序
├── scanner.py                # 扫描引擎
├── config.py                 # 配置（标的/参数/权重）
├── portfolio.py              # 模拟交易模块
├── requirements.txt          # Python依赖
├── .streamlit/config.toml    # Streamlit配置
└── README.md
```

## 免责声明

⚠️ 本工具仅供参考，不构成投资建议。投资有风险，决策需谨慎。
