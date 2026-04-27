"""
Polymarket Copy Trading Bot
Monitors a target wallet and mirrors their trades with a fixed $12 budget.
"""

import os
import time
import json
import logging
import asyncio
import aiohttp
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

# ─── Logging ────────────────────────────────────────────────────────────────
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("logs/bot.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# ─── Config ─────────────────────────────────────────────────────────────────
target_addresses_str = os.getenv("TARGET_ADDRESSES", "0x8d1d5d1c6041b13fc708b5d9f668070e1724ed4a")
TARGET_ADDRESSES = [addr.strip().lower() for addr in target_addresses_str.split(",") if addr.strip()]
TARGET_ADDRESS = TARGET_ADDRESSES[0]  # For backward compatibility

TOTAL_BUDGET_USD = Decimal(os.getenv("BUDGET_USD", "12"))
BUDGET_PER_TRADER_USD = Decimal(os.getenv("BUDGET_PER_TRADER", "0"))

if BUDGET_PER_TRADER_USD > 0:
    BUDGET_USD = BUDGET_PER_TRADER_USD
else:
    BUDGET_USD = TOTAL_BUDGET_USD / len(TARGET_ADDRESSES) if TARGET_ADDRESSES else TOTAL_BUDGET_USD

POLL_INTERVAL   = int(os.getenv("POLL_INTERVAL",   "15"))
DRY_RUN         = os.getenv("DRY_RUN", "true").lower() == "true" # set false to live-trade
PRIVATE_KEY     = os.getenv("PRIVATE_KEY",    "")
FUNDER_ADDRESS  = os.getenv("FUNDER_ADDRESS", "")
SIGNATURE_TYPE  = int(os.getenv("SIGNATURE_TYPE", "2"))          # 2 = GNOSIS_SAFE

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_ENABLED  = os.getenv("TELEGRAM_ENABLED", "false").lower() == "true"

API_KEY         = os.getenv("API_KEY", "")
API_SECRET     = os.getenv("API_SECRET", "")
API_PASSPHRASE = os.getenv("API_PASSPHRASE", "")

CLOB_HOST       = "https://clob.polymarket.com"
GAMMA_HOST      = "https://gamma-api.polymarket.com"
DATA_HOST       = "https://data-api.polymarket.com"

# ─── State ───────────────────────────────────────────────────────────────────
seen_trade_ids: set[str] = set()
open_positions: dict[str, dict] = {}

def load_positions() -> dict:
    try:
        with open("logs/positions.json", "r") as f:
            return json.load(f)
    except:
        return {}

def save_positions(positions: dict) -> None:
    with open("logs/positions.json", "w") as f:
        json.dump(positions, f)

# ─── Telegram Notifications ─────────────────────────────────────────────────
async def send_telegram_message(message: str) -> bool:
    if not TELEGRAM_ENABLED:
        logger.warning("Telegram disabled, skipping notification")
        return False
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set")
        return False
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
    
    for attempt in range(3):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        logger.info(f"Telegram sent successfully")
                        return True
                    elif resp.status == 429:
                        wait_time = 2 ** attempt
                        logger.warning(f"Telegram rate limited, waiting {wait_time}s...")
                        await asyncio.sleep(wait_time)
                        continue
                    else:
                        logger.warning(f"Telegram response: {resp.status}")
                        return False
        except Exception as e:
            logger.error("Telegram send error: %s", e)
            await asyncio.sleep(1)
    return False


# ─── Helpers ─────────────────────────────────────────────────────────────────
async def fetch_json(session: aiohttp.ClientSession, url: str, params: dict = None) -> Optional[dict | list]:
    try:
        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 200:
                return await resp.json()
            logger.warning("HTTP %s fetching %s", resp.status, url)
    except Exception as e:
        logger.error("fetch_json error: %s — %s", url, e)
    return None


def ratio_for_budget(trade_size_usd: float, budget: Decimal) -> Decimal:
    """Compute the fraction of our budget to deploy, capped at 100 %."""
    if trade_size_usd <= 0:
        return Decimal("0")
    ratio = budget / Decimal(str(trade_size_usd))
    return min(ratio, Decimal("1")).quantize(Decimal("0.0001"), rounding=ROUND_DOWN)


# ─── Trade Detection ─────────────────────────────────────────────────────────
async def fetch_recent_trades(session: aiohttp.ClientSession, target_address: str = None) -> list[dict]:
    """
    Pull recent trades for a target address from the Polymarket Data API.
    Endpoint: GET /activity?user=<address>&limit=20
    """
    if target_address is None:
        target_address = TARGET_ADDRESS
    url = f"{DATA_HOST}/activity"
    params = {"user": target_address, "limit": "20"}
    data = await fetch_json(session, url, params)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("data", data.get("trades", []))
    return []


async def fetch_all_traders_trades(session: aiohttp.ClientSession) -> list[dict]:
    """Fetch trades from all target traders."""
    all_trades = []
    for addr in TARGET_ADDRESSES:
        trades = await fetch_recent_trades(session, addr)
        for t in trades:
            t["source_wallet"] = addr  # Tag the trade with source wallet
        all_trades.extend(trades)
    return all_trades


# ─── Market Info ─────────────────────────────────────────────────────────────
async def get_market_info(session: aiohttp.ClientSession, condition_id: str) -> Optional[dict]:
    url = f"{GAMMA_HOST}/markets/{condition_id}"
    return await fetch_json(session, url)


# ─── Order Placement (live) ───────────────────────────────────────────────────
async def place_copy_order(session: aiohttp.ClientSession, trade: dict, our_size: Decimal) -> bool:
    """
    Place a market order mirroring the target's trade.
    Requires py-clob-client-v2 and valid credentials in .env.
    """
    try:
        from py_clob_client.client import ClobClient
        from py_clob_client.clob_types import OrderArgs

        client = ClobClient(
            host=CLOB_HOST,
            chain_id=137,
            key=PRIVATE_KEY,
            signature_type=SIGNATURE_TYPE,
            funder=FUNDER_ADDRESS,
        )

        if API_KEY and API_SECRET and API_PASSPHRASE:
            from py_clob_client.clob_types import ApiCreds
            creds = ApiCreds(api_key=API_KEY, api_secret=API_SECRET, api_passphrase=API_PASSPHRASE)
            client.set_api_creds(creds)

        token_id = trade.get("asset")
        side    = trade.get("side", "BUY").upper()
        trade_price = trade.get("price", 0.5)
        
        order_args = OrderArgs(
            token_id=str(token_id),
            price=trade_price,
            size=float(our_size),
            side=side,
        )

        resp = client.create_and_post_order(order_args)
        logger.info("Order posted: %s", resp)
        return True

    except ImportError:
        logger.error("py-clob-client-v2 not installed. Run: pip install py-clob-client-v2")
        return False
    except Exception as e:
        logger.error("Order placement failed: %s", e)
        return False


# ─── Core Copy Logic ─────────────────────────────────────────────────────────
async def process_new_trade(session: aiohttp.ClientSession, trade: dict) -> None:
    trade_type = trade.get("type", "")
    if trade_type != "TRADE":
        return
        
    trade_id    = trade.get("id") or trade.get("transaction_hash") or str(trade)
    market_id   = trade.get("condition_id") or trade.get("market")
    side        = trade.get("side", "?").upper()
    price       = float(trade.get("price") or trade.get("avg_price") or 0)
    size_usd    = float(trade.get("usdcSize", 0))
    outcome     = trade.get("outcome") or trade.get("outcome_index") or "?"
    timestamp   = trade.get("timestamp") or trade.get("created_at") or ""
    market_title = trade.get("title", "") or trade.get("slug", "") or market_id or ""
    source_wallet = trade.get("source_wallet", TARGET_ADDRESS)
    
    source_short = f"{source_wallet[:6]}...{source_wallet[-4:]}"
    title_short = market_title[:50] + "..." if len(market_title) > 50 else market_title

    asset_id = trade.get("asset")
    
    if side == "SELL":
        if asset_id in open_positions and open_positions[asset_id].get("size", 0) > 0:
            our_size = Decimal(str(open_positions[asset_id].get("size", 0)))
            logger.info("Closing position for %s", asset_id)
        else:
            logger.info("No position to close for %s, skipping", asset_id)
            return
    else:
        our_size = Decimal(str(BUDGET_USD))

    logger.info(
        "[%s] New trade detected!\n"
        "   Trade ID   : %s\n"
        "   Market     : %s\n"
        "   Side      : %s\n"
        "   Outcome   : %s\n"
        "   Price     : $%.4f\n"
        "   Target    : $%.2f\n"
        "   Our Size  : $%.2f (budget $%s)\n",
        source_short, trade_id, market_id, side, outcome,
        price, size_usd, float(our_size), BUDGET_USD,
    )

    telegram_msg = (
        f"🔔 <b>New Trading Signal!</b>\n\n"
        f"👤 <b>Trader:</b> <code>{source_short}</code>\n"
        f"📌 <b>Market:</b> {title_short}\n"
        f"📊 <b>Side:</b> {side}\n"
        f"🎯 <b>Outcome:</b> {outcome}\n"
        f"💰 <b>Price:</b> ${price:.4f}\n"
        f"💵 <b>Target Size:</b> ${size_usd:.2f}\n"
        f"💵 <b>Your Size:</b> ${float(our_size):.2f}\n"
    )
    await send_telegram_message(telegram_msg)

    if DRY_RUN:
        logger.info("💤 DRY RUN — skipping live order. Set DRY_RUN=false to trade.")
        return

    if not PRIVATE_KEY:
        logger.warning("⚠️  No PRIVATE_KEY set. Cannot place live orders.")
        return

    if float(our_size) < 5.0:
        logger.warning("Trade size $%.2f too small (min $5), skipping.", float(our_size))
        return

    success = await place_copy_order(session, trade, our_size)
    status  = "✅ placed" if success else "❌ failed"
    logger.info("Order status: %s", status)

    if success:
        if side == "BUY":
            open_positions[asset_id] = {"size": float(our_size), "price": price, "market": market_id}
        elif side == "SELL" and asset_id in open_positions:
            del open_positions[asset_id]
        save_positions(open_positions)

    # Persist trade record
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "trade_id": trade_id,
        "market": market_id,
        "side": side,
        "outcome": outcome,
        "price": price,
        "target_size_usd": size_usd,
        "our_size_usd": float(our_size),
        "dry_run": DRY_RUN,
        "order_placed": success,
    }
    with open("logs/trades.jsonl", "a") as f:
        f.write(json.dumps(record) + "\n")


# ─── Main Poll Loop ───────────────────────────────────────────────────────────
async def run_bot() -> None:
    global open_positions
    open_positions = load_positions()
    
    logger.info("=" * 60)
    logger.info("Polymarket Copy Bot starting up")
    logger.info("  Targets : %s", ", ".join([f"{addr[:6]}...{addr[-4:]}" for addr in TARGET_ADDRESSES]))
    logger.info("  Total Budget: $%s (split across %d traders)", TOTAL_BUDGET_USD, len(TARGET_ADDRESSES))
    logger.info("  Per Trader: $%s", BUDGET_USD)
    logger.info("  Poll    : every %ss", POLL_INTERVAL)
    logger.info("  DRY RUN : %s", DRY_RUN)
    logger.info("  Open Positions: %d", len(open_positions))
    logger.info("=" * 60)

    async with aiohttp.ClientSession() as session:
        # Prime the seen-set with current trades so we don't replay history
        logger.info("Fetching existing trades to avoid replaying history...")
        existing = await fetch_all_traders_trades(session)
        for t in existing:
            tid = t.get("id") or t.get("transaction_hash") or str(t)
            seen_trade_ids.add(tid)
        logger.info("  Seeded %d known trade IDs.", len(seen_trade_ids))

        trader_list = ", ".join([f"{addr[:6]}...{addr[-4:]}" for addr in TARGET_ADDRESSES])
        startup_msg = (
            f"✅ <b>Polymarket Copy Bot Started!</b>\n\n"
            f"📌 <b>Targets:</b> {trader_list}\n"
            f"💰 <b>Total Budget:</b> ${TOTAL_BUDGET_USD}\n"
            f"💵 <b>Per Trader:</b> ${BUDGET_USD}\n"
            f"⏱️ <b>Poll:</b> every {POLL_INTERVAL}s\n"
            f"🔄 <b>Mode:</b> {'DRY RUN' if DRY_RUN else 'LIVE'}\n\n"
            f"<i>Watching for new trades...</i>"
        )
        await send_telegram_message(startup_msg)

        while True:
            try:
                trades = await fetch_all_traders_trades(session)
                new_trades = []
                for t in trades:
                    tid = t.get("id") or t.get("transaction_hash") or str(t)
                    if tid not in seen_trade_ids:
                        seen_trade_ids.add(tid)
                        new_trades.append(t)

                if new_trades:
                    logger.info("⚡ %d new trade(s) found for targets.", len(new_trades))
                    for trade in new_trades:
                        await process_new_trade(session, trade)
                else:
                    logger.debug("No new trades. Sleeping %ss…", POLL_INTERVAL)

            except asyncio.CancelledError:
                logger.info("Bot cancelled. Shutting down.")
                break
            except Exception as e:
                logger.error("Unexpected error in poll loop: %s", e, exc_info=True)

            await asyncio.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        logger.info("Interrupted by user. Goodbye.")
