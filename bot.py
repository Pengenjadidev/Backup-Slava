import logging
import os
import re
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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

# ==============================
# COINMARKETCAP: SEARCH + PRICE
# ==============================

def cmc_get_price(symbol: str, fiat: str) -> dict | None:
    """
    Ambil harga langsung dari CMC by symbol.
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
            "symbol": coin.get("symbol", symbol).lower(),
            "price": quote.get("price") or 0,
            "change_24h": quote.get("percent_change_24h") or 0,
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
        match = next((c for c in coins if c["name"].lower() == q), None)
        if not match:
            match = next((c for c in coins if q in c["name"].lower()), None)
        if not match:
            return None

        return cmc_get_price(match["symbol"], fiat)

    except Exception as e:
        logger.error(f"CMC name search error for '{query}': {e}")
        return None


def get_price(query: str, fiat: str) -> dict | None:
    """
    Resolve harga coin dari CoinMarketCap.
    """
    data = cmc_get_price(query, fiat)
    if data:
        return data

    logger.info(f"Symbol lookup miss for '{query}', trying name search...")
    data = cmc_search_by_name(query, fiat)
    if data:
        return data

    return None

# ==============================
# HELPERS
# ==============================

def format_number(n: float) -> str:
    """Format angka tanpa simbol mata uang di depan"""
    if n == 0:
        return "0"
    elif n >= 1000:
        return f"{n:,.0f}".replace(",", ".")
    elif n >= 1:
        return f"{n:,.2f}".replace(",", ".")
    elif n >= 0.0001:
        return f"{n:.6f}"
    else:
        return f"{n:.10f}"

def format_change(change: float) -> str:
    """Format perubahan 24h tanpa emotikon"""
    sign = "+" if change >= 0 else ""
    return f"{sign}{change:.2f}%"

def parse_arithmetic_query(text: str):
    """
    Parse query dengan operasi aritmatika.
    """
    text = text.strip().lower()
    pattern = r'^(\d+(?:[.,]\d+)?)\s*([+\-*/])\s*(\d+(?:[.,]\d+)?)\s+([a-z0-9\-]+)(?:\s+([a-z]+))?$'
    match = re.match(pattern, text)
    if not match:
        return None
    
    num1_str, operator, num2_str, coin_input, fiat_input = match.groups()
    
    try:
        num1 = float(num1_str.replace(",", "."))
        num2 = float(num2_str.replace(",", "."))
        
        if operator == "+":
            amount = num1 + num2
        elif operator == "-":
            amount = num1 - num2
        elif operator == "*":
            amount = num1 * num2
        elif operator == "/":
            if num2 == 0:
                return None
            amount = num1 / num2
        else:
            return None
        
        fiat = fiat_input if fiat_input else "usd"
        if fiat not in SUPPORTED_FIAT:
            return None
        if coin_input in SUPPORTED_FIAT:
            return None
        
        return amount, coin_input, fiat
    except:
        return None

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
        f"Mencari {coin_input.upper()}..."
    )

    data = get_price(coin_input, fiat)

    if not data:
        await msg.edit_text(
            f"{coin_input.upper()} tidak ditemukan."
        )
        return

    price = data["price"]
    total = amount * price
    change_24h = data.get("change_24h") or 0
    coin_display = data.get("symbol", coin_input.lower())
    coin_name = data.get("name", coin_display)

    # Format output sangat sederhana sesuai permintaan
    # Bitcoin (btc):
    # 79924 usd        |-1.27%
    # 1.0183 btc       |-1.28% (Jika input jumlah > 1)
    
    if amount == 1:
        text = (
            f"{coin_name} ({coin_display}):\n"
            f"{format_number(price)} {fiat.lower()}        |{format_change(change_24h)}"
        )
    else:
        text = (
            f"{coin_name} ({coin_display}):\n"
            f"{format_number(total)} {fiat.lower()}        |{format_change(change_24h)}"
        )

    # Tombol chart tetap ada agar bersih
    chart_url = f"https://coinmarketcap.com/currencies/{coin_name.lower().replace(' ', '-')}/"
    keyboard = [[InlineKeyboardButton("View Chart", url=chart_url)]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await msg.edit_text(text, reply_markup=reply_markup)

# ==============================
# COMMANDS
# ==============================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "Halo! Selamat datang di Crypto Bot\n\n"
        "Cara pakai - cukup ketik langsung:\n"
        "1 btc\n"
        "2 eth idr\n"
        "13*4 btc\n\n"
        "/help - Bantuan\n"
        "/fiat - Daftar mata uang"
    )
    await update.message.reply_text(text)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "Panduan Penggunaan Bot\n\n"
        "Format: <jumlah> <coin> [mata_uang]\n"
        "Contoh: 1 btc idr\n\n"
        "Aritmatika: 13*4 btc\n\n"
        "/fiat - Daftar mata uang"
    )
    await update.message.reply_text(text)

async def fiat_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = ["Mata Uang Fiat yang Didukung:\n" + ", ".join(sorted(list(SUPPORTED_FIAT))).upper()]
    await update.message.reply_text("\n".join(lines))

# ==============================
# MESSAGE HANDLER
# ==============================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    text = update.message.text.strip()
    if text.startswith("/"):
        return
    
    result = parse_arithmetic_query(text)
    if result is None:
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
    logger.info("Bot berjalan...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    main()
