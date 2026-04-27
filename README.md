# Polymarket Copy-Trading Bot

Automatically mirrors trades made by wallet **`0x8d1d5d1c6041b13fc708b5d9f668070e1724ed4a`** with a fixed **$12 budget** per trade.

---

## How It Works

1. **Polls** the Polymarket Data API every 15 seconds for new activity from the target wallet.  
2. **Detects** any new trades not seen before (first run seeds the seen-set to avoid replaying history).  
3. **Scales** your $12 budget proportionally to the target's trade size (capped at $12).  
4. **Places** a matching market order on your Polymarket account (when `DRY_RUN=false`).  
5. **Logs** every action to `logs/bot.log` and `logs/trades.jsonl`.

---

## Target Wallet Analysis

Before running, use the analyzer to understand how this trader behaves:

```bash
python src/analyze_wallet.py
```

This prints:
- Total trade volume & trade count
- Average / min / max trade sizes
- Buy vs Sell split
- Top markets traded
- Suggested copy-trade sizing ratio

---

## Quick Start

### 1. Install Python dependencies

```bash
pip install -r requirements.txt
```

For **live trading**, also install the Polymarket SDK:

```bash
pip install py-clob-client-v2
```

### 2. Configure your environment

```bash
cp config/.env.example .env
```

Open `.env` and fill in:

| Variable | Description |
|---|---|
| `TARGET_ADDRESS` | Wallet to follow (pre-filled) |
| `BUDGET_USD` | Your budget per trade (default `12`) |
| `POLL_INTERVAL` | Seconds between checks (default `15`) |
| `DRY_RUN` | `true` = simulate only, `false` = live trades |
| `PRIVATE_KEY` | Your Polymarket proxy wallet private key |
| `FUNDER_ADDRESS` | Your proxy wallet address |
| `SIGNATURE_TYPE` | `1` = Magic Link, `2` = MetaMask/Rabby (default `2`) |

> ⚠️ **Keep your `.env` file private. Never commit it to git.**

### 3. Run the bot

```bash
# Dry-run mode (safe, no real money)
python src/bot.py

# Live mode — edit .env first: DRY_RUN=false
python src/bot.py
```

### 4. View your trade log

```bash
python src/view_trades.py
```

---

## Sizing Logic

The bot scales your $12 proportionally to the target's trade size:

```
ratio    = min($12 / target_size, 1.0)
our_size = $12 × ratio
```

Example:
- Target trades **$120** → you deploy **$12** (ratio 10%)
- Target trades **$8** → you deploy **$8** (ratio 100%, capped at their size)
- Minimum enforced: **$1.00**

---

## Files

```
polymarket-copybot/
├── src/
│   ├── bot.py              ← Main polling & copy-trade engine
│   ├── analyze_wallet.py   ← Standalone wallet analyzer
│   └── view_trades.py      ← Pretty-print trade log
├── config/
│   └── .env.example        ← Environment template
├── logs/
│   ├── bot.log             ← Full runtime log (created on first run)
│   └── trades.jsonl        ← One JSON record per copied trade
├── requirements.txt
└── README.md
```

---

## How to Get Your Private Key & Proxy Address

1. Log in to [polymarket.com](https://polymarket.com)
2. Click your profile icon → **Settings**
3. Under **Export Private Key**, export it (**MetaMask / Rabby** accounts use `SIGNATURE_TYPE=2`; **Magic Link** accounts use `SIGNATURE_TYPE=1`)
4. Your **proxy wallet address** appears in the profile dropdown — it starts with `0x` and is different from your main wallet

---

## ⚠️ Risks & Disclaimers

- **Copy-trading does not guarantee profits.** Past performance of any trader is not indicative of future results.
- Polymarket is a **prediction market**. All positions can go to zero.
- This bot is provided for **educational purposes only**. Use at your own risk.
- You are responsible for complying with Polymarket's [Terms of Service](https://polymarket.com/tos) and the laws of your jurisdiction.
- Polymarket is **geo-blocked** in several countries. Check [docs.polymarket.com/api-reference/geoblock](https://docs.polymarket.com/api-reference/geoblock).

---

## Troubleshooting

| Issue | Fix |
|---|---|
| `No trade data found` | The target may be inactive; check the address on polymarket.com |
| `py-clob-client-v2 not installed` | Run `pip install py-clob-client-v2` |
| `No PRIVATE_KEY set` | Add your key to `.env` and set `DRY_RUN=false` |
| Orders failing | Ensure your proxy wallet has USDC deposited and `FUNDER_ADDRESS` is correct |

---

## Running Continuously (Linux / macOS)

```bash
# Run in background with nohup
nohup python src/bot.py > logs/nohup.out 2>&1 &

# Or with screen
screen -S copybot
python src/bot.py
# Ctrl+A then D to detach
```
