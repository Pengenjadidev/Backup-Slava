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
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable tidak ditemukan!")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

COINGECKO_BASE = "https://api.coingecko.com/api/v3"

# ==============================
# DAFTAR COIN LENGKAP
# ==============================
COIN_ALIASES = {
    # Top 10
    "btc": "bitcoin",
    "eth": "ethereum",
    "bnb": "binancecoin",
    "sol": "solana",
    "xrp": "ripple",
    "usdt": "tether",
    "usdc": "usd-coin",
    "ada": "cardano",
    "doge": "dogecoin",
    "trx": "tron",
    # Layer 1
    "dot": "polkadot",
    "avax": "avalanche-2",
    "atom": "cosmos",
    "near": "near",
    "ftm": "fantom",
    "algo": "algorand",
    "icp": "internet-computer",
    "apt": "aptos",
    "sui": "sui",
    "sei": "sei-network",
    "inj": "injective-protocol",
    "one": "harmony",
    "egld": "elrond-erd-2",
    "hbar": "hedera-hashgraph",
    "xlm": "stellar",
    "vet": "vechain",
    "flow": "flow",
    "kas": "kaspa",
    "zec": "zcash",
    "xtz": "tezos",
    "eos": "eos",
    "etc": "ethereum-classic",
    "bch": "bitcoin-cash",
    "bsv": "bitcoin-sv",
    # Layer 2 / Scaling
    "matic": "matic-network",
    "pol": "matic-network",
    "arb": "arbitrum",
    "op": "optimism",
    "strk": "starknet",
    "zk": "zksync",
    "imx": "immutable-x",
    "lrc": "loopring",
    # DeFi
    "uni": "uniswap",
    "aave": "aave",
    "crv": "curve-dao-token",
    "mkr": "maker",
    "snx": "synthetix-network-token",
    "comp": "compound-governance-token",
    "bal": "balancer",
    "sushi": "sushi",
    "1inch": "1inch",
    "cake": "pancakeswap-token",
    "joe": "joe",
    "gmx": "gmx",
    "dydx": "dydx",
    "perp": "perpetual-protocol",
    # AI & Data
    "fet": "fetch-ai",
    "agix": "singularitynet",
    "ocean": "ocean-protocol",
    "rndr": "render-token",
    "render": "render-token",
    "grt": "the-graph",
    "wld": "worldcoin-wld",
    "tao": "bittensor",
    "akash": "akash-network",
    "akt": "akash-network",
    # Gaming & Metaverse
    "axs": "axie-infinity",
    "sand": "the-sandbox",
    "mana": "decentraland",
    "enj": "enjincoin",
    "ilv": "illuvium",
    "gala": "gala",
    "ygg": "yield-guild-games",
    "magic": "magic",
    "gods": "gods-unchained",
    # NFT & Social
    "blur": "blur",
    "looks": "looksrare",
    "x2y2": "x2y2",
    # Infrastructure
    "link": "chainlink",
    "band": "band-protocol",
    "api3": "api3",
    "pyth": "pyth-network",
    "fil": "filecoin",
    "ar": "arweave",
    "storj": "storj",
    "lpt": "livepeer",
    "hnt": "helium",
    "iotx": "iotex",
    # Exchange Tokens
    "kcs": "kucoin-shares",
    "gt": "gatechain-token",
    "mx": "mx-token",
    "okb": "okb",
    "cro": "crypto-com-chain",
    "ht": "huobi-token",
    # Meme
    "shib": "shiba-inu",
    "pepe": "pepe",
    "floki": "floki",
    "bonk": "bonk",
    "wif": "dogwifcoin",
    "meme": "memecoin-2",
    "bome": "book-of-meme",
    "popcat": "popcat",
    # Stablecoins & Wrapped
    "dai": "dai",
    "busd": "binance-usd",
    "tusd": "true-usd",
    "frax": "frax",
    "wbtc": "wrapped-bitcoin",
    "weth": "weth",
    "steth": "staked-ether",
    # Others
    "ton": "the-open-network",
    "ltc": "litecoin",
    "xmr": "monero",
    "dash": "dash",
    "neo": "neo",
    "waves": "waves",
    "qtum": "qtum",
    "bat": "basic-attention-token",
    "chz": "chiliz",
    "hot": "holotoken",
    "zil": "zilliqa",
    "iota": "iota",
    "nano": "nano",
    "sc": "siacoin",
    "dcr": "decred",
    "kava": "kava",
    "celr": "celer-network",
    "glm": "golem",
    "ens": "ethereum-name-service",
    "cvx": "convex-finance",
    "frxeth": "frax-ether",
    "stg": "stargate-finance",
    "pendle": "pendle",
    "ethfi": "ether-fi",
    "eigen": "eigenlayer",
    "jup": "jupiter-exchange-solana",
    "pyusd": "paypal-usd",
    "not": "notcoin",
    "dogs": "dogs-2",
    "hmstr": "hamster-kombat",
    "cati": "catizen",
    "major": "major",
}

SUPPORTED_FIAT = {"usd", "idr", "eur", "gbp", "jpy", "sgd", "myr", "aud", "cny", "krw", "thb", "php", "vnd", "brl", "inr"}

FIAT_SYMBOL = {
    "usd": "$", "idr": "Rp", "eur": "€", "gbp": "£", "jpy": "¥",
    "sgd": "S$", "myr": "RM", "aud": "A$", "cny": "¥", "krw": "₩",
    "thb": "฿", "php": "₱", "vnd": "₫", "brl": "R$", "inr": "₹",
}

# Cache daftar coin dari CoinGecko (refresh tiap sesi)
_coin_list_cache = {}

def load_coin_list():
    """Load semua coin dari CoinGecko ke cache untuk pencarian dinamis."""
    global _coin_list_cache
    if _coin_list_cache:
        return
    try:
        resp = requests.get(f"{COINGECKO_BASE}/coins/list", timeout=15)
        resp.raise_for_status()
        coins = resp.json()
        for coin in coins:
            symbol = coin["symbol"].lower()
            cid = coin["id"]
            name = coin["name"].lower()
            # Simpan: simbol → id (prioritaskan yang sudah ada di COIN_ALIASES)
            if symbol not in _coin_list_cache:
                _coin_list_cache[symbol] = cid
            # Juga simpan nama lengkap
            _coin_list_cache[name] = cid
        logger.info(f"Loaded {len(coins)} coins from CoinGecko")
    except Exception as e:
        logger.error(f"Failed to load coin list: {e}")

def resolve_coin_id(coin: str) -> str:
    """Resolve simbol/nama ke CoinGecko coin ID."""
    coin = coin.lower().strip()
    # Prioritas 1: alias manual (lebih akurat)
    if coin in COIN_ALIASES:
        return COIN_ALIASES[coin]
    # Prioritas 2: cache dari CoinGecko
    if coin in _coin_list_cache:
        return _coin_list_cache[coin]
    # Fallback: gunakan apa adanya
    return coin

def get_coin_price(coin_id: str, vs_currency: str = "usd") -> dict | None:
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

def get_fiat_rate(from_fiat: str, to_fiat: str) -> float | None:
    try:
        url = f"https://open.er-api.com/v6/latest/{from_fiat.upper()}"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if data.get("result") == "success" and to_fiat.upper() in data["rates"]:
            return data["rates"][to_fiat.upper()]
        return None
    except Exception as e:
        logger.error(f"Error fetching fiat rate: {e}")
        return None

def format_number(n: float, currency: str = "") -> str:
    symbol = FIAT_SYMBOL.get(currency.lower(), "")
    if n >= 1_000_000_000:
        return f"{symbol}{n:,.2f}"
    elif n >= 1_000:
        return f"{symbol}{n:,.2f}"
    elif n >= 1:
        return f"{symbol}{n:,.4f}"
    elif n >= 0.0001:
        return f"{symbol}{n:.6f}"
    else:
        return f"{symbol}{n:.10f}"

def get_coin_name_display(coin_input: str, coin_id: str) -> str:
    """Tampilkan nama coin yang lebih user-friendly."""
    if coin_input.upper() != coin_id.upper():
        return coin_input.upper()
    return coin_id.replace("-", " ").title()

# ==============================
# PARSER: Natural Message
# Format: <jumlah> <coin> [fiat]
# Contoh: "1 btc", "2 eth idr", "0.5 sol eur"
# ==============================
def parse_price_query(text: str):
    """
    Parse pesan natural menjadi (amount, coin, fiat).
    Mengembalikan None jika tidak cocok.
    """
    text = text.strip().lower()
    # Regex: angka (opsional) + spasi + coin + spasi opsional + fiat opsional
    pattern = r'^(\d+(?:[.,]\d+)?)\s+([a-z0-9]+)(?:\s+([a-z]+))?$'
    match = re.match(pattern, text)
    if not match:
        return None

    amount_str, coin_input, fiat_input = match.groups()
    amount = float(amount_str.replace(",", "."))
    fiat = fiat_input if fiat_input else "usd"

    # Validasi: fiat harus dikenal
    if fiat not in SUPPORTED_FIAT:
        return None

    # Validasi: coin tidak boleh berupa fiat
    if coin_input in SUPPORTED_FIAT:
        return None

    return amount, coin_input, fiat

async def handle_price_query(update: Update, amount: float, coin_input: str, fiat: str):
    """Proses query harga dan kirim hasilnya."""
    coin_id = resolve_coin_id(coin_input)
    data = get_coin_price(coin_id, fiat)

    if not data:
        # Coba load coin list dan retry sekali
        load_coin_list()
        coin_id = resolve_coin_id(coin_input)
        data = get_coin_price(coin_id, fiat)

    if not data or fiat not in data:
        await update.message.reply_text(
            f"❌ Coin `{coin_input.upper()}` tidak ditemukan.\n"
            f"Coba ketik nama lengkap coinnya, contoh: `1 bitcoin idr`\n"
            f"Atau cek daftar coin dengan `/list`",
            parse_mode="Markdown"
        )
        return

    price_per_unit = data[fiat]
    total = amount * price_per_unit
    change_24h = data.get(f"{fiat}_24h_change", 0) or 0
    market_cap = data.get(f"{fiat}_market_cap", 0) or 0

    change_emoji = "🟢" if change_24h >= 0 else "🔴"
    change_sign = "+" if change_24h >= 0 else ""
    coin_display = coin_input.upper()

    if amount == 1:
        # Tampilan harga 1 coin
        text = (
            f"💰 *{coin_display} / {fiat.upper()}*\n\n"
            f"💵 Harga: `{format_number(price_per_unit, fiat)}`\n"
            f"{change_emoji} 24h: `{change_sign}{change_24h:.2f}%`\n"
            f"📊 Market Cap: `{format_number(market_cap, fiat)}`\n\n"
            f"_Data dari CoinGecko_"
        )
    else:
        # Tampilan konversi jumlah tertentu
        text = (
            f"💰 *{amount:g} {coin_display} → {fiat.upper()}*\n\n"
            f"💵 Total: `{format_number(total, fiat)}`\n"
            f"📌 Harga per unit: `{format_number(price_per_unit, fiat)}`\n"
            f"{change_emoji} 24h: `{change_sign}{change_24h:.2f}%`\n\n"
            f"_Data dari CoinGecko_"
        )

    await update.message.reply_text(text, parse_mode="Markdown")

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
        "• `0.5 sol eur` → harga 0.5 SOL dalam Euro\n\n"
        "📋 `/list` — Daftar coin & simbol\n"
        "❓ `/help` — Bantuan lengkap\n"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    fiat_list = ", ".join(sorted(f.upper() for f in SUPPORTED_FIAT))
    text = (
        "📖 *Panduan Penggunaan Bot*\n\n"
        "*Format penulisan:*\n"
        "`<jumlah> <coin> [mata_uang]`\n\n"
        "*Contoh:*\n"
        "`1 btc` — harga 1 BTC dalam USD\n"
        "`2 eth` — harga 2 ETH dalam USD\n"
        "`1 btc idr` — harga 1 BTC dalam IDR\n"
        "`0.5 sol eur` — harga 0.5 SOL dalam EUR\n"
        "`10 bnb sgd` — harga 10 BNB dalam SGD\n"
        "`100 doge jpy` — harga 100 DOGE dalam JPY\n\n"
        f"*Mata uang fiat:*\n{fiat_list}\n\n"
        "*Default:* jika fiat tidak ditulis, otomatis USD\n\n"
        "📋 Ketik `/list` untuk melihat daftar coin"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def list_coins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    categories = {
        "🏆 Top Crypto": [
            ("BTC","Bitcoin"),("ETH","Ethereum"),("BNB","BNB"),("SOL","Solana"),
            ("XRP","Ripple"),("ADA","Cardano"),("DOGE","Dogecoin"),("TRX","Tron"),
            ("AVAX","Avalanche"),("DOT","Polkadot"),
        ],
        "🔷 Layer 2": [
            ("MATIC","Polygon"),("ARB","Arbitrum"),("OP","Optimism"),("IMX","Immutable X"),
        ],
        "🏦 DeFi": [
            ("UNI","Uniswap"),("AAVE","Aave"),("MKR","Maker"),("CAKE","PancakeSwap"),
            ("GMX","GMX"),("DYDX","dYdX"),
        ],
        "🤖 AI": [
            ("FET","Fetch.ai"),("RNDR","Render"),("WLD","Worldcoin"),("TAO","Bittensor"),
            ("GRT","The Graph"),("AGIX","SingularityNET"),
        ],
        "🎮 Gaming": [
            ("AXS","Axie Infinity"),("SAND","The Sandbox"),("MANA","Decentraland"),
            ("GALA","Gala"),("ENJ","Enjin"),
        ],
        "🐸 Meme": [
            ("SHIB","Shiba Inu"),("PEPE","Pepe"),("FLOKI","Floki"),("BONK","Bonk"),
            ("WIF","dogwifhat"),("BOME","Book of Meme"),
        ],
        "🔗 Infrastruktur": [
            ("LINK","Chainlink"),("FIL","Filecoin"),("AR","Arweave"),("HNT","Helium"),
            ("LTC","Litecoin"),("XMR","Monero"),("TON","Toncoin"),
        ],
    }

    lines = ["📋 *Daftar Coin yang Didukung*\n"]
    for cat, coins in categories.items():
        lines.append(f"\n*{cat}*")
        row = "  ".join(f"`{s}`" for s, _ in coins)
        lines.append(row)

    lines.append("\n💡 *Cara pakai:*")
    lines.append("`1 btc` atau `2 eth idr` atau `0.5 sol eur`")
    lines.append("\n_Coin lain juga bisa dicoba dengan nama/simbol CoinGecko-nya_")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

# ==============================
# MESSAGE HANDLER (Natural Input)
# ==============================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()

    # Abaikan pesan yang dimulai dengan /
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
    # Load coin list saat startup
    load_coin_list()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("list", list_coins))

    # Handler untuk pesan natural (1 btc, 2 eth idr, dst)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot berjalan...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    main()
