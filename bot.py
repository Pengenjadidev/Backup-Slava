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
    data = cmc_get_price(query, fiat)
    if data:
        return data
    data = cmc_search_by_name(query, fiat)
    return data

# ==============================
# HELPERS
# ==============================

def format_number(n: float) -> str:
    if n == 0:
        return "0"
    elif n >= 1000:
        return f"{n:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    elif n >= 1:
        return f"{n:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    elif n >= 0.0001:
        return f"{n:.6f}".replace(".", ",")
    else:
        return f"{n:.10f}".replace(".", ",")

def format_change(change: float) -> str:
    sign = "+" if change >= 0 else ""
    return f"{sign}{change:.2f}%"

def safe_eval(expr: str):
    """Evaluasi aritmatika sederhana dengan aman"""
    expr = expr.replace(",", ".")
    # Hanya izinkan angka dan operator dasar
    if not re.match(r'^[0-9.+\-*/\s()]+$', expr):
        return None
    try:
        # Gunakan eval dengan namespace terbatas
        result = eval(expr, {"__builtins__": None}, {})
        return float(result)
    except:
        return None

def parse_arithmetic_query(text: str):
    """
    Parse query dengan operasi aritmatika: <expr> <coin> [fiat]
    """
    text = text.strip().lower()
    # Mencari ekspresi matematika di awal
    pattern = r'^([0-9.+\-*/\s()]+)\s+([a-z0-9\-]+)(?:\s+([a-z]+))?$'
    match = re.match(pattern, text)
    if not match:
        return None
    
    expr_str, coin_input, fiat_input = match.groups()
    amount = safe_eval(expr_str)
    
    if amount is None:
        return None
        
    fiat = fiat_input if fiat_input else "usd"
    if fiat not in SUPPORTED_FIAT:
        return None
    if coin_input in SUPPORTED_FIAT:
        return None
    
    return amount, coin_input, fiat, expr_str.strip()

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
    return amount, coin_input, fiat, amount_str

# ==============================
# CORE HANDLER
# ==============================

async def handle_price_query(update: Update, amount: float, coin_input: str, fiat: str, original_expr: str):
    msg = await update.message.reply_text(f"Mencari {coin_input.upper()}...")

    data = get_price(coin_input, fiat)

    if not data:
        await msg.edit_text(f"{coin_input.upper()} tidak ditemukan.")
        return

    price = data["price"]
    total = amount * price
    change_24h = data.get("change_24h") or 0
    coin_display = data.get("symbol", coin_input.lower())
    coin_name = data.get("name", coin_display)

    # Format output dengan monospace agar bisa autocopy
    # Jika ada ekspresi matematika, tampilkan hasilnya dulu
    if original_expr and not original_expr.replace(".", "").replace(",", "").isdigit():
        calc_line = f"`{original_expr} = {format_number(amount)}` {coin_display}\n"
    else:
        calc_line = ""

    text = (
        f"{coin_name} ({coin_display}):\n"
        f"{calc_line}"
        f"`{format_number(total)}` {fiat.lower()}        |`{format_change(change_24h)}`"
    )

    chart_url = f"https://coinmarketcap.com/currencies/{coin_name.lower().replace(' ', '-')}/"
    keyboard = [[InlineKeyboardButton("View Chart", url=chart_url)]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await msg.edit_text(text, reply_markup=reply_markup, parse_mode="MarkdownV2")

async def handle_calculator(update: Update, text: str):
    """Fungsi kalkulator sederhana"""
    result = safe_eval(text)
    if result is not None:
        # Format result agar rapi
        formatted_res = format_number(result)
        await update.message.reply_text(f"`{text} = {formatted_res}`", parse_mode="MarkdownV2")
        return True
    return False

# ==============================
# COMMANDS
# ==============================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "Halo! Selamat datang di Crypto Bot\n\n"
        "Cara pakai:\n"
        "1 btc\n"
        "13*4 btc idr\n"
        "10+5*2 (kalkulator)\n\n"
        "/help - Bantuan"
    )
    await update.message.reply_text(text)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "Panduan Bot\n\n"
        "Cek Harga: <jumlah/rumus> <coin> [fiat]\n"
        "Contoh: 13*4 btc idr\n\n"
        "Kalkulator: Ketik rumus matematika langsung\n"
        "Contoh: 5000/150\n\n"
        "Klik pada angka untuk copy otomatis."
    )
    await update.message.reply_text(text)

# ==============================
# MESSAGE HANDLER
# ==============================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    text = update.message.text.strip()
    if text.startswith("/"):
        return
    
    # 1. Coba parse sebagai query harga dengan aritmatika
    res = parse_arithmetic_query(text)
    if res:
        amount, coin_input, fiat, expr = res
        await handle_price_query(update, amount, coin_input, fiat, expr)
        return

    # 2. Coba parse sebagai query harga normal
    res = parse_price_query(text)
    if res:
        amount, coin_input, fiat, expr = res
        await handle_price_query(update, amount, coin_input, fiat, expr)
        return

    # 3. Coba sebagai kalkulator murni
    if await handle_calculator(update, text):
        return

# ==============================
# MAIN
# ==============================

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("Bot berjalan...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    main()
