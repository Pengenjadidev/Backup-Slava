import logging
import os
import re
import requests
import html
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
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
        # Format: 1.234.567,89
        return f"{n:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    elif n >= 1:
        return f"{n:,.2f}".replace(".", ",")
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
    if not re.match(r'^[0-9.+\-*/\s()]+$', expr):
        return None
    try:
        result = eval(expr, {"__builtins__": None}, {})
        return float(result)
    except:
        return None

def parse_arithmetic_query(text: str):
    text = text.strip().lower()
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

    # Gunakan HTML agar lebih stabil
    coin_name_html = html.escape(coin_name)
    coin_display_html = html.escape(coin_display)
    fiat_html = html.escape(fiat.lower())
    
    if original_expr and not original_expr.replace(".", "").replace(",", "").isdigit():
        expr_html = html.escape(original_expr)
        res_html = html.escape(format_number(amount))
        calc_line = f"<code>{expr_html} = {res_html}</code> {coin_display_html}\n"
    else:
        calc_line = ""

    total_html = html.escape(format_number(total))
    change_html = html.escape(format_change(change_24h))

    text = (
        f"{coin_name_html} ({coin_display_html}):\n"
        f"{calc_line}"
        f"<code>{total_html}</code> {fiat_html}        |<code>{change_html}</code>"
    )

    chart_url = f"https://coinmarketcap.com/currencies/{coin_name.lower().replace(' ', '-')}/"
    keyboard = [[InlineKeyboardButton("View Chart", url=chart_url)]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await msg.edit_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

async def handle_calculator(update: Update, text: str):
    result = safe_eval(text)
    if result is not None:
        expr_html = html.escape(text)
        res_html = html.escape(format_number(result))
        await update.message.reply_text(f"<code>{expr_html} = {res_html}</code>", parse_mode=ParseMode.HTML)
        return True
    return False

# ==============================
# COMMANDS
# ==============================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot Aktif. Gunakan <jumlah> <coin> atau rumus matematika.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Contoh: 1 btc, 13*4 eth idr, 5000/150")

# ==============================
# MESSAGE HANDLER
# ==============================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    text = update.message.text.strip()
    if text.startswith("/"):
        return
    
    res = parse_arithmetic_query(text)
    if res:
        amount, coin_input, fiat, expr = res
        await handle_price_query(update, amount, coin_input, fiat, expr)
        return

    res = parse_price_query(text)
    if res:
        amount, coin_input, fiat, expr = res
        await handle_price_query(update, amount, coin_input, fiat, expr)
        return

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
