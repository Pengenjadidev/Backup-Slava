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
COINGECKO_API_KEY = os.environ.get("COINGECKO_API_KEY", "")  # Opsional

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable tidak ditemukan!")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==============================
# API CONFIG
# ==============================
DEXSCREENER_BASE = "https://api.dexscreener.com"

def cg_get(endpoint: str, params: dict = {}) -> requests.Response:
    """Request ke CoinGecko (Pro jika ada key, free jika tidak)."""
    if COINGECKO_API_KEY:
        base = "https://pro-api.coingecko.com/api/v3"
        headers = {"x-cg-pro-api-key": COINGECKO_API_KEY}
    else:
        base = "https://api.coingecko.com/api/v3"
        headers = {}
    return requests.get(f"{base}{endpoint}", params=params, headers=headers, timeout=10)

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
# COIN ALIASES (CoinGecko ID)
# ==============================
COIN_ALIASES = {
    "btc": "bitcoin", "eth": "ethereum", "bnb": "binancecoin",
    "sol": "solana", "xrp": "ripple", "usdt": "tether",
    "usdc": "usd-coin", "ada": "cardano", "doge": "dogecoin",
    "trx": "tron", "dot": "polkadot", "avax": "avalanche-2",
    "atom": "cosmos", "near": "near", "ftm": "fantom",
    "algo": "algorand", "icp": "internet-computer", "apt": "aptos",
    "sui": "sui", "sei": "sei-network", "inj": "injective-protocol",
    "hbar": "hedera-hashgraph", "xlm": "stellar", "vet": "vechain",
    "fil": "filecoin", "kas": "kaspa", "zec": "zcash", "xtz": "tezos",
    "eos": "eos", "etc": "ethereum-classic", "bch": "bitcoin-cash",
    "ltc": "litecoin", "xmr": "monero", "dash": "dash",
    "matic": "matic-network", "pol": "matic-network", "arb": "arbitrum",
    "op": "optimism", "strk": "starknet", "imx": "immutable-x",
    "uni": "uniswap", "aave": "aave", "crv": "curve-dao-token",
    "mkr": "maker", "cake": "pancakeswap-token", "gmx": "gmx",
    "dydx": "dydx", "1inch": "1inch",
    "fet": "fetch-ai", "agix": "singularitynet", "rndr": "render-token",
    "render": "render-token", "grt": "the-graph", "wld": "worldcoin-wld",
    "tao": "bittensor", "akt": "akash-network", "ocean": "ocean-protocol",
    "axs": "axie-infinity", "sand": "the-sandbox", "mana": "decentraland",
    "enj": "enjincoin", "gala": "gala",
    "shib": "shiba-inu", "pepe": "pepe", "floki": "floki",
    "bonk": "bonk", "wif": "dogwifcoin", "bome": "book-of-meme",
    "popcat": "popcat",
    "link": "chainlink", "pyth": "pyth-network", "ar": "arweave",
    "hnt": "helium", "ton": "the-open-network", "not": "notcoin",
    "dai": "dai", "wbtc": "wrapped-bitcoin", "steth": "staked-ether",
    "ens": "ethereum-name-service", "pendle": "pendle",
    "jup": "jupiter-exchange-solana", "eigen": "eigenlayer",
    "chz": "chiliz", "bat": "basic-attention-token",
    "okb": "okb", "cro": "crypto-com-chain", "kcs": "kucoin-shares",
    "dogs": "dogs-2", "hmstr": "hamster-kombat",
}

# ==============================
# FIAT CONVERSION (untuk DexScreener yang hanya punya USD)
# ==============================

def get_fiat_rate(to_fiat: str) -> float:
    """Ambil rate USD → fiat target via ExchangeRate API (gratis)."""
    if to_fiat == "usd":
        return 1.0
    try:
        resp = requests.get(
            f"https://open.er-api.com/v6/latest/USD",
            timeout=8
        )
        resp.raise_for_status()
        data = resp.json()
        return data["rates"].get(to_fiat.upper(), 1.0)
    except Exception as e:
        logger.error(f"Error fetching fiat rate for {to_fiat}: {e}")
        return 1.0

# ==============================
# SOURCE 1: COINGECKO
# ==============================

def coingecko_search(query: str) -> str | None:
    """Cari coin ID di CoinGecko."""
    q = query.lower().strip()
    if q in COIN_ALIASES:
        return COIN_ALIASES[q]
    try:
        resp = cg_get("/search", {"query": q})
        resp.raise_for_status()
        coins = resp.json().get("coins", [])
        if not coins:
            return None
        exact = [c for c in coins if c["symbol"].lower() == q]
        if exact:
            exact.sort(key=lambda c: c.get("market_cap_rank") or 999999)
            return exact[0]["id"]
        exact_name = [c for c in coins if c["name"].lower() == q]
        if exact_name:
            exact_name.sort(key=lambda c: c.get("market_cap_rank") or 999999)
            return exact_name[0]["id"]
        coins.sort(key=lambda c: c.get("market_cap_rank") or 999999)
        return coins[0]["id"]
    except Exception as e:
        logger.error(f"CoinGecko search error: {e}")
        return None

def coingecko_price(coin_id: str, fiat: str) -> dict | None:
    """Ambil harga dari CoinGecko."""
    try:
        resp = cg_get("/simple/price", {
            "ids": coin_id,
            "vs_currencies": fiat,
            "include_24hr_change": "true",
            "include_market_cap": "true",
            "include_24hr_vol": "true",
        })
        resp.raise_for_status()
        data = resp.json()
        if coin_id not in data or fiat not in data[coin_id]:
            return None
        d = data[coin_id]
        return {
            "price": d[fiat],
            "change_24h": d.get(f"{fiat}_24h_change") or 0,
            "market_cap": d.get(f"{fiat}_market_cap") or 0,
            "volume_24h": d.get(f"{fiat}_24h_vol") or 0,
            "source": "CoinGecko",
            "coin_name": coin_id.replace("-", " ").title(),
        }
    except Exception as e:
        logger.error(f"CoinGecko price error: {e}")
        return None

# ==============================
# SOURCE 2: DEXSCREENER
# ==============================

def dexscreener_search(query: str, fiat: str) -> dict | None:
    """
    Cari token di DexScreener.
    Ambil pair dengan liquiditas terbesar sebagai harga acuan.
    Konversi ke fiat jika bukan USD.
    """
    try:
        resp = requests.get(
            f"{DEXSCREENER_BASE}/latest/dex/search",
            params={"q": query},
            timeout=10
        )
        resp.raise_for_status()
        pairs = resp.json().get("pairs", [])
        if not pairs:
            return None

        # Filter: hanya pair yang simbolnya exact match
        q = query.upper()
        exact = [
            p for p in pairs
            if p.get("baseToken", {}).get("symbol", "").upper() == q
        ]
        candidates = exact if exact else pairs

        # Pilih pair dengan liquiditas terbesar
        candidates.sort(
            key=lambda p: float(p.get("liquidity", {}).get("usd", 0) or 0),
            reverse=True
        )
        best = candidates[0]

        price_usd = float(best.get("priceUsd") or 0)
        if price_usd == 0:
            return None

        # Konversi ke fiat target
        fiat_rate = get_fiat_rate(fiat)
        price_fiat = price_usd * fiat_rate

        change_24h = float(best.get("priceChange", {}).get("h24") or 0)
        volume_24h_usd = float(best.get("volume", {}).get("h24") or 0)
        liquidity_usd = float(best.get("liquidity", {}).get("usd") or 0)

        token_name = best.get("baseToken", {}).get("name", query)
        token_symbol = best.get("baseToken", {}).get("symbol", query)
        chain = best.get("chainId", "").capitalize()
        dex = best.get("dexId", "").capitalize()
        pair_url = best.get("url", "")

        return {
            "price": price_fiat,
            "change_24h": change_24h,
            "market_cap": 0,  # DexScreener jarang punya market cap
            "volume_24h": volume_24h_usd * fiat_rate,
            "liquidity": liquidity_usd * fiat_rate,
            "source": f"DexScreener ({chain} · {dex})",
            "coin_name": token_name,
            "symbol": token_symbol,
            "pair_url": pair_url,
        }
    except Exception as e:
        logger.error(f"DexScreener search error: {e}")
        return None

# ==============================
# UNIFIED PRICE RESOLVER
# ==============================

def get_price(query: str, fiat: str) -> dict | None:
    """
    Coba CoinGecko dulu, fallback ke DexScreener.
    Return dict dengan data harga yang sudah dinormalisasi.
    """
    # --- CoinGecko ---
    coin_id = coingecko_search(query)
    if coin_id:
        data = coingecko_price(coin_id, fiat)
        if data:
            logger.info(f"Price for '{query}' from CoinGecko ({coin_id})")
            return data

    # --- DexScreener fallback ---
    logger.info(f"CoinGecko miss for '{query}', trying DexScreener...")
    data = dexscreener_search(query, fiat)
    if data:
        logger.info(f"Price for '{query}' from DexScreener")
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
            f"❌ *{coin_input.upper()}* tidak ditemukan di CoinGecko maupun DexScreener.\n"
            f"Coba gunakan nama lengkap atau contract address.",
            parse_mode="Markdown"
        )
        return

    price = data["price"]
    total = amount * price
    change_24h = data.get("change_24h") or 0
    market_cap = data.get("market_cap") or 0
    volume_24h = data.get("volume_24h") or 0
    liquidity = data.get("liquidity") or 0
    source = data.get("source", "")
    coin_display = data.get("symbol", coin_input).upper()
    pair_url = data.get("pair_url", "")

    change_emoji = "🟢" if change_24h >= 0 else "🔴"
    change_sign = "+" if change_24h >= 0 else ""

    if amount == 1:
        text = (
            f"💰 *{coin_display} / {fiat.upper()}*\n\n"
            f"💵 Harga: `{format_number(price, fiat)}`\n"
            f"{change_emoji} 24h: `{change_sign}{change_24h:.2f}%`\n"
        )
        if market_cap > 0:
            text += f"📊 Market Cap: `{format_number(market_cap, fiat)}`\n"
        if volume_24h > 0:
            text += f"📈 Volume 24h: `{format_number(volume_24h, fiat)}`\n"
        if liquidity > 0:
            text += f"💧 Liquidity: `{format_number(liquidity, fiat)}`\n"
    else:
        text = (
            f"💰 *{amount:g} {coin_display} → {fiat.upper()}*\n\n"
            f"💵 Total: `{format_number(total, fiat)}`\n"
            f"📌 Harga/unit: `{format_number(price, fiat)}`\n"
            f"{change_emoji} 24h: `{change_sign}{change_24h:.2f}%`\n"
        )
        if market_cap > 0:
            text += f"📊 Market Cap: `{format_number(market_cap, fiat)}`\n"
        if volume_24h > 0:
            text += f"📈 Volume 24h: `{format_number(volume_24h, fiat)}`\n"
        if liquidity > 0:
            text += f"💧 Liquidity: `{format_number(liquidity, fiat)}`\n"

    text += f"\n_Sumber: {source}_"
    if pair_url:
        text += f"\n[Lihat chart di DexScreener]({pair_url})"

    await msg.edit_text(text, parse_mode="Markdown", disable_web_page_preview=True)

# ==============================
# COMMANDS
# ==============================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 *Halo! Selamat datang di Crypto Bot!*\n\n"
        "Cara pakai — cukup ketik langsung:\n\n"
        "• `1 btc` → harga BTC dalam USD\n"
        "• `2 eth idr` → harga 2 ETH dalam Rupiah\n"
        "• `1 pepe idr` → harga PEPE dalam Rupiah\n"
        "• `1 wojak usd` → token baru/DeFi juga bisa!\n\n"
        "🔁 Data dari *CoinGecko* + *DexScreener*\n\n"
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
        "`1 wojak usd` — token DeFi/baru via DexScreener\n\n"
        "*Default fiat:* USD\n\n"
        "🔁 Bot otomatis cari di CoinGecko dulu,\n"
        "jika tidak ada → lanjut ke DexScreener.\n\n"
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
    ]
    lines = ["💱 *Mata Uang Fiat yang Didukung*\n"]
    for code, name in fiat_display:
        symbol = FIAT_SYMBOL.get(code.lower(), "")
        lines.append(f"`{code}` {symbol} — {name}")
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
    logger.info("✅ Bot berjalan (CoinGecko + DexScreener)...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    main()
