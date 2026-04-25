import requests
import time
from datetime import datetime

BOT_TOKEN = "8715230504:AAHncD3m3nhCAG-UxAuGS7btY1snweC5zvw"
CHAT_ID = "1058404514"
SYMBOL = "BTCUSDT"

last_signal = {"5m": None, "1h": None}

def send_telegram(msg):
    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={
        "chat_id": CHAT_ID,
        "text": msg,
        "parse_mode": "HTML"
    })

def get_klines(interval, limit=100):
    url = f"https://api.binance.com/api/v3/klines?symbol={SYMBOL}&interval={interval}&limit={limit}"
    data = requests.get(url, timeout=10).json()
    closes = [float(c[4]) for c in data]
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

    macd_cross_up = macd_prev < sig_prev and macd_now > sig_now
    macd_cross_down = macd_prev > sig_prev and macd_now < sig_now

    signal = None
    if rsi < 30 and macd_cross_up:
        signal = "COMPRA"
    elif rsi > 70 and macd_cross_down:
        signal = "VENTA"

    if signal and signal != last_signal[interval]:
        last_signal[interval] = signal
        emoji = "🟢" if signal == "COMPRA" else "🔴"
        msg = (
            f"{emoji} <b>SEÑAL DE {signal} - BTC/USDT</b>\n"
            f"⏱ Temporalidad: <b>{interval}</b>\n"
            f"💰 Precio: <b>${price:,.2f}</b>\n"
            f"📊 RSI 14: <b>{rsi:.1f}</b>\n"
            f"📈 MACD: <b>{macd_now:.2f}</b> | Señal: <b>{sig_now:.2f}</b>\n"
            f"🕐 {datetime.now().strftime('%H:%M:%S')}"
        )
        send_telegram(msg)
        print(f"[{interval}] Señal {signal} enviada — RSI: {rsi:.1f}")
    else:
        print(f"[{interval}] RSI: {rsi:.1f} | MACD: {macd_now:.2f} | Sin señal")

send_telegram("🤖 <b>Bot de señales BTC iniciado</b>\nMonitoreando RSI 14 + MACD en 5m y 1h")
print("Bot de señales Bitcoin iniciado. Ctrl+C para detener.")

check_5m_counter = 0
while True:
    try:
        check_signals("5m")
        check_5m_counter += 1
        if check_5m_counter >= 12:
            check_signals("1h")
            check_5m_counter = 0
        time.sleep(300)
    except KeyboardInterrupt:
        print("Bot detenido.")
        break
    except Exception as e:
        print(f"Error: {e}")
        time.sleep(30)
