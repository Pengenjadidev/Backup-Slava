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
COINGECKO_API_KEY = os.environ.get("COINGECKO_API_KEY", "")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable tidak ditemukan!")
if not COINGECKO_API_KEY:
    raise ValueError("COINGECKO_API_KEY environment variable tidak ditemukan!")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==============================
# COINGECKO API CONFIG
# ==============================
COINGECKO_BASE = "https://pro-api.coingecko.com/api/v3"

def cg_headers() -> dict:
    """Header dengan API key CoinGecko Pro."""
    return {"x-cg-pro-api-key": COINGECKO_API_KEY}

# ==============================
# SUPPORTED FIAT
# ==============================
SUPPORTED_FIAT = {
    "usd", "idr", "eur", "gbp", "jpy", "sgd", "myr",
    "aud", "cny", "krw", "thb", "php", "vnd", "brl", "inr",
    "chf", "hkd", "twd", "nzd", "sek", "nok", "dkk", "rub",
    "zar", "try", "aed", "sar", "mxn", "cop", "clp", "pkr",
}

FIAT_SYMBOL = {
    "usd": "$", "idr": "Rp", "eur": "€", "gbp": "£", "jpy": "¥",
    "sgd": "S$", "myr": "RM", "aud": "A$", "cny": "¥", "krw": "₩",
    "thb": "฿", "php": "₱", "vnd": "₫", "brl": "R$", "inr": "₹",
    "chf": "Fr", "hkd": "HK$", "twd": "NT$", "nzd": "NZ$",
    "aed": "د.إ", "sar": "﷼", "try": "₺", "rub": "₽", "zar": "R",
}

# ==============================
# COIN SEARCH — langsung hit CoinGecko setiap query
# ==============================

def search_coin_id(query: str) -> str | None:
    """
    Cari coin ID dari CoinGecko berdasarkan simbol atau nama.
    Hit API setiap kali dipanggil agar selalu up-to-date.
    """
    query = query.lower().strip()
    try:
        # Gunakan endpoint /search untuk pencarian fleksibel
        resp = requests.get(
            f"{COINGECKO_BASE}/search",
            params={"query": query},
            headers=cg_headers(),
            timeout=10
        )
        resp.raise_for_status()
        data = resp.json()

        coins = data.get("coins", [])
        if not coins:
            return None

        # Prioritas 1: cocok persis dengan simbol
        for coin in coins:
            if coin["symbol"].lower() == query:
                return coin["id"]

        # Prioritas 2: cocok persis dengan nama
        for coin in coins:
            if coin["name"].lower() == query:
                return coin["id"]

        # Prioritas 3: hasil pertama dari pencarian
        return coins[0]["id"]

    except Exception as e:
        logger.error(f"Error searching coin '{query}': {e}")
        return None


def get_coin_price(coin_id: str, vs_currency: str = "usd") -> dict | None:
    """
    Ambil harga coin dari CoinGecko Pro API.
    Selalu hit API langsung setiap query.
    """
    try:
        resp = requests.get(
            f"{COINGECKO_BASE}/simple/price",
            params={
                "ids": coin_id,
                "vs_currencies": vs_currency,
                "include_24hr_change": "true",
                "include_market_cap": "true",
                "include_24hr_vol": "true",
            },
            headers=cg_headers(),
            timeout=10
        )
        resp.raise_for_status()
        data = resp.json()
        if coin_id in data:
            return data[coin_id]
        return None
    except Exception as e:
        logger.error(f"Error fetching price for '{coin_id}': {e}")
        return None


def get_coin_detail(coin_id: str) -> dict | None:
    """Ambil detail coin (nama lengkap, simbol, dll)."""
    try:
        resp = requests.get(
            f"{COINGECKO_BASE}/coins/{coin_id}",
            params={"localization": "false", "tickers": "false", "community_data": "false", "developer_data": "false"},
            headers=cg_headers(),
            timeout=10
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error(f"Error fetching detail for '{coin_id}': {e}")
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
    """
    Parse pesan natural: <jumlah> <coin> [fiat]
    Contoh: '1 btc', '2 eth idr', '0.5 sol eur'
    Return: (amount, coin_input, fiat) atau None
    """
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
# CORE: Handle price query
# ==============================

async def handle_price_query(update: Update, amount: float, coin_input: str, fiat: str):
    """Cari coin, ambil harga, dan tampilkan hasilnya."""
    msg = await update.message.reply_text(f"🔍 Mencari *{coin_input.upper()}*...", parse_mode="Markdown")

    # Step 1: Cari coin ID dari CoinGecko
    coin_id = search_coin_id(coin_input)
    if not coin_id:
        await msg.edit_text(
            f"❌ Coin `{coin_input.upper()}` tidak ditemukan di CoinGecko.\n"
            f"Coba gunakan nama lengkap, contoh: `1 bitcoin idr`",
            parse_mode="Markdown"
        )
        return

    # Step 2: Ambil harga
    await msg.edit_text(f"⏳ Mengambil harga *{coin_input.upper()}*...", parse_mode="Markdown")
    data = get_coin_price(coin_id, fiat)

    if not data or fiat not in data:
        await msg.edit_text(
            f"❌ Harga `{coin_input.upper()}` dalam `{fiat.upper()}` tidak tersedia.",
            parse_mode="Markdown"
        )
        return

    # Step 3: Susun response
    price_per_unit = data[fiat]
    total = amount * price_per_unit
    change_24h = data.get(f"{fiat}_24h_change") or 0
    market_cap = data.get(f"{fiat}_market_cap") or 0
    vol_24h = data.get(f"{fiat}_24h_vol") or 0

    change_emoji = "🟢" if change_24h >= 0 else "🔴"
    change_sign = "+" if change_24h >= 0 else ""
    coin_display = coin_input.upper()

    if amount == 1:
        text = (
            f"💰 *{coin_display} / {fiat.upper()}*\n\n"
            f"💵 Harga: `{format_number(price_per_unit, fiat)}`\n"
            f"{change_emoji} 24h: `{change_sign}{change_24h:.2f}%`\n"
            f"📊 Market Cap: `{format_number(market_cap, fiat)}`\n"
            f"📈 Volume 24h: `{format_number(vol_24h, fiat)}`\n\n"
            f"_Data dari CoinGecko_"
        )
    else:
        text = (
            f"💰 *{amount:g} {coin_display} → {fiat.upper()}*\n\n"
            f"💵 Total: `{format_number(total, fiat)}`\n"
            f"📌 Harga/unit: `{format_number(price_per_unit, fiat)}`\n"
            f"{change_emoji} 24h: `{change_sign}{change_24h:.2f}%`\n"
            f"📊 Market Cap: `{format_number(market_cap, fiat)}`\n\n"
            f"_Data dari CoinGecko_"
        )

    await msg.edit_text(text, parse_mode="Markdown")


# ==============================
# COMMAND HANDLERS
# ==============================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 *Halo! Selamat datang di Crypto Bot!*\n\n"
        "Cara pakai — cukup ketik langsung:\n\n"
        "• `1 btc` → harga 1 BTC dalam USD\n"
        "• `2 eth` → harga 2 ETH dalam USD\n"
        "• `1 btc idr` → harga 1 BTC dalam Rupiah\n"
        "• `0.5 sol eur` → harga 0.5 SOL dalam Euro\n"
        "• `100 doge jpy` → harga 100 DOGE dalam Yen\n\n"
        "Semua koin yang ada di CoinGecko bisa dicari! 🚀\n\n"
        "❓ `/help` — Bantuan lengkap\n"
        "💱 `/fiat` — Daftar mata uang yang didukung\n"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 *Panduan Penggunaan Bot*\n\n"
        "*Format:*\n"
        "`<jumlah> <coin> [mata_uang]`\n\n"
        "*Contoh:*\n"
        "`1 btc` — 1 BTC dalam USD\n"
        "`2 eth` — 2 ETH dalam USD\n"
        "`1 btc idr` — 1 BTC dalam Rupiah\n"
        "`0.5 sol eur` — 0.5 SOL dalam Euro\n"
        "`100 doge jpy` — 100 DOGE dalam Yen\n"
        "`1 pepe idr` — 1 PEPE dalam Rupiah\n"
        "`1 notcoin idr` — bisa nama lengkap juga\n\n"
        "*Default:* jika fiat tidak ditulis → USD\n\n"
        "💡 Semua koin di CoinGecko bisa dicari!\n"
        "💱 `/fiat` — Daftar mata uang yang didukung"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def fiat_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    fiat_display = [
        ("USD", "US Dollar"), ("IDR", "Rupiah"), ("EUR", "Euro"),
        ("GBP", "Pound"), ("JPY", "Yen"), ("SGD", "Singapore Dollar"),
        ("MYR", "Ringgit"), ("AUD", "Australian Dollar"), ("CNY", "Yuan"),
        ("KRW", "Won"), ("THB", "Baht"), ("PHP", "Peso"), ("VND", "Dong"),
        ("BRL", "Real"), ("INR", "Rupee"), ("CHF", "Swiss Franc"),
        ("HKD", "HK Dollar"), ("TWD", "Taiwan Dollar"), ("AED", "Dirham"),
        ("SAR", "Riyal"), ("TRY", "Lira"), ("RUB", "Ruble"), ("ZAR", "Rand"),
    ]
    lines = ["💱 *Mata Uang Fiat yang Didukung*\n"]
    for code, name in fiat_display:
        lines.append(f"`{code}` — {name}")
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
        return  # Abaikan pesan yang tidak sesuai format

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

    logger.info("✅ Bot berjalan...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
