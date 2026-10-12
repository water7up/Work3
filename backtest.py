"""Honest backtest of a classic strategy on BTCUSDT perpetual: SMA crossover on 4h candles, long/short.

What makes it 'honest':
  * decisions on a closed candle, execution at the NEXT candle's open (no look-ahead)
  * taker fee + slippage on every position change, real funding payments on open positions
  * parameters chosen on the in-sample period only, then judged once on an untouched out-of-sample period
  * gross vs net shown side by side, so you see exactly how much costs eat

  python backtest.py            -> prints metrics and writes report/*.png + report/summary.md
"""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).parent
DATA, REPORT = ROOT / "data", ROOT / "report"
FEE, SLIP = 0.00055, 0.0002              # Bybit taker fee and assumed slippage, per side
SPLIT = "2024-07-01"                      # in-sample before, out-of-sample from here on
GRID = [(f, s) for f in (10, 20, 30, 50) for s in (50, 100, 150, 200) if f < s]

# palette (validated reference instance): slot 1 blue, slot 2 orange, slot 3 aqua; recessive ink/grid
C_NET, C_GROSS, C_HOLD = "#2a78d6", "#eb6834", "#1baf7a"
INK, MUTED, GRID_C, SURF = "#0b0b0b", "#52514e", "#e7e6e2", "#fcfcfb"


def load() -> tuple[pd.DataFrame, pd.Series]:
    k = pd.read_csv(DATA / "BTCUSDT_15m.csv").drop_duplicates("timestamp").sort_values("timestamp")
    k.index = pd.to_datetime(k.pop("timestamp"), unit="ms", utc=True)
    bars = k.resample("4h").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    f = pd.read_csv(DATA / "BTCUSDT_funding.csv").drop_duplicates("timestamp")
    fund = pd.Series(f["funding_rate"].values, index=pd.to_datetime(f["timestamp"], unit="ms", utc=True)).sort_index()
    return bars, fund


def run(bars: pd.DataFrame, fund: pd.Series, fast: int, slow: int) -> pd.DataFrame:
    c = bars["close"]
    signal = np.sign(c.rolling(fast).mean() - c.rolling(slow).mean()).fillna(0)
    pos = signal.shift(1).fillna(0)                      # decided on close of bar t-1, held during bar t
    ret = bars["open"].shift(-1) / bars["open"] - 1      # open(t) -> open(t+1): we trade at the open
    gross = (pos * ret).fillna(0)
    turnover = pos.diff().abs().fillna(pos.abs())       # 1 = open/close, 2 = flip long<->short
    cost = turnover * (FEE + SLIP)
    # funding settled inside (open t, open t+1] is paid by the position held during bar t:
    # longs pay positive rates, shorts receive them
    idx = bars.index.values
    f = fund[(fund.index > bars.index[0]) & (fund.index <= bars.index[-1] + pd.Timedelta("4h"))]
    slot = np.searchsorted(idx, f.index.values, side="left") - 1
    f_bar = pd.Series(np.bincount(slot, weights=f.values, minlength=len(idx))[:len(idx)], index=bars.index)
    funding = -pos * f_bar
    return pd.DataFrame({"pos": pos, "gross": gross, "cost": cost, "funding": funding,
                         "net": gross - cost + funding, "hold": ret.fillna(0)})


def metrics(r: pd.Series) -> dict:
    eq = (1 + r).cumprod()
    days = (r.index[-1] - r.index[0]).days or 1
    daily = (1 + r).resample("1D").prod() - 1
    return {"total": eq.iloc[-1] - 1, "cagr": eq.iloc[-1] ** (365 / days) - 1,
            "max_dd": (eq / eq.cummax() - 1).min(),
            "sharpe": daily.mean() / daily.std() * np.sqrt(365) if daily.std() > 0 else 0.0}


def style(ax, title):
    ax.set_facecolor(SURF)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID_C)
    ax.grid(axis="y", color=GRID_C, linewidth=0.8)
    ax.tick_params(colors=MUTED, labelsize=9)
    ax.set_title(title, loc="left", color=INK, fontsize=12, fontweight="bold", pad=12)


def plot_equity(res: pd.DataFrame, path: Path, title: str, split=None):
    fig, ax = plt.subplots(figsize=(10, 4.6), facecolor=SURF)
    style(ax, title)
    curves = [("Strategy, net of costs", res["net"], C_NET, "-"), ("Strategy, before costs", res["gross"], C_GROSS, "--"),
              ("Buy & hold BTC", res["hold"], C_HOLD, "-")]
    ends = []
    for label, r, color, ls in curves:
        eq = (1 + r).cumprod() * 100
        ax.plot(eq.index, eq.values, color=color, linewidth=2, linestyle=ls, label=label)
        ends.append([eq.iloc[-1], eq.index[-1]])
    # spread end labels so close values do not overlap (min gap = 4% of the y-range)
    lo, hi = ax.get_ylim(); gap = (hi - lo) * 0.04
    ends.sort(key=lambda e: e[0])
    ys = [e[0] for e in ends]
    for i in range(1, len(ys)):
        ys[i] = max(ys[i], ys[i - 1] + gap)
    for (v, t), y in zip(ends, ys):
        ax.annotate(f"{v:.0f}", (t, y), xytext=(6, 0), textcoords="offset points", color=INK, fontsize=9, va="center")
    if split is not None:
        ax.axvline(split, color=MUTED, linewidth=1, linestyle=":")
        ax.text(split, ax.get_ylim()[1], "  out-of-sample →", color=MUTED, fontsize=9, va="top")
    ax.set_ylabel("Equity, start = 100", color=MUTED, fontsize=9)
    ax.legend(frameon=False, fontsize=9, labelcolor=INK, loc="upper left")
    fig.tight_layout(); fig.savefig(path, dpi=150, facecolor=SURF); plt.close(fig)


def plot_costs(res: pd.DataFrame, path: Path):
    years = res.groupby(res.index.year)[["gross", "cost", "funding", "net"]].sum() * 100
    fig, ax = plt.subplots(figsize=(10, 4.2), facecolor=SURF)
    style(ax, "Where the edge goes: yearly return before costs vs after costs (%)")
    x = np.arange(len(years)); w = 0.36
    b1 = ax.bar(x - w / 2 - 0.01, years["gross"], w, color=C_GROSS, label="Before costs")
    b2 = ax.bar(x + w / 2 + 0.01, years["net"], w, color=C_NET, label="After fees, slippage & funding")
    for bars in (b1, b2):
        for b in bars:
            v = b.get_height()
            ax.annotate(f"{v:+.0f}", (b.get_x() + b.get_width() / 2, v), xytext=(0, 3 if v >= 0 else -11),
                        textcoords="offset points", ha="center", fontsize=8, color=INK)
    ax.axhline(0, color=MUTED, linewidth=1)
    ax.set_xticks(x, [str(y) for y in years.index])
    ax.legend(frameon=False, fontsize=9, labelcolor=INK, loc="upper right")
    fig.tight_layout(); fig.savefig(path, dpi=150, facecolor=SURF); plt.close(fig)


def main():
    REPORT.mkdir(exist_ok=True)
    bars, fund = load()
    ins, oos = bars[bars.index < SPLIT], bars[bars.index >= SPLIT]

    # 1) pick parameters on in-sample only
    scores = []
    for f, s in GRID:
        m = metrics(run(ins, fund, f, s)["net"])
        scores.append((m["sharpe"], f, s, m))
    scores.sort(reverse=True)
    _, fast, slow, m_ins = scores[0]

    # 2) judge once on out-of-sample (warm-up bars from in-sample so averages exist on day one)
    warm = bars[bars.index >= ins.index[-slow - 5]]
    res_oos = run(warm, fund, fast, slow)
    res_oos = res_oos[res_oos.index >= SPLIT]
    res_all = run(bars, fund, fast, slow)

    m_oos, m_oos_g, m_hold = metrics(res_oos["net"]), metrics(res_oos["gross"]), metrics(res_oos["hold"])
    trades = int((res_oos["pos"].diff().abs() > 0).sum())
    cost_share = res_oos["cost"].sum(), -res_oos["funding"].sum()

    plot_equity(res_all, REPORT / "equity_full.png",
                f"BTCUSDT 4h SMA {fast}/{slow} crossover: full period", split=pd.Timestamp(SPLIT, tz="UTC"))
    plot_equity(res_oos, REPORT / "equity_oos.png", "Out-of-sample only: the period the parameters never saw")
    plot_costs(res_all, REPORT / "yearly_costs.png")

    pct = lambda v: f"{v * 100:+.1f}%"
    lines = [
        f"# Backtest summary: BTCUSDT 4h SMA {fast}/{slow} crossover (long/short)",
        "",
        f"Parameters chosen on in-sample ({bars.index[0]:%Y-%m-%d} – {SPLIT}) out of {len(GRID)} combinations "
        f"by net Sharpe; judged once on out-of-sample ({SPLIT} – {bars.index[-1]:%Y-%m-%d}).",
        "",
        "| | In-sample (net) | Out-of-sample before costs | Out-of-sample net | Buy & hold (OOS) |",
        "|---|---|---|---|---|",
        f"| Total return | {pct(m_ins['total'])} | {pct(m_oos_g['total'])} | {pct(m_oos['total'])} | {pct(m_hold['total'])} |",
        f"| CAGR | {pct(m_ins['cagr'])} | {pct(m_oos_g['cagr'])} | {pct(m_oos['cagr'])} | {pct(m_hold['cagr'])} |",
        f"| Max drawdown | {pct(m_ins['max_dd'])} | {pct(m_oos_g['max_dd'])} | {pct(m_oos['max_dd'])} | {pct(m_hold['max_dd'])} |",
        f"| Sharpe | {m_ins['sharpe']:.2f} | {m_oos_g['sharpe']:.2f} | {m_oos['sharpe']:.2f} | {m_hold['sharpe']:.2f} |",
        "",
        f"Out-of-sample: {trades} position changes; fees+slippage cost {cost_share[0] * 100:.1f}% of equity, "
        f"funding cost {cost_share[1] * 100:+.1f}%.",
    ]
    (REPORT / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
