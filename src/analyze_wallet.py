"""
analyze_wallet.py — Analyze historical trades of the target Polymarket address.
Run this standalone to understand the trader's style before enabling the bot.
"""

import asyncio
import aiohttp
import json
from collections import defaultdict
from datetime import datetime, timezone

TARGET = "0x8d1d5d1c6041b13fc708b5d9f668070e1724ed4a"
DATA_HOST  = "https://data-api.polymarket.com"
GAMMA_HOST = "https://gamma-api.polymarket.com"


async def fetch(session, url, params=None):
    async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as r:
        if r.status == 200:
            return await r.json()
        print(f"  HTTP {r.status} — {url}")
        return None


async def analyze():
    async with aiohttp.ClientSession() as session:
        print(f"\n{'='*60}")
        print(f"  Polymarket Wallet Analyzer")
        print(f"  Target: {TARGET}")
        print(f"{'='*60}\n")

        # ── Fetch trade history ──────────────────────────────────────────────
        print("⏳ Fetching trade activity…")
        trades = []
        for limit in [50, 100]:
            raw = await fetch(session, f"{DATA_HOST}/activity",
                              {"user": TARGET, "limit": str(limit)})
            if isinstance(raw, list) and raw:
                trades = raw
                break
            if isinstance(raw, dict):
                trades = raw.get("data", raw.get("trades", []))
                if trades:
                    break

        if not trades:
            print("⚠️  No trade data found via Data API. The address may be inactive or the endpoint changed.")
            print("    Check https://data-api.polymarket.com/activity?user=" + TARGET)
            return

        print(f"✅ Found {len(trades)} trade records.\n")

        # ── Aggregate stats ──────────────────────────────────────────────────
        total_volume   = 0.0
        wins           = 0
        losses         = 0
        markets_traded = defaultdict(int)
        sides          = defaultdict(int)
        sizes          = []
        prices         = []

        for t in trades:
            size  = float(t.get("size")  or t.get("usd_size") or t.get("amount") or 0)
            price = float(t.get("price") or t.get("avg_price") or 0)
            side  = (t.get("side") or "BUY").upper()
            mkt   = t.get("condition_id") or t.get("market") or "unknown"

            total_volume += size
            sizes.append(size)
            if price:
                prices.append(price)
            markets_traded[mkt] += 1
            sides[side] += 1

        avg_size   = sum(sizes) / len(sizes) if sizes else 0
        avg_price  = sum(prices) / len(prices) if prices else 0
        max_size   = max(sizes) if sizes else 0
        min_size   = min(s for s in sizes if s > 0) if sizes else 0

        print("📊  TRADE STATISTICS")
        print(f"  Total trades analyzed : {len(trades)}")
        print(f"  Total volume (USDC)   : ${total_volume:,.2f}")
        print(f"  Avg trade size        : ${avg_size:.2f}")
        print(f"  Largest trade         : ${max_size:.2f}")
        print(f"  Smallest trade        : ${min_size:.2f}")
        print(f"  Avg price (prob)      : {avg_price:.3f}  ({avg_price*100:.1f}%)")
        print(f"  Unique markets        : {len(markets_traded)}")
        print(f"  Buy / Sell split      : {sides.get('BUY',0)} BUY  /  {sides.get('SELL',0)} SELL\n")

        # ── Top markets ───────────────────────────────────────────────────────
        print("🏆  TOP MARKETS (by trade count)")
        top = sorted(markets_traded.items(), key=lambda x: -x[1])[:5]
        for mkt, cnt in top:
            print(f"  [{cnt:>3} trades]  {mkt}")

        # ── Recent trades ─────────────────────────────────────────────────────
        print("\n📋  LAST 5 TRADES")
        for t in trades[:5]:
            side   = (t.get("side") or "?").upper()
            price  = float(t.get("price") or t.get("avg_price") or 0)
            size   = float(t.get("size")  or t.get("usd_size") or t.get("amount") or 0)
            ts     = t.get("timestamp") or t.get("created_at") or "?"
            mkt    = (t.get("condition_id") or t.get("market") or "?")[:20]
            print(f"  {side:<4}  ${size:>8.2f}  @ {price:.4f}  mkt={mkt}…  ts={ts}")

        # ── Copy-trade sizing guidance ─────────────────────────────────────────
        budget = 12.0
        print(f"\n💡  COPY-TRADE SIZING (your budget: ${budget})")
        if avg_size > 0:
            ratio = min(budget / avg_size, 1.0)
            print(f"  Ratio vs avg trade : {ratio:.2%}")
            print(f"  Per-trade deploy   : ${budget * ratio:.2f}")
        else:
            print("  Cannot compute ratio (no trade data).")

        print(f"\n{'='*60}")
        print("  Analysis complete. Configure .env and run bot.py.")
        print(f"{'='*60}\n")


if __name__ == "__main__":
    asyncio.run(analyze())
