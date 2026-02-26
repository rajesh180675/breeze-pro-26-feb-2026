# 📈 Breeze Options Trader PRO v10.0

> **Production-grade** ICICI Breeze Options Trading Terminal built with Streamlit.
> Complete end-to-end options trading: market data, execution, risk management, analytics.

---

## 🚀 Quick Start

```bash
# 1. Clone / unzip
unzip breeze_trader_pro_v10.zip && cd breeze_trader_pro

# 2. Setup (installs deps, creates dirs)
chmod +x setup.sh && ./setup.sh

# 3. Add credentials
nano .streamlit/secrets.toml

# 4. Launch
./run.sh
```

Open `http://localhost:8501` → enter daily session token → trade!

---

## ✨ What's New in v10.0

| Feature | v8 (Original) | v10 PRO |
|---------|--------------|---------|
| Pages | 9 | 11 |
| Strategies | 7 | 15+ |
| Auto-refresh | ❌ | ✅ Configurable |
| IV Smile | ❌ | ✅ |
| Stress Test | ❌ | ✅ |
| Bulk Square-Off | ❌ | ✅ |
| Watchlist | ❌ | ✅ Persistent |
| P&L History | ❌ | ✅ 90-day chart |
| Export | ❌ | ✅ CSV + Excel |
| Portfolio Greeks | Basic | ✅ Full aggregation |
| Portfolio Stop | ❌ | ✅ |
| Settings Page | ❌ | ✅ |
| Auto Stop-Loss on Sell | ❌ | ✅ |
| Dark Mode | ❌ | ✅ |
| Payoff Diagram | Basic | ✅ Plotly interactive |

---

## 📋 Pages

| Page | Description |
|------|-------------|
| 🏠 Dashboard | Account overview, positions, P&L, quick actions |
| 📊 Option Chain | Live chain, Greeks, PCR, IV smile, OI charts |
| 💰 Sell Options | Place sell orders with auto stop-loss setup |
| 🔄 Square Off | Individual or bulk square-off with P&L display |
| 📋 Orders & Trades | Live orders, trades, persistent history, export |
| 📍 Positions | Current positions with real-time P&L |
| 🎯 Strategy Builder | 15+ templates + custom legs + payoff diagrams |
| 📈 Analytics | Greeks, margin, performance, stress test |
| 🛡️ Risk Monitor | Fixed/trailing stops + portfolio-level limits |
| 👁️ Watchlist | Track options with live quote updates |
| ⚙️ Settings | Trading preferences, risk limits, DB management |

---

## 🎯 Strategy Templates (15+)

**Neutral Sell** (Premium Collection):
- Short Straddle, Short Strangle
- Iron Condor, Wide Iron Condor, Iron Butterfly

**Directional Buy**:
- Bull Call Spread, Bull Put Spread, Long Call
- Bear Put Spread, Bear Call Spread, Long Put

**Volatile**:
- Long Straddle, Long Strangle

**Advanced**:
- Jade Lizard, Broken Wing Butterfly, Ratio Put Spread

---

## 🛡️ Risk Management Features

- **Per-position stops**: Fixed price or trailing % stop-losses
- **Auto stop-loss**: Set automatically when placing sell orders
- **Portfolio limit**: Alert + trigger when total loss exceeds limit
- **Margin monitoring**: Warnings at 75%, critical at 90%
- **Expiry alerts**: Day-before and same-day warnings
- **Stress testing**: P&L under various spot & IV scenarios

---

## 📁 Project Structure

```
breeze_trader_pro/
├── app.py                  # Main Streamlit app (11 pages)
├── app_config.py           # Instruments, constants, expiry logic
├── breeze_api.py           # ICICI Breeze API client (retry, rate-limit)
├── helpers.py              # Utilities, formatting, chain processing
├── analytics.py            # Black-Scholes, Greeks, IV, portfolio math
├── strategies.py           # 15+ strategies, payoff diagrams
├── risk_monitor.py         # Background stop-loss daemon
├── persistence.py          # SQLite: trades, watchlist, alerts, settings
├── session_manager.py      # Session, credentials, caching
├── validators.py           # Pydantic v2 validation
├── requirements.txt        # Dependencies
├── setup.sh / setup.bat    # One-click setup
├── run.sh / run.bat        # Launch scripts
├── .streamlit/
│   ├── config.toml         # Dark theme + server config
│   └── secrets.toml        # API credentials (gitignored)
├── data/                   # SQLite DB (auto-created)
└── logs/                   # App logs (auto-created)
```

---

## 🔑 Credentials Setup

### Option A: Streamlit Secrets (Recommended)
```toml
# .streamlit/secrets.toml
BREEZE_API_KEY = "your_key"
BREEZE_API_SECRET = "your_secret"
```

### Option B: Environment Variables
```bash
export BREEZE_API_KEY=your_key
export BREEZE_API_SECRET=your_secret
```

### Option C: Manual Entry
Enter credentials directly in the login form on first run.

---

## 🔄 Daily Workflow

1. Login to [ICICI Breeze portal](https://api.icicidirect.com/) → get session token
2. Open the app → paste token → Connect
3. Check Dashboard for positions & funds
4. Use Option Chain to find strikes
5. Sell Options with auto stop-loss
6. Monitor in Risk Monitor page
7. Square off positions as needed

---

## ⚠️ Risk Disclaimer

This terminal is for educational/research purposes. Option selling carries **unlimited risk**.
Always use stop-losses. Never risk more than you can afford to lose.

---

## 📜 License

MIT License — Use at your own risk.
