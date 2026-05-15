import requests
import time
import hmac
import hashlib
import json
import os
from datetime import datetime

# ── Config ───────────────────────────────────────────────────────────────
ACCESS_ID  = os.getenv("COINEX_ACCESS_ID",  "D05298077E764F3D9BE7DD729C4ADEFA")
SECRET_KEY = os.getenv("COINEX_SECRET_KEY", "224E866F9CDB76B3B3F0C3AD6AF841F50334EE7A740AC591")
BOT_TOKEN  = os.getenv("TELEGRAM_BOT_TOKEN","8715230504:AAHncD3m3nhCAG-UxAuGS7btY1snweC5zvw")
CHAT_IDS   = ["1058404514", "679685918", "8793813161"]

MARKET          = "BTCUSDT"
BASE_URL        = "https://api.coinex.com"
POSITION_FILE   = "position.json"

LEVERAGE        = 10
STOP_LOSS_PCT   = 0.025   # 2.5% en precio → 25% en margen
TAKE_PROFIT_PCT = 0.05    # 5% en precio  → 50% en margen
CAPITAL_PCT     = 0.05    # 5% del USDT disponible como margen

# ── Telegram ─────────────────────────────────────────────────────────────
def send_telegram(msg):
    for chat_id in CHAT_IDS:
        try:
            requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"},
                timeout=10
            )
        except Exception as e:
            print(f"[Telegram error {chat_id}] {e}")

# ── CoinEx API ────────────────────────────────────────────────────────────
def coinex_get(path, params=None):
    timestamp = str(int(time.time() * 1000))
    query = ""
    if params:
        query = "?" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    to_sign = f"GET{path}{query}{timestamp}"
    sig = hmac.new(SECRET_KEY.encode(), to_sign.encode(), hashlib.sha256).hexdigest()
    headers = {"X-COINEX-KEY": ACCESS_ID, "X-COINEX-SIGN": sig, "X-COINEX-TIMESTAMP": timestamp}
    r = requests.get(f"{BASE_URL}{path}{query}", headers=headers, timeout=10)
    return r.json()

def coinex_post(path, body):
    timestamp = str(int(time.time() * 1000))
    body_str = json.dumps(body, separators=(",", ":"))
    to_sign = f"POST{path}{body_str}{timestamp}"
    sig = hmac.new(SECRET_KEY.encode(), to_sign.encode(), hashlib.sha256).hexdigest()
    headers = {
        "X-COINEX-KEY": ACCESS_ID,
        "X-COINEX-SIGN": sig,
        "X-COINEX-TIMESTAMP": timestamp,
        "Content-Type": "application/json"
    }
    r = requests.post(f"{BASE_URL}{path}", headers=headers, data=body_str, timeout=10)
    return r.json()

def get_klines(period="5min", limit=100):
    params = {"limit": limit, "market": MARKET, "period": period}
    data = coinex_get("/v2/futures/kline", params)
    if data.get("code") != 0:
        raise Exception(f"klines error: {data}")
    candles = sorted(data["data"], key=lambda c: c["created_at"])
    return [float(c["close"]) for c in candles]

def get_futures_balance():
    data = coinex_get("/v2/assets/futures/balance")
    if data.get("code") != 0:
        raise Exception(f"balance error: {data}")
    return {item["ccy"]: float(item["available"]) for item in (data["data"] or [])}

def set_leverage():
    data = coinex_post("/v2/futures/adjust-position-leverage", {
        "market": MARKET,
        "market_type": "FUTURES",
        "leverage": LEVERAGE,
        "margin_mode": "isolated"
    })
    if data.get("code") != 0:
        raise Exception(f"set_leverage error: {data}")
    print(f"[FUTURES] Apalancamiento configurado: {LEVERAGE}x isolated")

def place_futures_order(side, btc_amount):
    return coinex_post("/v2/futures/order", {
        "market": MARKET,
        "market_type": "FUTURES",
        "side": side,
        "type": "market",
        "amount": f"{btc_amount:.4f}"
    })

def place_futures_close():
    return coinex_post("/v2/futures/close-position", {
        "market": MARKET,
        "market_type": "FUTURES",
        "type": "market"
    })

# ── Indicadores ───────────────────────────────────────────────────────────
def calc_rsi(closes, period=14):
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i-1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100
    return 100 - (100 / (1 + avg_gain / avg_loss))

def calc_ema(data, period):
    ema = [sum(data[:period]) / period]
    k = 2 / (period + 1)
    for price in data[period:]:
        ema.append(price * k + ema[-1] * (1 - k))
    return ema

def calc_macd(closes):
    ema12 = calc_ema(closes, 12)
    ema26 = calc_ema(closes, 26)
    n = min(len(ema12), len(ema26))
    macd = [ema12[-n+i] - ema26[i] for i in range(n)]
    signal = calc_ema(macd, 9)
    return macd[-1], macd[-2], signal[-1], signal[-2]

# ── Posición persistida ───────────────────────────────────────────────────
def load_position():
    try:
        with open(POSITION_FILE) as f:
            return json.load(f)
    except:
        return None

def save_position(pos):
    if pos is None:
        try:
            os.remove(POSITION_FILE)
        except:
            pass
    else:
        with open(POSITION_FILE, "w") as f:
            json.dump(pos, f)

# ── Trades ────────────────────────────────────────────────────────────────
def open_trade(direction, price, rsi, macd_now):
    balance = get_futures_balance()
    usdt = balance.get("USDT", 0)
    if usdt < 5:
        print(f"[TRADE] USDT insuficiente: {usdt:.2f}")
        return

    margin     = usdt * CAPITAL_PCT
    btc_amount = (margin * LEVERAGE) / price
    side       = "buy" if direction == "long" else "sell"

    result = place_futures_order(side, btc_amount)
    if result.get("code") != 0:
        print(f"[TRADE] Error apertura {direction}: {result}")
        send_telegram(f"⚠️ <b>Error al abrir {direction}</b>\n{result.get('message')}")
        return

    order         = result["data"]
    filled_amount = float(order.get("filled_amount", btc_amount))
    filled_value  = float(order.get("filled_value", margin * LEVERAGE))
    avg_price     = filled_value / filled_amount if filled_amount > 0 else price

    if direction == "long":
        stop_loss   = avg_price * (1 - STOP_LOSS_PCT)
        take_profit = avg_price * (1 + TAKE_PROFIT_PCT)
        emoji = "🟢"
        label = "LONG"
    else:
        stop_loss   = avg_price * (1 + STOP_LOSS_PCT)
        take_profit = avg_price * (1 - TAKE_PROFIT_PCT)
        emoji = "🔴"
        label = "SHORT"

    save_position({
        "direction":   direction,
        "entry_price": avg_price,
        "amount_btc":  filled_amount,
        "margin_usdt": margin,
        "stop_loss":   stop_loss,
        "take_profit": take_profit,
        "entry_time":  datetime.now().isoformat()
    })

    send_telegram(
        f"{emoji} <b>{label} ABIERTO - BTC/USDT FUTUROS {LEVERAGE}x</b>\n"
        f"💰 Entrada: <b>${avg_price:,.2f}</b>\n"
        f"₿ Tamaño: <b>{filled_amount:.4f} BTC</b>\n"
        f"💵 Margen: <b>${margin:.2f} USDT</b>\n"
        f"🛑 Stop Loss: <b>${stop_loss:,.2f}</b>\n"
        f"🎯 Take Profit: <b>${take_profit:,.2f}</b>\n"
        f"📊 RSI: <b>{rsi:.1f}</b> | MACD: <b>{macd_now:.2f}</b>\n"
        f"🕐 {datetime.now().strftime('%H:%M:%S')}"
    )
    print(f"[TRADE] {label} abierto: {filled_amount:.4f} BTC @ ${avg_price:,.2f} | Margen: ${margin:.2f}")

def close_trade(pos, price, reason):
    result = place_futures_close()
    if result.get("code") != 0:
        print(f"[TRADE] Error cierre: {result}")
        send_telegram(f"⚠️ <b>Error al cerrar posición</b>\n{result.get('message')}")
        return

    direction = pos.get("direction", "long")
    if direction == "long":
        pnl_usdt = pos["amount_btc"] * (price - pos["entry_price"])
    else:
        pnl_usdt = pos["amount_btc"] * (pos["entry_price"] - price)

    price_chg_pct = (price - pos["entry_price"]) / pos["entry_price"] * 100
    pnl_on_margin = pnl_usdt / pos["margin_usdt"] * 100
    emoji         = "✅" if pnl_usdt >= 0 else "❌"
    label         = "LONG" if direction == "long" else "SHORT"

    send_telegram(
        f"{emoji} <b>{label} CERRADO - {reason}</b>\n"
        f"💰 Salida: <b>${price:,.2f}</b>\n"
        f"📥 Entrada: <b>${pos['entry_price']:,.2f}</b>\n"
        f"📊 Movimiento: <b>{price_chg_pct:+.2f}%</b>\n"
        f"{'📈' if pnl_usdt >= 0 else '📉'} PnL sobre margen: <b>{pnl_on_margin:+.2f}% (${pnl_usdt:+.2f})</b>\n"
        f"🕐 {datetime.now().strftime('%H:%M:%S')}"
    )
    print(f"[TRADE] {label} cerrado @ ${price:,.2f} | PnL: {pnl_on_margin:+.2f}%")
    save_position(None)

# ── Loop principal ────────────────────────────────────────────────────────
def run():
    set_leverage()
    send_telegram(
        f"🤖 <b>Bot de trading BTC iniciado</b>\n"
        f"Modo: Futuros {LEVERAGE}x isolated | Long + Short\n"
        f"Long: RSI &lt; 35 + MACD cruce alcista\n"
        f"Short: RSI &gt; 65 + MACD cruce bajista\n"
        f"Margen: {CAPITAL_PCT*100:.0f}% | SL: {STOP_LOSS_PCT*100:.1f}% | TP: {TAKE_PROFIT_PCT*100:.1f}%"
    )
    print("Bot iniciado.")
    check_1h_counter = 0

    while True:
        try:
            closes_5m = get_klines("5min")
            rsi       = calc_rsi(closes_5m)
            macd_now, macd_prev, sig_now, sig_prev = calc_macd(closes_5m)
            price     = closes_5m[-1]

            macd_cross_up   = macd_prev < sig_prev and macd_now > sig_now
            macd_cross_down = macd_prev > sig_prev and macd_now < sig_now

            pos = load_position()

            if pos:
                direction = pos.get("direction", "long")
                if direction == "long":
                    price_chg = (price - pos["entry_price"]) / pos["entry_price"] * 100
                    print(f"[5m] LONG abierto | Precio: ${price:,.2f} | {price_chg:+.2f}% | RSI: {rsi:.1f}")
                    if price <= pos["stop_loss"]:
                        close_trade(pos, price, "STOP LOSS")
                    elif price >= pos["take_profit"]:
                        close_trade(pos, price, "TAKE PROFIT")
                    elif macd_cross_down:
                        close_trade(pos, price, "SEÑAL MACD BAJISTA")
                else:
                    price_chg = (pos["entry_price"] - price) / pos["entry_price"] * 100
                    print(f"[5m] SHORT abierto | Precio: ${price:,.2f} | {price_chg:+.2f}% | RSI: {rsi:.1f}")
                    if price >= pos["stop_loss"]:
                        close_trade(pos, price, "STOP LOSS")
                    elif price <= pos["take_profit"]:
                        close_trade(pos, price, "TAKE PROFIT")
                    elif macd_cross_up:
                        close_trade(pos, price, "SEÑAL MACD ALCISTA")
            else:
                print(f"[5m] RSI: {rsi:.1f} | MACD: {macd_now:.4f} | Precio: ${price:,.2f}")
                if rsi < 35 and macd_cross_up:
                    open_trade("long", price, rsi, macd_now)
                elif rsi > 65 and macd_cross_down:
                    open_trade("short", price, rsi, macd_now)

            check_1h_counter += 1
            if check_1h_counter >= 12:
                check_1h_counter = 0
                closes_1h = get_klines("1hour")
                rsi_1h    = calc_rsi(closes_1h)
                macd_1h, _, _, _ = calc_macd(closes_1h)
                print(f"[1h] RSI: {rsi_1h:.1f} | MACD: {macd_1h:.4f}")

            time.sleep(300)

        except KeyboardInterrupt:
            print("Bot detenido.")
            break
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(30)

if __name__ == "__main__":
    run()
