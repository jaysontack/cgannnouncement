import os
import re
import sys
import time
import requests
from datetime import datetime, timezone
from telethon import TelegramClient, events
from telethon.sessions import StringSession

# === Emoji support for Windows terminal ===
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
    except Exception:
        pass

# === TELEGRAM CREDENTIALS (ENV) ===
# Render > Environment Variables:
#   API_ID, API_HASH, SESSION_STRING
try:
    api_id = int(os.environ["API_ID"])
    api_hash = os.environ["API_HASH"]
    session_string = os.environ["SESSION_STRING"]
except KeyError as e:
    print(f"❌ ENV eksik: {e}. Lütfen API_ID / API_HASH / SESSION_STRING tanımlayın.", flush=True)
    raise SystemExit(1)

# === CHANNEL MAP (source -> target) ===
channel_map = {
    -1001559069277: -1001458452380,  # CG Listing Alert -> hedef kanal
    -1002767464580: -1001458452380,  # New Channel -> aynı hedef
    -1001292331458: -1001095707884   # CMC Channel -> yeni hedef
}

# === IMAGE MAP (kanal -> fallback görsel) ===
channel_image_map = {
    -1001559069277: 'cg.jpg',
    -1002767464580: 'cg.jpg',
    -1001292331458: 'cmc.jpg'
}

# === SOURCE NAME MAP (başlık için) ===
channel_source_name_map = {
    -1001559069277: "CoinGecko",
    -1002767464580: "CoinGecko",
    -1001292331458: "CoinMarketCap"
}

# === EXTRACT FIELDS FROM MESSAGE ===
def extract_fields(text: str):
    print(f"[LOG] Extracting fields from message.", flush=True)
    symbol = re.search(r'\$([A-Z0-9]{2,15})', text or "")
    ca = re.search(r'(?:CA|Ca|ca|Contract|contract)[^\w]{0,3}([a-zA-Z0-9]{35,})', text or "")
    chain = re.search(r'⛓️\s*Blockchain:\s*(.+)', text or "")
    tg = re.search(r'Telegram:\s*@?(\w+)', text or "")

    fields = {
        'contract': ca.group(1) if ca else None,
        'chain': chain.group(1).strip() if chain else 'Unknown',
        'chat': f"https://t.me/{tg.group(1)}" if tg else None,
        'symbol': symbol.group(1).upper() if symbol else 'TOKEN',
    }
    print(f"[LOG] Extracted fields: {fields}", flush=True)
    return fields

# === GET DEX DATA ===
REQ_HEADERS = {"User-Agent": "Mozilla/5.0 (RenderBot/1.0)"}
def get_dex_data(contract: str):
    try:
        print(f"[LOG] Fetching DEX data for: {contract}", flush=True)
        url = f"https://api.dexscreener.com/latest/dex/search/?q={contract}"
        res = requests.get(url, headers=REQ_HEADERS, timeout=10)
        data = res.json()
        if data.get("pairs"):
            return data["pairs"][0]
        return None
    except Exception as e:
        print(f"[ERROR] DEX API error: {e}", flush=True)
        return None

def format_dollar(val):
    try:
        val = float(val or 0)
        if val >= 1_000_000:
            return f"${val / 1_000_000:.2f}M"
        elif val >= 1_000:
            return f"${val / 1_000:.2f}K"
        return f"${val:.10f}" if val < 1 else f"${val:.2f}"
    except:
        return "Unknown"

def format_change(val):
    try:
        v = float(val or 0)
        icon = "🟢" if v >= 0 else "🔻"
        return f"{v:.2f}% {icon}"
    except:
        return "Unknown"

def get_fast_trade_link(chain: str):
    c = (chain or "").lower()
    if "solana" in c:   return "https://jup.ag/swap"
    if "ethereum" in c: return "https://app.uniswap.org"
    if "binance" in c or "bnb" in c: return "https://pancakeswap.finance"
    if "base" in c:     return "https://app.uniswap.org"
    if "cardano" in c:  return "https://muesliswap.com"
    if "hyperevm" in c: return "https://hyperswap.xyz"
    if "xrp" in c:      return "https://bithomp.com"
    return None

# === BUILD MESSAGE ===
def build_message(fields, dex, origin_id):
    source_name = channel_source_name_map.get(origin_id, "Unknown Source")
    symbol = fields["symbol"]
    swap_link = get_fast_trade_link(fields["chain"])

    msg = f"<b>🚨 New Listing Alert — ${symbol} listed on {source_name}</b>\n\n"
    msg += f"⛓️ <b>Chain:</b> {fields['chain']}\n"
    msg += f"🔗 <b>Contract:</b> <code>{fields['contract']}</code>\n\n"

    if swap_link:
        msg += f"⚡ <b>Fast Trade:</b> {swap_link}\n"

    if dex:  # ✅ DEX datası varsa market bilgilerini ekle
        price = float(dex.get("priceUsd", 0) or 0)
        liquidity = float((dex.get("liquidity") or {}).get("usd", 0) or 0)
        mcap = dex.get("marketCap") or dex.get("fdv") or 0
        pc = dex.get("priceChange") or {}
        h1  = float(pc.get("h1", 0) or 0)
        h6  = float(pc.get("h6", 0) or 0)
        h24 = float(pc.get("h24", 0) or 0)

        msg += f"\n💵 <b>Market Cap:</b> {format_dollar(mcap)}"
        msg += f"\n💰 <b>Price:</b> {format_dollar(price)}"
        msg += f"\n💧 <b>Liquidity:</b> {format_dollar(liquidity)}"
        msg += f"\n📊 <b>1h:</b> {format_change(h1)}"
        msg += f"\n🕕 <b>6h:</b> {format_change(h6)}"
        msg += f"\n🕒 <b>24h:</b> {format_change(h24)}"

    if fields.get("chat"):
        msg += f"\n\n💬 <b>Chat:</b> {fields['chat']}"

    return msg

# === TELEGRAM CLIENT ===
client = TelegramClient(StringSession(session_string), api_id, api_hash)

@client.on(events.NewMessage(chats=list(channel_map.keys())))
async def handler(event):
    try:
        print(f"[LOG] New message received. Channel ID: {event.chat_id}", flush=True)
        text = event.message.message or ""
        origin_id = event.chat_id

        if origin_id not in channel_map:
            print("[LOG] This channel is not being monitored, skipping.", flush=True)
            return

        target_id = channel_map[origin_id]
        print(f"[LOG] Target channel ID: {target_id}", flush=True)
        image_path = channel_image_map.get(origin_id, 'cg.jpg')

        fields = extract_fields(text)
        if not fields or not fields.get("contract"):
            print("[LOG] No contract found, skipping.", flush=True)
            return

        dex = get_dex_data(fields["contract"])
        if not dex:
            print("[LOG] No DEX data found, posting without market info.", flush=True)

        msg = build_message(fields, dex, origin_id)

        # Header görseli varsa indir; yoksa fallback
        if dex and (dex.get("info") or {}).get("header"):
            header_url = dex["info"]["header"]
            print(f"[LOG] Downloading header image: {header_url}", flush=True)
            try:
                res = requests.get(header_url, headers=REQ_HEADERS, timeout=5)
                if res.status_code == 200:
                    with open("header_temp.jpg", "wb") as f:
                        f.write(res.content)
                    image_path = "header_temp.jpg"
                else:
                    print(f"[LOG] Header indirilemedi (HTTP {res.status_code}), fallback kullanılacak.", flush=True)
            except Exception as e:
                print(f"[Image fallback] Header download failed: {e}", flush=True)

        await client.send_file(
            target_id,
            image_path,
            caption=msg,
            parse_mode='html'
        )

        if image_path == "header_temp.jpg" and os.path.exists("header_temp.jpg"):
            os.remove("header_temp.jpg")

        print(f"✅ Sent: {fields['contract']}", flush=True)
        print("POSTED_SUCCESS", flush=True)

    except Exception as e:
        print(f"[ERROR] {e.__class__.__name__}: {e}", flush=True)

# === START BOT ===
if __name__ == "__main__":
    while True:
        try:
            print("🚀 CG/CMC Bot is running...", flush=True)
            client.start()
            client.run_until_disconnected()
        except Exception as e:
            print(f"❌ Bot crashed: {e}. Restarting in 5s...", flush=True)
            time.sleep(5)
