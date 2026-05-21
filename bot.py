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

def cmc_get_price(symbol: str, convert: str) -> dict | None:
    try:
        resp = cmc_get("/cryptocurrency/quotes/latest", {
            "symbol": symbol.upper(),
            "convert": convert.upper(),
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

        quote = coin.get("quote", {}).get(convert.upper(), {})
        if not quote:
            return None

        return {
            "name": coin.get("name", symbol),
            "symbol": coin.get("symbol", symbol).lower(),
            "price": quote.get("price") or 0,
            "change_24h": quote.get("percent_change_24h") or 0,
        }

    except Exception as e:
        logger.error(f"CMC price error for '{symbol}' to '{convert}': {e}")
        return None


def cmc_search_by_name(query: str, convert: str) -> dict | None:
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

        return cmc_get_price(match["symbol"], convert)

    except Exception as e:
        logger.error(f"CMC name search error for '{query}': {e}")
        return None


def get_price(query: str, convert: str) -> dict | None:
    data = cmc_get_price(query, convert)
    if data:
        return data
    data = cmc_search_by_name(query, convert)
    return data

# ==============================
# HELPERS
# ==============================

def format_number(n: float, is_calc: bool = False) -> str:
    if n == 0:
        return "0"
    
    if is_calc:
        if n == int(n):
            return f"{int(n):,}".replace(",", ".")
        return f"{n:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    if n >= 1000:
        return f"{n:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    elif n >= 1:
        return f"{n:,.4f}".replace(".", ",")
    elif n >= 0.0001:
        return f"{n:.6f}".replace(".", ",")
    else:
        return f"{n:.10f}".replace(".", ",")

def format_change(change: float) -> str:
    sign = "+" if change >= 0 else ""
    return f"{sign}{change:.2f}%"

def process_suffix_format(text: str) -> str:
    """
    Konversi suffix k, m, b, t ke angka aslinya.
    k = 1,000
    m = 1,000,000
    b = 1,000,000,000
    t = 1,000,000,000,000
    """
    def replace_suffix(match):
        num = float(match.group(1))
        suffix = match.group(2).lower()
        multipliers = {
            'k': 1000,
            'm': 1000000,
            'b': 1000000000,
            't': 1000000000000
        }
        result = num * multipliers[suffix]
        # Kembalikan sebagai string integer jika tidak ada desimal untuk menghindari notasi ilmiah
        if result == int(result):
            return str(int(result))
        return f"{result:.10f}".rstrip('0').rstrip('.')

    return re.sub(r'(\d+(?:\.\d+)?)([kmbt])', replace_suffix, text, flags=re.IGNORECASE)

def safe_eval(expr: str):
    expr = process_suffix_format(expr.replace(",", "."))
    if not re.match(r'^[0-9.+\-*/\s()]+$', expr):
        return None
    try:
        result = eval(expr, {"__builtins__": None}, {})
        return float(result)
    except:
        return None

def parse_query(text: str):
    text = process_suffix_format(text.strip().lower())
    parts = text.split()
    if len(parts) < 2:
        return None
    
    if len(parts) >= 3:
        target1 = parts[-2]
        target2 = parts[-1]
        expr_str = " ".join(parts[:-2])
        amount = safe_eval(expr_str)
        
        if amount is not None:
            if target1 in SUPPORTED_FIAT:
                return {"amount": amount, "base": target2, "convert": target1, "expr": expr_str, "is_reverse": True}
            else:
                return {"amount": amount, "base": target1, "convert": target2, "expr": expr_str, "is_reverse": False}

    if len(parts) == 2:
        expr_str = parts[0]
        coin_candidate = parts[1]
        amount = safe_eval(expr_str)
        if amount is not None:
            return {"amount": amount, "base": coin_candidate, "convert": "usd", "expr": expr_str, "is_reverse": False}

    return None

# ==============================
# CORE HANDLER
# ==============================

async def handle_price_query(update: Update, q: dict):
    amount = q["amount"]
    base_input = q["base"]
    convert_input = q["convert"]
    original_expr = q["expr"]
    is_reverse = q["is_reverse"]

    msg = await update.message.reply_text(f"Mencari {base_input.upper()}...")

    data = get_price(base_input, convert_input)

    if not data:
        await msg.edit_text(f"{base_input.upper()} atau {convert_input.upper()} tidak ditemukan.")
        return

    price = data["price"]
    change_24h = data.get("change_24h") or 0
    coin_display = data.get("symbol", base_input.lower())
    coin_name = data.get("name", coin_display)

    if is_reverse:
        total_val = amount / price
        unit_display = coin_display
        calc_unit = convert_input.upper()
    else:
        total_val = amount * price
        unit_display = convert_input.lower()
        calc_unit = coin_display

    # Sembunyikan baris kalkulasi jika input hanya angka sederhana
    # Tampilkan jika mengandung operasi matematika atau suffix (k, m, b, t)
    show_calc_line = any(char in original_expr for char in "+-*/") or any(s in original_expr.lower() for s in "kmbt")
    
    calc_line = ""
    if show_calc_line:
        expr_html = html.escape(original_expr)
        amount_html = html.escape(format_number(amount, is_calc=True))
        calc_line = f"<code>{expr_html} = {amount_html}</code> {html.escape(calc_unit)}\n"

    coin_name_html = html.escape(coin_name)
    coin_display_html = html.escape(coin_display)
    total_html = html.escape(format_number(total_val))
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
# SELL HANDLER (REGRET CALCULATOR)
# ==============================

async def sell_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 4:
        await update.message.reply_text("Format: <code>/sell 1 btc at 30000 usd</code>", parse_mode=ParseMode.HTML)
        return

    try:
        amount = safe_eval(args[0])
        symbol = args[1].lower()
        sold_price = safe_eval(args[3])
        fiat = args[4].lower() if len(args) > 4 else "usd"
        
        if amount is None or sold_price is None:
            raise ValueError
    except:
        await update.message.reply_text("Format salah. Pastikan angka benar.")
        return

    msg = await update.message.reply_text(f"Mencari {symbol.upper()}...")
    
    data = get_price(symbol, fiat)
    if not data:
        await msg.edit_text(f"{symbol.upper()} tidak ditemukan.")
        return

    current_price = data["price"]
    realized_value = amount * sold_price
    current_potential_value = amount * current_price
    diff = realized_value - current_potential_value
    diff_percent = (diff / current_potential_value) * 100 if current_potential_value != 0 else 0
    
    text = (
        f"Simulasi Jual\n\n"
        f"Aset: {data['name']} ({data['symbol'].upper()})\n"
        f"Jumlah: {format_number(amount, True)}\n"
        f"-------------------\n"
        f"Harga Jual Dulu: {format_number(sold_price, True)} {fiat.upper()}\n"
        f"Harga Kini: {format_number(current_price, True)} {fiat.upper()}\n"
        f"-------------------\n"
        f"Hasil Jual Dulu: {format_number(realized_value, True)} {fiat.upper()}\n"
        f"Nilai Kini: {format_number(current_potential_value, True)} {fiat.upper()}\n\n"
        f"Selisih: {format_number(diff, True)} {fiat.upper()} ({format_change(diff_percent)})"
    )
    
    chart_url = f"https://coinmarketcap.com/currencies/{data['name'].lower().replace(' ', '-')}/"
    keyboard = [[InlineKeyboardButton("View Chart", url=chart_url)]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await msg.edit_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

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
    app.add_handler(CommandHandler("sell", sell_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("Bot berjalan...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    main()
