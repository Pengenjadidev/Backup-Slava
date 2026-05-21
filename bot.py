import logging
import os
import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# ==============================
# KONFIGURASI
# Token dibaca dari environment variable (aman untuk Railway)
# ==============================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable tidak ditemukan! Set di Railway dashboard.")

# ==============================
# LOGGING
# ==============================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==============================
# HELPER: COINGECKO API
# ==============================
COINGECKO_BASE = "https://api.coingecko.com/api/v3"

# Mapping nama/alias populer ke CoinGecko ID
COIN_ALIASES = {
    "btc": "bitcoin",
    "eth": "ethereum",
    "bnb": "binancecoin",
    "sol": "solana",
    "xrp": "ripple",
    "ada": "cardano",
    "doge": "dogecoin",
    "dot": "polkadot",
    "matic": "matic-network",
    "ltc": "litecoin",
    "avax": "avalanche-2",
    "link": "chainlink",
    "trx": "tron",
    "shib": "shiba-inu",
    "ton": "the-open-network",
}

# Mata uang fiat yang didukung
SUPPORTED_FIAT = {"usd", "idr", "eur", "gbp", "jpy", "sgd", "myr", "aud", "cny", "krw"}

def resolve_coin_id(coin: str) -> str:
    """Resolve alias atau simbol ke CoinGecko coin ID."""
    coin = coin.lower().strip()
    return COIN_ALIASES.get(coin, coin)

def get_coin_price(coin_id: str, vs_currency: str = "usd") -> dict | None:
    """Ambil harga coin dari CoinGecko."""
    try:
        url = f"{COINGECKO_BASE}/simple/price"
        params = {
            "ids": coin_id,
            "vs_currencies": vs_currency,
            "include_24hr_change": "true",
            "include_market_cap": "true",
        }
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if coin_id in data:
            return data[coin_id]
        return None
    except Exception as e:
        logger.error(f"Error fetching price: {e}")
        return None

def get_exchange_rate(from_currency: str, to_currency: str, amount: float) -> dict | None:
    """
    Konversi mata uang menggunakan CoinGecko.
    Mendukung: crypto-to-fiat, fiat-to-fiat (via USD), fiat-to-crypto.
    """
    from_c = from_currency.lower()
    to_c = to_currency.lower()

    try:
        # Case 1: crypto -> fiat
        if from_c not in SUPPORTED_FIAT and to_c in SUPPORTED_FIAT:
            coin_id = resolve_coin_id(from_c)
            data = get_coin_price(coin_id, to_c)
            if data and to_c in data:
                rate = data[to_c]
                return {"result": amount * rate, "rate": rate}

        # Case 2: fiat -> crypto
        elif from_c in SUPPORTED_FIAT and to_c not in SUPPORTED_FIAT:
            coin_id = resolve_coin_id(to_c)
            data = get_coin_price(coin_id, from_c)
            if data and from_c in data:
                rate = data[from_c]
                result = amount / rate
                return {"result": result, "rate": 1 / rate}

        # Case 3: fiat -> fiat (via USD as bridge)
        elif from_c in SUPPORTED_FIAT and to_c in SUPPORTED_FIAT:
            # Ambil rate keduanya terhadap USD via exchangerate-api (gratis)
            url = f"https://open.er-api.com/v6/latest/{from_c.upper()}"
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            if data.get("result") == "success" and to_c.upper() in data["rates"]:
                rate = data["rates"][to_c.upper()]
                return {"result": amount * rate, "rate": rate}

        # Case 4: crypto -> crypto (via USD)
        else:
            coin_from = resolve_coin_id(from_c)
            coin_to = resolve_coin_id(to_c)
            url = f"{COINGECKO_BASE}/simple/price"
            params = {"ids": f"{coin_from},{coin_to}", "vs_currencies": "usd"}
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            if coin_from in data and coin_to in data:
                price_from = data[coin_from]["usd"]
                price_to = data[coin_to]["usd"]
                rate = price_from / price_to
                return {"result": amount * rate, "rate": rate}

        return None
    except Exception as e:
        logger.error(f"Error in conversion: {e}")
        return None

def format_number(n: float) -> str:
    """Format angka besar dengan pemisah ribuan."""
    if n >= 1_000_000:
        return f"{n:,.2f}"
    elif n >= 1:
        return f"{n:,.4f}"
    else:
        return f"{n:.8f}"

# ==============================
# COMMAND HANDLERS
# ==============================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 *Halo! Selamat datang di Crypto Bot!*\n\n"
        "Berikut perintah yang tersedia:\n\n"
        "💰 `/harga <coin> [mata_uang]`\n"
        "   Cek harga crypto\n"
        "   Contoh: `/harga bitcoin` atau `/harga btc idr`\n\n"
        "🔄 `/konversi <jumlah> <dari> <ke>`\n"
        "   Konversi mata uang / crypto\n"
        "   Contoh: `/konversi 100 usd idr`\n"
        "   Contoh: `/konversi 0.5 btc usd`\n\n"
        "📋 `/list` — Daftar crypto populer\n"
        "❓ `/help` — Bantuan lengkap\n"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 *Panduan Penggunaan Bot*\n\n"
        "*Cek Harga Crypto:*\n"
        "`/harga bitcoin` — harga BTC dalam USD\n"
        "`/harga btc idr` — harga BTC dalam IDR\n"
        "`/harga ethereum eur` — harga ETH dalam EUR\n\n"
        "*Konversi Mata Uang:*\n"
        "`/konversi 1 btc usd` — BTC ke USD\n"
        "`/konversi 100 usd idr` — USD ke IDR\n"
        "`/konversi 1000000 idr sgd` — IDR ke SGD\n"
        "`/konversi 1 eth btc` — ETH ke BTC\n\n"
        "*Alias Crypto yang didukung:*\n"
        "btc, eth, bnb, sol, xrp, ada, doge, dot, matic, ltc, avax, link, trx, shib, ton\n\n"
        "*Mata uang fiat:* USD, IDR, EUR, GBP, JPY, SGD, MYR, AUD, CNY, KRW\n\n"
        "💡 Nama coin lain juga bisa dicoba menggunakan CoinGecko ID-nya."
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def harga(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text(
            "⚠️ Format: `/harga <coin> [mata_uang]`\nContoh: `/harga bitcoin` atau `/harga btc idr`",
            parse_mode="Markdown"
        )
        return

    coin_input = args[0].lower()
    vs_currency = args[1].lower() if len(args) > 1 else "usd"

    if vs_currency not in SUPPORTED_FIAT:
        await update.message.reply_text(
            f"⚠️ Mata uang `{vs_currency.upper()}` tidak didukung.\n"
            f"Pilihan: {', '.join(c.upper() for c in SUPPORTED_FIAT)}",
            parse_mode="Markdown"
        )
        return

    coin_id = resolve_coin_id(coin_input)
    await update.message.reply_text("⏳ Mengambil data harga...")

    data = get_coin_price(coin_id, vs_currency)

    if not data:
        await update.message.reply_text(
            f"❌ Coin `{coin_input}` tidak ditemukan.\n"
            "Coba gunakan nama lengkap (contoh: `bitcoin`, `ethereum`) atau cek `/list`.",
            parse_mode="Markdown"
        )
        return

    price = data.get(vs_currency, 0)
    change_24h = data.get(f"{vs_currency}_24h_change", 0)
    market_cap = data.get(f"{vs_currency}_market_cap", 0)

    change_emoji = "🟢" if change_24h >= 0 else "🔴"
    change_sign = "+" if change_24h >= 0 else ""

    text = (
        f"💰 *{coin_id.upper()} / {vs_currency.upper()}*\n\n"
        f"💵 Harga: `{vs_currency.upper()} {format_number(price)}`\n"
        f"{change_emoji} 24h: `{change_sign}{change_24h:.2f}%`\n"
        f"📊 Market Cap: `{vs_currency.upper()} {format_number(market_cap)}`\n\n"
        f"_Data dari CoinGecko_"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def konversi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 3:
        await update.message.reply_text(
            "⚠️ Format: `/konversi <jumlah> <dari> <ke>`\n"
            "Contoh: `/konversi 100 usd idr`\n"
            "Contoh: `/konversi 0.5 btc usd`",
            parse_mode="Markdown"
        )
        return

    try:
        amount = float(args[0].replace(",", "."))
    except ValueError:
        await update.message.reply_text("⚠️ Jumlah tidak valid. Gunakan angka, contoh: `100` atau `0.5`", parse_mode="Markdown")
        return

    from_currency = args[1].lower()
    to_currency = args[2].lower()

    await update.message.reply_text("⏳ Menghitung konversi...")

    result = get_exchange_rate(from_currency, to_currency, amount)

    if not result:
        await update.message.reply_text(
            f"❌ Gagal mengkonversi `{from_currency.upper()}` ke `{to_currency.upper()}`.\n"
            "Pastikan nama mata uang/coin benar.",
            parse_mode="Markdown"
        )
        return

    converted = result["result"]
    rate = result["rate"]

    text = (
        f"🔄 *Hasil Konversi*\n\n"
        f"`{format_number(amount)} {from_currency.upper()}`\n"
        f"➡️ `{format_number(converted)} {to_currency.upper()}`\n\n"
        f"📈 Rate: `1 {from_currency.upper()} = {format_number(rate)} {to_currency.upper()}`\n\n"
        f"_Data dari CoinGecko / ExchangeRate API_"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def list_coins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📋 *Daftar Crypto Populer*\n\n"
        "Gunakan simbol atau nama lengkap:\n\n"
        "| Simbol | Nama |\n"
        "|--------|------|\n"
    )
    coins = [
        ("BTC", "Bitcoin"), ("ETH", "Ethereum"), ("BNB", "BNB"),
        ("SOL", "Solana"), ("XRP", "Ripple"), ("ADA", "Cardano"),
        ("DOGE", "Dogecoin"), ("DOT", "Polkadot"), ("MATIC", "Polygon"),
        ("LTC", "Litecoin"), ("AVAX", "Avalanche"), ("LINK", "Chainlink"),
        ("TRX", "Tron"), ("SHIB", "Shiba Inu"), ("TON", "Toncoin"),
    ]

    lines = ["📋 *Daftar Crypto Populer*\n"]
    for symbol, name in coins:
        lines.append(f"• `{symbol}` — {name}")
    lines.append("\n💡 Contoh: `/harga btc idr` atau `/konversi 1 eth usd`")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

# ==============================
# MAIN
# ==============================
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("harga", harga))
    app.add_handler(CommandHandler("konversi", konversi))
    app.add_handler(CommandHandler("list", list_coins))

    logger.info("Bot berjalan...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
