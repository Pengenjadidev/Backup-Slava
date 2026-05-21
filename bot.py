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

def format_number(n: float, is_calc: bool = False) -> str:
    if n == 0:
        return "0"
    
    # Jika hasil perhitungan, hilangkan desimal jika bulat
    if is_calc:
        if n == int(n):
            return f"{int(n):,}".replace(",", ".")
        return f"{n:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    if n >= 1000:
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

def process_k_format(text: str) -> str:
    """Mengganti 100k menjadi 100000"""
    def replace_k(match):
        num = match.group(1)
        return str(int(float(num) * 1000))
    return re.sub(r'(\d+(?:\.\d+)?)k', replace_k, text, flags=re.IGNORECASE)

def safe_eval(expr: str):
    """Evaluasi aritmatika sederhana dengan aman"""
    expr = process_k_format(expr.replace(",", "."))
    if not re.match(r'^[0-9.+\-*/\s()]+$', expr):
        return None
    try:
        result = eval(expr, {"__builtins__": None}, {})
        return float(result)
    except:
        return None

def parse_query(text: str):
    """
    Parse query:
    1. <expr> <coin> [fiat] -> Normal
    2. <expr> <fiat> <coin> -> Reverse (Pembalikan)
    """
    text = process_k_format(text.strip().lower())
    
    # Pattern 1: <expr> <coin/fiat> <coin/fiat>
    # Kita pecah berdasarkan spasi terakhir
    parts = text.split()
    if len(parts) < 2:
        return None
    
    # Coba identifikasi fiat dan coin
    # Kasus 3 kata: <expr> <part1> <part2>
    if len(parts) >= 3:
        fiat_candidate = parts[-2]
        coin_candidate = parts[-1]
        expr_str = " ".join(parts[:-2])
        
        if fiat_candidate in SUPPORTED_FIAT:
            # Ini adalah REVERSE: 100k idr eth
            amount = safe_eval(expr_str)
            if amount is not None:
                return {"amount": amount, "coin": coin_candidate, "fiat": fiat_candidate, "expr": expr_str, "is_reverse": True}
        
        # Coba pola normal: 1 btc idr
        fiat_candidate = parts[-1]
        coin_candidate = parts[-2]
        expr_str = " ".join(parts[:-2])
        if fiat_candidate in SUPPORTED_FIAT:
            amount = safe_eval(expr_str)
            if amount is not None:
                return {"amount": amount, "coin": coin_candidate, "fiat": fiat_candidate, "expr": expr_str, "is_reverse": False}

    # Kasus 2 kata: <expr> <coin>
    if len(parts) == 2:
        expr_str = parts[0]
        coin_candidate = parts[1]
        amount = safe_eval(expr_str)
        if amount is not None:
            return {"amount": amount, "coin": coin_candidate, "fiat": "usd", "expr": expr_str, "is_reverse": False}

    return None

# ==============================
# CORE HANDLER
# ==============================

async def handle_price_query(update: Update, q: dict):
    amount = q["amount"]
    coin_input = q["coin"]
    fiat = q["fiat"]
    original_expr = q["expr"]
    is_reverse = q["is_reverse"]

    msg = await update.message.reply_text(f"Mencari {coin_input.upper()}...")

    data = get_price(coin_input, fiat)

    if not data:
        await msg.edit_text(f"{coin_input.upper()} tidak ditemukan.")
        return

    price = data["price"]
    change_24h = data.get("change_24h") or 0
    coin_display = data.get("symbol", coin_input.lower())
    coin_name = data.get("name", coin_display)

    if is_reverse:
        # Pembalikan: Berapa coin yang didapat dari fiat
        total_coin = amount / price
        total_display = format_number(total_coin)
        unit_display = coin_display
        
        # Baris kalkulasi
        expr_html = html.escape(original_expr)
        amount_html = html.escape(format_number(amount, is_calc=True))
        calc_line = f"<code>{expr_html} = {amount_html}</code> {html.escape(fiat.upper())}\n"
    else:
        # Normal: Berapa fiat yang didapat dari coin
        total_fiat = amount * price
        total_display = format_number(total_fiat)
        unit_display = fiat.lower()
        
        # Baris kalkulasi
        expr_html = html.escape(original_expr)
        amount_html = html.escape(format_number(amount, is_calc=True))
        calc_line = f"<code>{expr_html} = {amount_html}</code> {html.escape(coin_display)}\n"

    coin_name_html = html.escape(coin_name)
    coin_display_html = html.escape(coin_display)
    total_html = html.escape(total_display)
    unit_html = html.escape(unit_display)
    change_html = html.escape(format_change(change_24h))

    text = (
        f"{coin_name_html} ({coin_display_html}):\n"
        f"{calc_line}"
        f"<code>{total_html}</code> {unit_html}        |<code>{change_html}</code>"
    )

    chart_url = f"https://coinmarketcap.com/currencies/{coin_name.lower().replace(' ', '-')}/"
    keyboard = [[InlineKeyboardButton("View Chart", url=chart_url)]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await msg.edit_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

async def handle_calculator(update: Update, text: str):
    result = safe_eval(text)
    if result is not None:
        expr_html = html.escape(text)
        res_html = html.escape(format_number(result, is_calc=True))
        await update.message.reply_text(f"<code>{expr_html} = {res_html}</code>", parse_mode=ParseMode.HTML)
        return True
    return False

# ==============================
# MESSAGE HANDLER
# ==============================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    text = update.message.text.strip()
    if text.startswith("/"):
        return
    
    q = parse_query(text)
    if q:
        await handle_price_query(update, q)
        return

    if await handle_calculator(update, text):
        return

# ==============================
# MAIN
# ==============================

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", lambda u, c: u.message.reply_text("Bot Aktif.")))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("Bot berjalan...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    main()
