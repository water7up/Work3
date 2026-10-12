"""Download BTCUSDT perpetual 15m candles and funding history from Bybit's public API into ./data."""
import csv, time
from pathlib import Path
import requests

API = "https://api.bybit.com/v5/market"
OUT = Path(__file__).parent / "data"
START = int(time.mktime((2021, 10, 1, 0, 0, 0, 0, 0, 0))) * 1000


def klines(symbol="BTCUSDT", interval="15"):
    rows, t = {}, START
    while True:
        r = requests.get(f"{API}/kline", params={"category": "linear", "symbol": symbol, "interval": interval,
                                                "start": t, "limit": 1000}, timeout=30).json()
        lst = r["result"]["list"]
        if not lst:
            break
        for x in lst:
            rows[int(x[0])] = x[:5]
        nxt = max(rows) + 15 * 60_000
        if nxt <= t:
            break
        t = nxt
        time.sleep(0.1)
    with open(OUT / f"{symbol}_15m.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["timestamp", "open", "high", "low", "close"])
        w.writerows(rows[k] for k in sorted(rows))


def funding(symbol="BTCUSDT"):
    rows, end = {}, int(time.time() * 1000)
    while end > START:
        lst = requests.get(f"{API}/funding/history", params={"category": "linear", "symbol": symbol,
                                                            "endTime": end, "limit": 200}, timeout=30).json()["result"]["list"]
        if not lst:
            break
        for x in lst:
            rows[int(x["fundingRateTimestamp"])] = x["fundingRate"]
        end = min(rows) - 1
        time.sleep(0.1)
    with open(OUT / f"{symbol}_funding.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["timestamp", "funding_rate"])
        w.writerows((k, rows[k]) for k in sorted(rows) if k >= START)


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    klines(); funding()
    print("saved to", OUT)
