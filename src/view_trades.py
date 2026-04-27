"""
view_trades.py — Pretty-print the trade log produced by bot.py
"""

import json, sys
from pathlib import Path

LOG = Path("logs/trades.jsonl")

if not LOG.exists():
    print("No trade log found yet (logs/trades.jsonl).")
    sys.exit(0)

lines = LOG.read_text().strip().splitlines()
if not lines:
    print("Trade log is empty.")
    sys.exit(0)

trades = [json.loads(l) for l in lines]
print(f"\n{'='*70}")
print(f"  Copy-Bot Trade Log  ({len(trades)} records)")
print(f"{'='*70}")
print(f"{'Timestamp':<26} {'Side':<5} {'Market':<22} {'Target$':>8} {'Our$':>7} {'Status'}")
print("-"*70)

for t in trades:
    ts     = t.get("ts","")[:19]
    side   = t.get("side","?")
    mkt    = (t.get("market") or "?")[:20]
    tgt    = f"${t.get('target_size_usd',0):.2f}"
    our    = f"${t.get('our_size_usd',0):.2f}"
    status = "DRY" if t.get("dry_run") else ("✅" if t.get("order_placed") else "❌")
    print(f"{ts:<26} {side:<5} {mkt:<22} {tgt:>8} {our:>7} {status}")

total_deployed = sum(t.get("our_size_usd",0) for t in trades if not t.get("dry_run"))
print("-"*70)
print(f"  Total USDC deployed (live): ${total_deployed:.2f}")
print()
