import logging
import os
import re
import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

# ==============================
# KONFIGURASI
# ==============================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CMC_API_KEY = os.environ.get("CMC_API_KEY", "")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable tidak ditemukan!")
if not CMC_API_KEY:
    raise ValueError("CMC_API_KEY environment variable tidak ditemukan!")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==============================
# COINMARKETCAP API CONFIG
# ==============================
CMC_BASE = "https://pro-api.coinmarketcap.com/v1"

def cmc_get(endpoint: str, params: dict = {}) -> requests.Response:
    return requests.get(
        f"{CMC_BASE}{endpoint}",
        params=params,
        headers={"X-CMC_PRO_API_KEY": CMC_API_KEY, "Accept": "application/json"},
        timeout=10
    )

# ==============================
# SUPPORTED FIAT
# ==============================
SUPPORTED_FIAT = {
    "usd", "idr", "eur", "gbp", "jpy", "sgd", "myr",
    "aud", "cny", "krw", "thb", "php", "vnd", "brl", "inr",
    "chf", "hkd", "twd", "nzd", "rub", "zar", "try",
    "aed", "sar", "mxn", "pkr",
}

FIAT_SYMBOL = {
    "usd": "$", "idr": "Rp ", "eur": "€", "gbp": "£", "jpy": "¥",
    "sgd": "S$", "myr": "RM ", "aud": "A$", "cny": "¥", "krw": "₩",
    "thb": "฿", "php": "₱", "vnd": "₫", "brl": "R$", "inr": "₹",
    "chf": "Fr ", "hkd": "HK$", "twd": "NT$", "nzd": "NZ$",
    "aed": "AED ", "sar": "SAR ", "try": "₺", "rub": "₽", "zar": "R",
}

# ==============================
# COINMARKETCAP: SEARCH + PRICE
# ==============================

def cmc_get_price(symbol: str, fiat: str) -> dict | None:
    """
    Ambil harga langsung dari CMC by symbol.
    CMC otomatis return coin dengan rank tertinggi jika ada duplikat simbol.
    """
    try:
        resp = cmc_get("/cryptocurrency/quotes/latest", {
            "symbol": symbol.upper(),
            "convert": fiat.upper(),
        })
        resp.raise_for_status()
        data = resp.json()

        if data.get("status", {}).get("error_code", 0) != 0:
            logger.error(f"CMC error: {data['status'].get('error_message')}")
            return None

        coin_data = data.get("data", {})
        if not coin_data:
            return None

        # CMC bisa return list jika ada duplikat simbol
        # Ambil coin dengan rank market cap tertinggi (rank terkecil)
        entries = coin_data.get(symbol.upper(), [])
        if isinstance(entries, list):
            entries = sorted(entries, key=lambda x: x.get("cmc_rank") or 999999)
            coin = entries[0]
        elif isinstance(entries, dict):
            coin = entries
        else:
            return None

        quote = coin.get("quote", {}).get(fiat.upper(), {})
        if not quote:
            return None

        return {
            "name": coin.get("name", symbol),
            "symbol": coin.get("symbol", symbol).upper(),
            "price": quote.get("price") or 0,
            "change_24h": quote.get("percent_change_24h") or 0,
            "market_cap": quote.get("market_cap") or 0,
            "volume_24h": quote.get("volume_24h") or 0,
            "rank": coin.get("cmc_rank"),
            "source": "CoinMarketCap",
        }

    except Exception as e:
        logger.error(f"CMC price error for '{symbol}': {e}")
        return None


def cmc_search_by_name(query: str, fiat: str) -> dict | None:
    """
    Fallback: cari coin by nama via /map endpoint jika symbol tidak ketemu.
    """
    try:
        resp = cmc_get("/cryptocurrency/map", {
            "listing_status": "active",
            "sort": "cmc_rank",
            "limit": 5000,
        })
        resp.raise_for_status()
        coins = resp.json().get("data", [])

        q = query.lower()
        # Cari exact match nama dulu
        match = next((c for c in coins if c["name"].lower() == q), None)
        # Jika tidak ada, cari yang mengandung query
        if not match:
            match = next((c for c in coins if q in c["name"].lower()), None)
        if not match:
            return None

        # Sekarang ambil harga menggunakan symbol yang ditemukan
        return cmc_get_price(match["symbol"], fiat)

    except Exception as e:
        logger.error(f"CMC name search error for '{query}': {e}")
        return None


def get_price(query: str, fiat: str) -> dict | None:
    """
    Resolve harga coin dari CoinMarketCap.
    1. Coba by symbol langsung
    2. Fallback by nama
    """
    # Step 1: coba sebagai symbol
    data = cmc_get_price(query, fiat)
    if data:
        return data

    # Step 2: coba sebagai nama (misal: "bitcoin", "ethereum")
    logger.info(f"Symbol lookup miss for '{query}', trying name search...")
    data = cmc_search_by_name(query, fiat)
    if data:
        return data

    return None

# ==============================
# HELPERS
# ==============================

def format_number(n: float, currency: str = "") -> str:
    symbol = FIAT_SYMBOL.get(currency.lower(), currency.upper() + " " if currency else "")
    if n == 0:
        return f"{symbol}0"
    elif n >= 1_000_000_000:
        return f"{symbol}{n:,.2f}"
    elif n >= 1_000:
        return f"{symbol}{n:,.2f}"
    elif n >= 1:
        return f"{symbol}{n:,.4f}"
    elif n >= 0.0001:
        return f"{symbol}{n:.6f}"
    else:
        return f"{symbol}{n:.10f}"

def parse_price_query(text: str):
    """Parse: <jumlah> <coin> [fiat]"""
    text = text.strip().lower()
    pattern = r'^(\d+(?:[.,]\d+)?)\s+([a-z0-9\-]+)(?:\s+([a-z]+))?$'
    match = re.match(pattern, text)
    if not match:
        return None
    amount_str, coin_input, fiat_input = match.groups()
    amount = float(amount_str.replace(",", "."))
    fiat = fiat_input if fiat_input else "usd"
    if fiat not in SUPPORTED_FIAT:
        return None
    if coin_input in SUPPORTED_FIAT:
        return None
    return amount, coin_input, fiat

# ==============================
# CORE HANDLER
# ==============================

async def handle_price_query(update: Update, amount: float, coin_input: str, fiat: str):
    msg = await update.message.reply_text(
        f"🔍 Mencari *{coin_input.upper()}*...", parse_mode="Markdown"
    )

    data = get_price(coin_input, fiat)

    if not data:
        await msg.edit_text(
            f"❌ *{coin_input.upper()}* tidak ditemukan.\n"
            f"Coba gunakan nama lengkap, contoh: `1 bitcoin idr`",
            parse_mode="Markdown"
        )
        return

    price = data["price"]
    total = amount * price
    change_24h = data.get("change_24h") or 0
    market_cap = data.get("market_cap") or 0
    volume_24h = data.get("volume_24h") or 0
    rank = data.get("rank")
    coin_display = data.get("symbol", coin_input.upper())
    coin_name = data.get("name", coin_display)

    change_emoji = "🟢" if change_24h >= 0 else "🔴"
    change_sign = "+" if change_24h >= 0 else ""
    rank_text = f"#{rank}" if rank else "-"

    if amount == 1:
        text = (
            f"💰 *{coin_name} ({coin_display}) / {fiat.upper()}*\n"
            f"🏅 Rank: `{rank_text}`\n\n"
            f"💵 Harga: `{format_number(price, fiat)}`\n"
            f"{change_emoji} 24h: `{change_sign}{change_24h:.2f}%`\n"
            f"📊 Market Cap: `{format_number(market_cap, fiat)}`\n"
            f"📈 Volume 24h: `{format_number(volume_24h, fiat)}`\n\n"
            f"_Sumber: CoinMarketCap_"
        )
    else:
        text = (
            f"💰 *{amount:g} {coin_name} ({coin_display}) → {fiat.upper()}*\n"
            f"🏅 Rank: `{rank_text}`\n\n"
            f"💵 Total: `{format_number(total, fiat)}`\n"
            f"📌 Harga/unit: `{format_number(price, fiat)}`\n"
            f"{change_emoji} 24h: `{change_sign}{change_24h:.2f}%`\n"
            f"📊 Market Cap: `{format_number(market_cap, fiat)}`\n"
            f"📈 Volume 24h: `{format_number(volume_24h, fiat)}`\n\n"
            f"_Sumber: CoinMarketCap_"
        )

    await msg.edit_text(text, parse_mode="Markdown")

# ==============================
# COMMANDS
# ==============================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 *Halo! Selamat datang di Crypto Bot!*\n\n"
        "Cara pakai — cukup ketik langsung:\n\n"
        "• `1 btc` → harga BTC dalam USD\n"
        "• `2 eth idr` → harga 2 ETH dalam Rupiah\n"
        "• `1 btc idr` → harga BTC dalam Rupiah\n"
        "• `0.5 sol eur` → harga 0.5 SOL dalam Euro\n"
        "• `100 doge jpy` → harga 100 DOGE dalam Yen\n\n"
        "📡 Data dari *CoinMarketCap*\n\n"
        "❓ `/help` — Bantuan\n"
        "💱 `/fiat` — Daftar mata uang\n"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 *Panduan Penggunaan Bot*\n\n"
        "*Format:* `<jumlah> <coin> [mata_uang]`\n\n"
        "*Contoh:*\n"
        "`1 btc` — harga BTC dalam USD\n"
        "`2 eth idr` — 2 ETH dalam Rupiah\n"
        "`0.5 sol eur` — 0.5 SOL dalam Euro\n"
        "`100 doge jpy` — 100 DOGE dalam Yen\n"
        "`1 pepe idr` — token meme\n"
        "`1 bitcoin idr` — nama lengkap juga bisa\n\n"
        "*Default fiat:* USD jika tidak ditulis\n\n"
        "💱 `/fiat` — Daftar mata uang yang didukung"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def fiat_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    fiat_display = [
        ("USD","Dollar"),("IDR","Rupiah"),("EUR","Euro"),("GBP","Pound"),
        ("JPY","Yen"),("SGD","S$ Dollar"),("MYR","Ringgit"),("AUD","A$ Dollar"),
        ("CNY","Yuan"),("KRW","Won"),("THB","Baht"),("PHP","Peso"),
        ("VND","Dong"),("BRL","Real"),("INR","Rupee"),("CHF","Swiss Franc"),
        ("HKD","HK Dollar"),("TWD","Taiwan Dollar"),("AED","Dirham"),
        ("SAR","Riyal"),("TRY","Lira"),("RUB","Ruble"),("ZAR","Rand"),
        ("MXN","Peso Mexico"),("PKR","Rupee Pakistan"),
    ]
    lines = ["💱 *Mata Uang Fiat yang Didukung*\n"]
    for code, name in fiat_display:
        symbol = FIAT_SYMBOL.get(code.lower(), "")
        lines.append(f"`{code}` {symbol}— {name}")
    lines.append("\n💡 Contoh: `1 btc idr` atau `2 eth eur`")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

# ==============================
# MESSAGE HANDLER
# ==============================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    text = update.message.text.strip()
    if text.startswith("/"):
        return
    result = parse_price_query(text)
    if result is None:
        return
    amount, coin_input, fiat = result
    await handle_price_query(update, amount, coin_input, fiat)

# ==============================
# MAIN
# ==============================

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("fiat", fiat_list))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("✅ Bot berjalan (CoinMarketCap)...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    main()
