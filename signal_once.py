import os, json, time
import ccxt, requests, pandas as pd

try:
    import feedparser
except ImportError:
    feedparser = None

EXCHANGE = "kraken"
QUOTE = "USD"
TOP_N = 30
ALWAYS_WATCH = ["QNT/USD", "SOL/USD"]
TIMEFRAME = "1h"
COOLDOWN = 4 * 3600
DANGER_ALERTS = {"QNT/USD": 216.0}
STABLES = {"USDT", "USDC", "DAI", "EUR", "GBP", "PYUSD", "USDG", "TUSD", "USDD"}
STATE_FILE = "state.json"

TG_TOKEN = os.environ.get("TG_TOKEN", "")
TG_CHAT = os.environ.get("TG_CHAT", "")
POS = ["partnership", "surge", "rally", "approval", "adoption", "launch", "gain"]
NEG = ["hack", "exploit", "lawsuit", "drop", "plunge", "ban", "dump", "fear", "sell-off"]


def telegram(text):
    print(text)
    if TG_TOKEN and TG_CHAT:
        requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                      data={"chat_id": TG_CHAT, "text": text}, timeout=15)


def load_state():
    try:
        return json.load(open(STATE_FILE))
    except Exception:
        return {}


def can_send(state, key):
    return time.time() - state.get(key, 0) > COOLDOWN


def indicators(df):
    d = df["c"].diff()
    g = d.clip(lower=0).rolling(14).mean()
    l = (-d.clip(upper=0)).rolling(14).mean()
    df["rsi"] = 100 - 100 / (1 + g / l)
    tr = pd.concat([df.h - df.l, (df.h - df.c.shift()).abs(),
                    (df.l - df.c.shift()).abs()], axis=1).max(axis=1)
    df["atr"] = tr.rolling(14).mean()
    return df


def news(base):
    if not feedparser:
        return 0, []
    try:
        url = f"https://news.google.com/rss/search?q={base}+crypto&hl=en"
        t = [e.title for e in feedparser.parse(url).entries[:8]]
    except Exception:
        return 0, []
    s = sum(any(w in x.lower() for w in POS) for x in t) \
        - sum(any(w in x.lower() for w in NEG) for x in t)
    return s, t[:2]


def watchlist(ex):
    rows = []
    for sym, t in ex.fetch_tickers().items():
        if not sym.endswith(f"/{QUOTE}") or ":" in sym:
            continue
        if sym.split("/")[0] in STABLES:
            continue
        rows.append((t.get("quoteVolume") or 0, sym))
    top = [s for _, s in sorted(rows, reverse=True)[:TOP_N]]
    return list(dict.fromkeys(ALWAYS_WATCH + top))


def analyze(ex, symbol):
    raw = ex.fetch_ohlcv(symbol, TIMEFRAME, limit=100)
    df = indicators(pd.DataFrame(raw, columns=["ts", "o", "h", "l", "c", "v"]))
    last = df.iloc[-1]
    price, rsi, atr = last.c, last.rsi, last.atr
    support, resistance = df.l.tail(48).min(), df.h.tail(48).max()
    base = symbol.split("/")[0]

    if price <= support + 0.8 * atr and rsi < 40:
        n, heads = news(base)
        if n >= 0:
            stop = support - atr
            return "BUY", price, (
                f"🟢 منطقة شراء — {symbol}\nالسعر: {price:.4g}\n"
                f"الدخول: {support:.4g} - {support + 0.8 * atr:.4g}\n"
                f"وقف الخسارة: {stop:.4g}\n"
                f"الهدف 1: {price + 1.5 * (price - stop):.4g} | الهدف 2: {resistance:.4g}\n"
                f"RSI: {rsi:.0f} | أخبار: {n:+d}"
                + ("\n📰 " + " | ".join(heads) if heads else "")
                + "\n\n(إشارة مساعدة فقط، مو ضمان)")
    if rsi > 70 or price >= resistance - 0.3 * atr:
        n, heads = news(base)
        return "SELL", price, (
            f"🔴 منطقة بيع/جني أرباح — {symbol}\nالسعر: {price:.4g}\n"
            f"المقاومة: {resistance:.4g}\nRSI: {rsi:.0f} | أخبار: {n:+d}"
            + ("\n📰 " + " | ".join(heads) if heads else "")
            + "\n\n(إشارة مساعدة فقط، مو ضمان)")
    return None, price, ""


def main():
    ex = getattr(ccxt, EXCHANGE)({"enableRateLimit": True})
    state = load_state()
    for symbol in watchlist(ex):
        try:
            sig, price, msg = analyze(ex, symbol)
            dz = DANGER_ALERTS.get(symbol)
            if dz and price <= dz * 1.03 and can_send(state, f"{symbol}|DANGER"):
                telegram(f"⚠️ خطر — {symbol} وصل {price:.4g}، قريب من {dz:.4g}")
                state[f"{symbol}|DANGER"] = time.time()
            if sig and can_send(state, f"{symbol}|{sig}"):
                telegram(msg)
                state[f"{symbol}|{sig}"] = time.time()
        except Exception as e:
            print(f"{symbol}: {e}")
    json.dump(state, open(STATE_FILE, "w"))


if __name__ == "__main__":
    main()
