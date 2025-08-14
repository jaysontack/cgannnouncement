import os
import re
import sys
import time
import requests
from datetime import datetime, timezone
from telethon import TelegramClient, events

# === Emoji support for Windows terminal ===
if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

# === TELEGRAM CREDENTIALS ===
api_id = 21103444
api_hash = '87108e6c04603ec6e955a03fd30df441'
session_name = 'tabersession'

# === CHANNEL MAP (source channel ID -> target channel ID) ===
channel_map = {
    -1001559069277: -1001458452380,  # CG Listing Alert
    -1002767464580: -1001458452380   # New Channel
}

# === IMAGE MAP ===
channel_image_map = {
    -1001559069277: 'cg.jpg',
    -1002767464580: 'cg.jpg'
}

# === EXTRACT FIELDS FROM MESSAGE ===
def extract_fields(text):
    print(f"[LOG] Extracting fields from message.")
    symbol = re.search(r'\$([A-Z0-9]{2,15})', text)
    ca = re.search(r'(?:CA|Ca|ca|Contract|contract)[^\w]{0,3}([a-zA-Z0-9]{35,})', text)
    chain = re.search(r'⛓️\s*Blockchain:\s*(.+)', text)
    tg = re.search(r'Telegram:\s*@?(\w+)', text)

    fields = {
        'contract': ca.group(1) if ca else None,
        'chain': chain.group(1).strip() if chain else 'Unknown',
        'chat': f"https://t.me/{tg.group(1)}" if tg else None,
        'symbol': symbol.group(1).upper() if symbol else 'TOKEN',
    }
    print(f"[LOG] Extracted fields: {fields}")
    return fields

# === GET DEX DATA ===
def get_dex_data(contract):
    try:
        print(f"[LOG] Fetching DEX data for: {contract}")
        url = f"https://api.dexscreener.com/latest/dex/search/?q={contract}"
        res = requests.get(url, timeout=10)
        data = res.json()
        if data.get("pairs"):
            return data["pairs"][0]
        return None
    except Exception as e:
        print(f"[ERROR] DEX API error: {e}")
        return None

def format_dollar(val):
    try:
        val = float(val)
        if val >= 1_000_000:
            return f"${val / 1_000_000:.2f}M"
        elif val >= 1_000:
            return f"${val / 1_000:.2f}K"
        return f"${val:.10f}"
    except:
        return "Unknown"

def format_change(val):
    try:
        icon = "🟢" if val >= 0 else "🔻"
        return f"{val:.2f}% {icon}"
    except:
        return "Unknown"

def get_fast_trade_link(chain):
    chain = chain.lower()
    if "solana" in chain:
        return "https://jup.ag/swap"
    elif "ethereum" in chain:
        return "https://app.uniswap.org"
    elif "binance" in chain or "bnb" in chain:
        return "https://pancakeswap.finance"
    elif "base" in chain:
        return "https://app.uniswap.org"
    elif "cardano" in chain:
        return "https://muesliswap.com"
    elif "hyperevm" in chain:
        return "https://hyperswap.xyz"
    elif "xrp" in chain:
        return "https://bithomp.com"
    else:
        return None

# === BUILD MESSAGE ===
def build_message(fields, dex):
    if dex:
        price = float(dex.get("priceUsd", 0))
        liquidity = float(dex.get("liquidity", {}).get("usd", 0))
        mcap = dex.get("marketCap") or 0
        pc = dex.get("priceChange", {})
        h1 = float(pc.get("h1", 0))
        h6 = float(pc.get("h6", 0))
        h24 = float(pc.get("h24", 0))
    else:
        price = liquidity = mcap = None
        h1 = h6 = h24 = None

    symbol = fields["symbol"]
    swap_link = get_fast_trade_link(fields["chain"])

    msg = f"<b>🚨 New Listing Alert — ${symbol} listed on CoinGecko</b>\n\n"
    msg += f"⛓️ <b>Chain:</b> {fields['chain']}\n"
    msg += f"🔗 <b>Contract:</b> <code>{fields['contract']}</code>\n\n"

    if swap_link:
        msg += f"⚡ <b>Fast Trade:</b> {swap_link}\n"

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
client = TelegramClient(session_name, api_id, api_hash)

@client.on(events.NewMessage(chats=list(channel_map.keys())))
async def handler(event):
    try:
        print(f"[LOG] New message received. Channel ID: {event.chat_id}")
        text = event.message.message
        origin_id = event.chat_id

        if origin_id not in channel_map:
            print("[LOG] This channel is not being monitored, skipping.")
            return

        target_id = channel_map[origin_id]  # Directly using channel ID
        print(f"[LOG] Target channel ID: {target_id}")
        image_path = channel_image_map.get(origin_id, 'cg.jpg')

        fields = extract_fields(text)
        if not fields or not fields["contract"]:
            print("[LOG] No contract found, skipping.")
            return

        dex = get_dex_data(fields["contract"])
        if not dex:
            print("[LOG] No DEX data found. Using only extracted message fields.")

        msg = build_message(fields, dex)

        # Download header image only if DEX data has one
        if dex and dex.get("info", {}).get("header"):
            header_url = dex["info"]["header"]
            print(f"[LOG] Downloading header image: {header_url}")
            try:
                res = requests.get(header_url, timeout=5)
                if res.status_code == 200:
                    with open("header_temp.jpg", "wb") as f:
                        f.write(res.content)
                    image_path = "header_temp.jpg"
            except Exception as e:
                print(f"[Image fallback] Header download failed: {e}")

        await client.send_file(
            target_id,
            image_path,
            caption=msg,
            parse_mode='html'
        )

        if image_path == "header_temp.jpg" and os.path.exists("header_temp.jpg"):
            os.remove("header_temp.jpg")

        print(f"✅ Sent: {fields['contract']}")
        print("POSTED_SUCCESS")

    except Exception as e:
        print(f"[ERROR] {e.__class__.__name__}: {e}")

# === START BOT ===
if __name__ == "__main__":
    while True:
        try:
            print("🚀 CG Bot is running...")
            client.start()
            client.run_until_disconnected()
        except Exception as e:
            print(f"❌ Bot crashed: {e}. Restarting in 5s...")
            time.sleep(5)