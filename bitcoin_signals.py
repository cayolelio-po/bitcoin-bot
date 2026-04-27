import requests
import time
from datetime import datetime

BOT_TOKEN = "8715230504:AAHncD3m3nhCAG-UxAuGS7btY1snweC5zvw"
CHAT_ID = "1058404514"
SYMBOL = "BTCUSDT"

last_signal = {
    "5m":  {"rsi": None, "macd": None},
    "1h":  {"rsi": None, "macd": None}
}

def send_telegram(msg):
    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={
        "chat_id": CHAT_ID,
        "text": msg,
        "parse_mode": "HTML"
    })

def get_klines(interval, limit=100):
    granularity = 300 if interval == "5m" else 3600
    url = f"https://api.exchange.coinbase.com/products/BTC-USD/candles?granularity={granularity}"
    data = requests.get(url, timeout=10).json()
    closes = [float(c[4]) for c in reversed(data[:limit])]
    return closes

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
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calc_ema(data, period):
    ema = [sum(data[:period]) / period]
    k = 2 / (period + 1)
    for price in data[period:]:
        ema.append(price * k + ema[-1] * (1 - k))
    return ema

def calc_macd(closes):
    ema12 = calc_ema(closes, 12)
    ema26 = calc_ema(closes, 26)
    min_len = min(len(ema12), len(ema26))
    macd_line = [ema12[-min_len+i] - ema26[i] for i in range(min_len)]
    signal_line = calc_ema(macd_line, 9)
    return macd_line[-1], macd_line[-2], signal_line[-1], signal_line[-2]

def check_signals(interval):
    closes = get_klines(interval)
    rsi = calc_rsi(closes)
    macd_now, macd_prev, sig_now, sig_prev = calc_macd(closes)
    price = closes[-1]

    # --- Señal RSI ---
    if rsi < 30 and last_signal[interval]["rsi"] != "SOBREVENTA":
        last_signal[interval]["rsi"] = "SOBREVENTA"
        send_telegram(
            f"📊 <b>RSI SOBREVENTA - BTC/USDT</b>\n"
            f"⏱ Temporalidad: <b>{interval}</b>\n"
            f"💰 Precio: <b>${price:,.2f}</b>\n"
            f"📉 RSI 14: <b>{rsi:.1f}</b> (por debajo de 30)\n"
            f"🕐 {datetime.now().strftime('%H:%M:%S')}"
        )
        print(f"[{interval}] RSI sobreventa enviado — RSI: {rsi:.1f}")
    elif rsi > 70 and last_signal[interval]["rsi"] != "SOBRECOMPRA":
        last_signal[interval]["rsi"] = "SOBRECOMPRA"
        send_telegram(
            f"📊 <b>RSI SOBRECOMPRA - BTC/USDT</b>\n"
            f"⏱ Temporalidad: <b>{interval}</b>\n"
            f"💰 Precio: <b>${price:,.2f}</b>\n"
            f"📈 RSI 14: <b>{rsi:.1f}</b> (por encima de 70)\n"
            f"🕐 {datetime.now().strftime('%H:%M:%S')}"
        )
        print(f"[{interval}] RSI sobrecompra enviado — RSI: {rsi:.1f}")
    elif 30 <= rsi <= 70:
        last_signal[interval]["rsi"] = None

    # --- Señal MACD ---
    macd_cross_up = macd_prev < sig_prev and macd_now > sig_now
    macd_cross_down = macd_prev > sig_prev and macd_now < sig_now

    if macd_cross_up and last_signal[interval]["macd"] != "CRUCE_ARRIBA":
        last_signal[interval]["macd"] = "CRUCE_ARRIBA"
        send_telegram(
            f"📈 <b>MACD CRUCE ALCISTA - BTC/USDT</b>\n"
            f"⏱ Temporalidad: <b>{interval}</b>\n"
            f"💰 Precio: <b>${price:,.2f}</b>\n"
            f"📊 RSI 14: <b>{rsi:.1f}</b>\n"
            f"⚡ MACD: <b>{macd_now:.2f}</b> cruza sobre señal: <b>{sig_now:.2f}</b>\n"
            f"🕐 {datetime.now().strftime('%H:%M:%S')}"
        )
        print(f"[{interval}] MACD cruce alcista enviado")
    elif macd_cross_down and last_signal[interval]["macd"] != "CRUCE_ABAJO":
        last_signal[interval]["macd"] = "CRUCE_ABAJO"
        send_telegram(
            f"📉 <b>MACD CRUCE BAJISTA - BTC/USDT</b>\n"
            f"⏱ Temporalidad: <b>{interval}</b>\n"
            f"💰 Precio: <b>${price:,.2f}</b>\n"
            f"📊 RSI 14: <b>{rsi:.1f}</b>\n"
            f"⚡ MACD: <b>{macd_now:.2f}</b> cruza bajo señal: <b>{sig_now:.2f}</b>\n"
            f"🕐 {datetime.now().strftime('%H:%M:%S')}"
        )
        print(f"[{interval}] MACD cruce bajista enviado")

    print(f"[{interval}] RSI: {rsi:.1f} | MACD: {macd_now:.2f} | Señal MACD: {sig_now:.2f}")

send_telegram("🤖 <b>Bot de señales BTC iniciado</b>\nMonitoreando RSI 14 + MACD en 5m y 1h (señales independientes)")
print("Bot de señales Bitcoin iniciado.")

while True:
    try:
        check_signals("5m")
        check_signals("1h")
        time.sleep(300)
    except KeyboardInterrupt:
        print("Bot detenido.")
        break
    except Exception as e:
        print(f"Error: {e}")
        time.sleep(30)
