#!/usr/bin/env python3
"""market.py - prices, breadth, calendar and options helpers for the earnings hunt. Commands:
mood | breadth [--vs SNAPFILE] [--html OUT] [--asof DATE] | ext SYMS | earnings DATE [MIN_B] | email BODY TABLE OUT
| move SYM DATE bmo|amc | price "SYM:benefit|suffer:SECTION,..." RUNTYPE | score FILE | rel SYMS DATE
| queue FROM TO [MIN_B] | revs SYMS | why SYMS DATE | lint BODY | watch FILE"""
import csv, io, json, sys, time, urllib.request, datetime as dt
from zoneinfo import ZoneInfo
ET = ZoneInfo("America/New_York")
UA = {"User-Agent": "Mozilla/5.0"}
WINDOWS = (5, 20, 50, 100, 150, 200)
SECTORS = ["Consumer Discretionary", "Consumer Staples", "Energy", "Financials", "Health Care", "Industrials",
  "Information Technology", "Materials", "Real Estate", "Communication Services", "Utilities"]
SECTOR_FUNDS = {"XLY": "Consumer Discretionary", "XLP": "Consumer Staples", "XLE": "Energy", "XLF": "Financials",
    "XLV": "Health Care", "XLI": "Industrials", "XLK": "Information Technology", "XLB": "Materials",
    "XLRE": "Real Estate", "XLC": "Communication Services", "XLU": "Utilities"}
PAIRS = [("SPHB", "SPLV", "high-beta (jumpy) stocks vs low-volatility stocks"),
  ("IWM", "SPY", "small companies vs large companies"),
  ("RSP", "SPY", "the average S&P 500 stock vs the biggest ones"),
  ("XLY", "XLP", "discretionary (wants) vs staples (needs)"),
  ("XLK", "XLU", "tech vs utilities")]
CONTEXT = {"TLT": "long-term Treasury bonds (up = yields falling)", "USO": "oil", "GLD": "gold", "UUP": "US dollar"}
TMAP = {"time-pre-market": "before the open", "time-after-hours": "after the close"}

def get(url, tries=3):
 err = None
 for i in range(tries):
  try:
   return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40).read()
  except Exception as e:
   err = e; time.sleep(2 + 3 * i)
 raise err

def now_et():
 return dt.datetime.now(ET)

def session_open(t):
 return t.weekday() < 5 and dt.time(9, 30) <= t.time() < dt.time(16, 0)

def daily(symbols, rng="1y"):
 out = {}
 for i in range(0, len(symbols), 20):
  chunk = symbols[i:i + 20]
  url = ("https://query1.finance.yahoo.com/v8/finance/spark?symbols=" + ",".join(chunk)
   + f"&range={rng}&interval=1d")
  try:
   d = json.loads(get(url))
  except Exception as e:
   print(f"# price chunk {i // 20} failed: {e}", file=sys.stderr); continue
  for s, v in d.items():
   if not v or not v.get("close"): continue
   out[s] = [(dt.datetime.fromtimestamp(t, ET).date(), c)
     for t, c in zip(v["timestamp"], v["close"]) if c is not None]
  time.sleep(0.4)
 return out

def latest_full(data, share=0.9):
 from collections import Counter
 cnt = Counter(d for v in data.values() for d in {p[0] for p in v})
 need = share * len(data)
 return max(d for d, k in cnt.items() if k >= need)

def stamp(data):
 t = now_et()
 last = latest_full(data)
 live = session_open(t) and last == t.date()
 label = f"live at {t:%H:%M} ET, {t:%b %d}" if live else f"close of {last:%b %d}"
 warn = ""
 if session_open(t) and last != t.date():
  warn = "WARNING: today's live prices are missing; figures are as of the prior close."
 elif t.weekday() < 5 and t.time() >= dt.time(16, 0) and last < t.date():
  warn = f"WARNING: today's closing prices are not in the data yet; figures are as of the close of {last:%b %d}."
 return last, live, label, warn

def pct(a, b):
 return 100 * (a / b - 1)

# ---------------- mood ----------------
def mood():
 syms = sorted({s for p in PAIRS for s in p[:2]} | set(SECTOR_FUNDS) | set(CONTEXT))
 data = daily(syms, "3mo")
 last, live, label, warn = stamp(data)
 print(f"Market mood, {label} (change vs prior close)")
 if warn: print(warn)
 ch = {}
 for s, pts in data.items():
  if len(pts) >= 2 and pts[-1][0] == last: ch[s] = pct(pts[-1][1], pts[-2][1])
 miss = sorted(set(syms) - set(ch))
 if miss: print("Missing a price for " + f"{last:%b %d}" + ": " + ", ".join(miss) + " (left out)")
 print("\nPairs (positive gap = the first, riskier group is ahead = aggressive):")
 score = 0
 for a, b, desc in PAIRS:
  if a in ch and b in ch:
   gap = ch[a] - ch[b]; score += (gap > 0.15) - (gap < -0.15)
   print(f"  {desc}: {a} {ch[a]:+.2f}% vs {b} {ch[b]:+.2f}% -> gap {gap:+.2f} pts")
 verdict = "aggressive" if score >= 2 else "defensive" if score <= -2 else "mixed"
 print(f"Pairs verdict: {verdict} (score {score:+d} of 5; a gap within 0.15 pts counts as even)")
 print("\nSector funds, best to worst:")
 for s in sorted(SECTOR_FUNDS, key=lambda s: -ch.get(s, -99)):
  if s in ch: print(f"  {SECTOR_FUNDS[s]} ({s}) {ch[s]:+.2f}%")
 print("Context: " + "; ".join(f"{v} ({k}) {ch[k]:+.2f}%" for k, v in CONTEXT.items() if k in ch))

# ---------------- breadth ----------------
def constituents():
 raw = get("https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv").decode()
 return [(r["Symbol"].replace(".", "-"), r["GICS Sector"]) for r in csv.DictReader(io.StringIO(raw))]

def table(data, members, asof):
 res = {}
 for s, sec in members:
  pts = [(d, c) for d, c in data.get(s, []) if d <= asof]
  if len(pts) < 200 or pts[-1][0] != asof: continue
  px = [c for d, c in pts]
  flags = [px[-1] > sum(px[-w:]) / w for w in WINDOWS]
  for key in (sec, "S&P 500"):
   res.setdefault(key, []).append(flags)
 return {k: [round(100 * sum(f[j] for f in v) / len(v)) for j in range(len(WINDOWS))] for k, v in res.items()}, \
  len(res.get("S&P 500", []))

def color(p):
 stops = [(0, (128, 16, 32)), (35, (120, 40, 80)), (50, (40, 70, 110)), (65, (26, 90, 80)), (100, (8, 70, 20))]
 for (p0, c0), (p1, c1) in zip(stops, stops[1:]):
  if p <= p1:
   f = (p - p0) / (p1 - p0)
   return "#%02x%02x%02x" % tuple(round(c0[i] + f * (c1[i] - c0[i])) for i in range(3))
 return "#%02x%02x%02x" % stops[-1][1]

def html(now, base, title, basis):
 f = '<font face="Arial,sans-serif" size="2"'
 out = [f'<p><b>{title}</b><br>{f} color="#555555">Small number under each value: change in percentage points '
  f'{basis}.</font></p>',
  '<table cellpadding="5" cellspacing="1" border="0" bgcolor="#ffffff"><tr bgcolor="#eeeeee">'
  f'<td>{f}><b>Sector</b></font></td>' + "".join(f'<td align="center">{f}><b>{w}-day avg</b></font></td>'
             for w in WINDOWS) + "</tr>"]
 for k in ["S&P 500"] + SECTORS:
  if k not in now: continue
  row = [f'<td>{f}>{k}</font></td>']
  for j, v in enumerate(now[k]):
   d = v - base[k][j] if k in base else 0
   row.append(f'<td align="center" bgcolor="{color(v)}">{f} color="#ffffff"><b>{v}%</b><br><small>{d:+d}</small></font></td>')
  out.append("<tr>" + "".join(row) + "</tr>")
 out.append("</table>")
 return "\n".join(out)

def breadth(args):
 vs = args[args.index("--vs") + 1] if "--vs" in args else None
 hout = args[args.index("--html") + 1] if "--html" in args else None
 asof = dt.date.fromisoformat(args[args.index("--asof") + 1]) if "--asof" in args else None
 members = constituents()
 data = daily([s for s, _ in members])
 if asof: data = {s: [p for p in v if p[0] <= asof] for s, v in data.items()}
 last, live, label, warn = stamp(data)
 days = sorted(d for d in {p[0] for v in data.values() for p in v} if d <= last)
 now, n = table(data, members, days[-1])
 prev, _ = table(data, members, days[-2])
 base, basis = prev, f"since the close of {days[-2]:%b %d}"
 if vs:
  try:
   snap = json.loads(open(vs).read().split("SNAPSHOT", 1)[-1].strip())
   base, basis = snap["v"], f"since {snap['t']}"
  except Exception as e:
   print(f"# could not use snapshot {vs}: {e}; comparing with the prior close", file=sys.stderr)
 title = f"Percent of S&P 500 stocks above their moving averages ({label})"
 print(title + f"; {n} of {len(members)} stocks have a price for {days[-1]:%b %d}")
 if warn: print(warn)
 if n < 0.9 * len(members):
  print(f"WARNING: only {n} of {len(members)} stocks have a price for {days[-1]:%b %d} so far; "
   "rerun in a few minutes or say so.")
 print("Sector | " + " | ".join(f"{w}d" for w in WINDOWS) + f" | change {basis}")
 for k in ["S&P 500"] + SECTORS:
  if k in now:
   print(f"{k} | " + " | ".join(f"{x}%" for x in now[k]) + " | "
    + "/".join(f"{now[k][j] - base[k][j]:+d}" if k in base else "n/a" for j in range(len(WINDOWS))))
 for j, w in ((0, 5), (1, 20), (2, 50)):
  sh = sorted(((now[k][j] - base[k][j], k) for k in SECTORS if k in now and k in base), reverse=True)
  print(f"Biggest shifts in the {w}-day column ({basis}): up: "
   + ", ".join(f"{k} {d:+d}" for d, k in sh[:3] if d > 0) + "; down: "
   + ", ".join(f"{k} {d:+d}" for d, k in sh[::-1][:3] if d < 0))
 if hout:
  open(hout, "w").write(html(now, base, title, basis)); print(f"HTML table written to {hout}")
 print("SNAPSHOT " + json.dumps({"t": label, "v": now}, separators=(",", ":")))

# ---------------- extended hours ----------------
def ext(arg):
 for s in arg.split(","):
  s = s.strip().upper().replace(".", "-")
  try:
   r = json.loads(get(f"https://query1.finance.yahoo.com/v8/finance/chart/{s}?range=2d&interval=5m"
       "&includePrePost=true"))["chart"]["result"][0]
  except Exception as e:
   print(f"{s}: no data ({e})"); continue
  m = r["meta"]; reg = m.get("regularMarketPrice")
  pts = [(t, c) for t, c in zip(r.get("timestamp", []), r["indicators"]["quote"][0]["close"]) if c]
  if not pts or not reg: print(f"{s}: no data"); continue
  t, c = pts[-1]
  tt = dt.datetime.fromtimestamp(t, ET)
  print(f"{s}: regular-session price {reg:.2f} (as of {dt.datetime.fromtimestamp(m['regularMarketTime'], ET):%b %d %H:%M} ET); "
   f"latest trade incl. pre/after-market {c:.2f} at {tt:%b %d %H:%M} ET ({pct(c, reg):+.2f}% vs regular price)")

# ---------------- earnings calendar ----------------
def earnings(day, min_b=10):
 d = json.loads(get(f"https://api.nasdaq.com/api/calendar/earnings?date={day}"))
 rows = ((d.get("data") or {}).get("rows")) or []
 keep = []
 for r in rows:
  try: cap = float(r["marketCap"].replace("$", "").replace(",", "")) / 1e9
  except Exception: continue
  if cap >= min_b: keep.append((cap, r))
 print(f"US earnings on {day}, companies worth ${min_b}B or more (Nasdaq calendar; {len(keep)} of {len(rows)}):")
 for cap, r in sorted(keep, key=lambda x: -x[0]):
  g = lambda k: (r.get(k) or "").strip() or "n/a"
  extra = (f"reported EPS {g('eps')} (surprise {g('surprise')}%)" if r.get("eps")
    else f"year-ago EPS {g('lastYearEPS')}")
  print(f"  {g('name')} ({g('symbol')}): {TMAP.get(r.get('time'), 'time not given')}; market value ${cap:,.0f}B; "
   f"EPS forecast {g('epsForecast')} ({g('noOfEsts')} analysts); {extra}; quarter ending {g('fiscalQuarterEnding')}")

# ---------------- email assembly ----------------
def email(body_file, table_file, out_file):
 import html as h
 lines = open(body_file).read().splitlines()
 table = open(table_file).read() if table_file != "-" else ""
 out, para, items = [], [], []
 def flush():
  if para: out.append("<p>" + "<br>".join(para) + "</p>"); para.clear()
  if items: out.append("<ul>" + "".join(f"<li>{x}</li>" for x in items) + "</ul>"); items.clear()
 for ln in lines:
  t = ln.strip()
  if not t: flush(); continue
  if t == "[[BREADTH_TABLE]]": flush(); out.append(table); continue
  e = h.escape(t)
  if t[:2].rstrip(".").isdigit() and t.upper() == t and len(t) < 90:
   flush(); out.append(f'<h3 style="margin:18px 0 6px">{e}</h3>'); continue
  if t.startswith("- "): items.append(e[2:]); continue
  if items: flush()
  para.append(e)
 flush()
 open(out_file, "w").write('<div style="font-family:Arial,sans-serif;font-size:14px;line-height:1.45">'
       + "\n".join(out) + "</div>")
 print(f"wrote {out_file} ({len(open(out_file).read())} chars)")

# ---------------- options-implied move ----------------
def _num(x):
 try: return float(str(x).replace(",", "").replace("$", ""))
 except Exception: return None

def move(sym, day, when):
 sym = sym.upper().replace(".", "-")
 d0 = dt.date.fromisoformat(day) + dt.timedelta(days=1 if when == "amc" else 0)
 url = (f"https://api.nasdaq.com/api/quote/{sym}/option-chain?assetclass=stocks&limit=200&money=at&type=all"
  f"&fromdate={d0}&todate={d0 + dt.timedelta(days=21)}")
 try:
  d = json.loads(get(url))["data"]
  rows = d["table"]["rows"] or []
  px = _num(d["lastTrade"].split("$", 1)[1].split()[0])
 except Exception as e:
  print(f"{sym}: no option data ({e})"); return
 try:
  m = json.loads(get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=1d&interval=1d"))["chart"]["result"][0]["meta"]
  px = m.get("regularMarketPrice") or px
 except Exception:
  pass
 group, best = None, None
 for r in rows:
  if r.get("expirygroup"):
   if best: break
   group = r["expirygroup"]; continue
  k = _num(r.get("strike"))
  if k is None: continue
  if best is None or abs(k - px) < abs(best[0] - px): best = (k, r)
 if not best:
  print(f"{sym}: no option expiry within 3 weeks of the report"); return
 k, r = best
 def mid(p):
  b, a, l = _num(r.get(p + "_Bid")), _num(r.get(p + "_Ask")), _num(r.get(p + "_Last"))
  return (b + a) / 2 if b and a else l
 c, p = mid("c"), mid("p")
 if not c or not p:
  print(f"{sym}: incomplete quotes at strike {k}"); return
 gap = (dt.datetime.strptime(group, "%B %d, %Y").date() - d0).days
 print(f"{sym}: options price a move of about +/-{100 * (c + p) / px:.1f}% by the {group} expiry "
  f"(straddle {c + p:.2f} at strike {k:g}; shares {px:.2f}; option quotes {d['lastTrade'].title()})"
  + (f"\nNOT COMPARABLE: expiry is {gap} days after the report; not a report move" if gap > 7 else ""))

# ---------------- scorecard ----------------
def _last(sym):
 r = json.loads(get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=2d&interval=5m"
     "&includePrePost=true"))["chart"]["result"][0]
 pts = [c for c in r["indicators"]["quote"][0]["close"] if c]
 return pts[-1] if pts else r["meta"]["regularMarketPrice"]

def price(spec, kind):
 gics = dict(constituents())
 fund_of = {v: k for k, v in SECTOR_FUNDS.items()}
 calls, cache = [], {}
 for item in spec.split(","):
  parts = [x.strip() for x in item.split(":")]
  if len(parts) < 2 or parts[1] not in ("benefit", "suffer"):
   print(f"# skipped '{item}': use SYM:benefit|suffer:SECTION", file=sys.stderr); continue
  sym = parts[0].upper().replace(".", "-")
  etf = fund_of.get(gics.get(sym), "SPY")
  try:
   for x in (sym, etf):
    if x not in cache: cache[x] = _last(x)
  except Exception as e:
   print(f"# no price for {sym}: {e}", file=sys.stderr); continue
  calls.append([sym, parts[1], etf, round(cache[sym], 4), round(cache[etf], 4),
     parts[2] if len(parts) > 2 else ""])
  print(f"{sym} ({parts[1]}) {cache[sym]:.2f}; sector fund {etf} {cache[etf]:.2f}")
 t = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
 print("SCORE " + json.dumps({"t": t, "kind": kind, "calls": calls}, separators=(",", ":")))

def score(path):
 emails = []
 for ln in open(path).read().splitlines():
  if "SCORE" in ln:
   try: emails.append(json.loads(ln.split("SCORE", 1)[1].strip()))
   except Exception as e: print(f"# bad SCORE line skipped: {e}", file=sys.stderr)
 syms = sorted({c[0] for e in emails for c in e["calls"]} | {c[2] for e in emails for c in e["calls"]})
 data = daily(syms, "3mo")
 rows = []
 for e in emails:
  te = dt.datetime.strptime(e["t"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=dt.timezone.utc).astimezone(ET)
  for sym, side, etf, ref, eref, sec in e["calls"]:
   a, b = data.get(sym, []), data.get(etf, [])
   if not a or not b: continue
   start = te.date() if (te.time() < dt.time(16, 0) and te.weekday() < 5) else te.date() + dt.timedelta(days=1)
   ca = [c for d, c in a if d >= start]; cb = {d: c for d, c in b}
   da = [d for d, c in a if d >= start]
   res = {}
   for h in (1, 5):
    if len(ca) >= h and da[h - 1] in cb:
     x = 100 * ((ca[h - 1] / ref - 1) - (cb[da[h - 1]] / eref - 1))
     res[h] = x if side == "benefit" else -x
   rows.append((e["t"][:10], e["kind"], sym, side, etf, sec, res))
 print(f"Scorecard: {len(rows)} calls from {len(emails)} emails. Edge = stock minus sector fund; + = right.")
 for h in (1, 5):
  done = [r for r in rows if h in r[6]]
  if not done:
   print(f"After {h} trading day(s): none complete yet."); continue
  hits = sum(r[6][h] > 0 for r in done)
  avg = sum(r[6][h] for r in done) / len(done)
  print(f"After {h} trading day(s): {hits} of {len(done)} right ({100 * hits / len(done):.0f}%), "
   f"average edge {avg:+.2f} points; pending {len(rows) - len(done)}")
  for key, label in ((3, "side"), (5, "section")):
   groups = {}
   for r in done: groups.setdefault(r[key] or "-", []).append(r[6][h])
   print("   by " + label + ": " + "; ".join(f"{g} {sum(v > 0 for v in vs)}/{len(vs)} ({sum(vs) / len(vs):+.2f})"
            for g, vs in sorted(groups.items())))
 best = [r for r in rows if r[6]]
 if best:
  k = lambda r: r[6].get(5, r[6].get(1))
  b, w = max(best, key=k), min(best, key=k)
  print(f"Best call: {b[2]} ({b[3]}, {b[1]} email {b[0]}) edge {k(b):+.2f}; "
   f"worst: {w[2]} ({w[3]}, {w[1]} email {w[0]}) edge {k(w):+.2f}")

# ---------------- peers ----------------
def rel(spec, day):
 syms = [x.strip().upper().replace(".", "-") for x in spec.split(",") if x.strip()]
 gics = dict(constituents())
 fund_of = {v: k for k, v in SECTOR_FUNDS.items()}
 funds = {s: fund_of.get(gics.get(s), "SPY") for s in syms}
 data = daily(sorted(set(syms) | set(funds.values())), "3mo")
 d0 = dt.date.fromisoformat(day)
 def chg(s):
  pts = data.get(s, [])
  for i, (d, c) in enumerate(pts):
   if d == d0 and i > 0: return pct(c, pts[i - 1][1])
  return None
 for s in syms:
  a, b = chg(s), chg(funds[s])
  if a is None or b is None:
   print(f"{s}: no price for {day}"); continue
  print(f"{s}: {a:+.2f}% on {day}; sector fund {funds[s]} {b:+.2f}%; difference {a - b:+.2f} points")

def revs(spec):
 for s in spec.split(","):
  s = s.strip().upper()
  try: rows = json.loads(get(f"https://api.nasdaq.com/api/analyst/{s}/earnings-forecast"))["data"]["yearlyForecast"]["rows"][:2]
  except Exception as e: print(f"{s}: no data ({e})"); continue
  print(f"{s}: " + "; ".join(f"year to {r['fiscalEnd']}: EPS forecast {r['consensusEPSForecast']} ({r['noOfEstimates']} analysts), last 4 weeks {r['up']} raised, {r['down']} cut" for r in rows))

def why(spec, day):
 ua = {"User-Agent": "Pedro Rodrigues research pedro.g.rodrigues@edu.ulisboa.pt"}
 tk = {v["ticker"]: v["cik_str"] for v in json.loads(urllib.request.urlopen(urllib.request.Request(
  "https://www.sec.gov/files/company_tickers.json", headers=ua), timeout=60).read()).values()}
 d0 = str(dt.date.fromisoformat(day) - dt.timedelta(days=4))
 for s in spec.split(","):
  s = s.strip().upper()
  try:
   r = json.loads(urllib.request.urlopen(urllib.request.Request(
    f"https://data.sec.gov/submissions/CIK{tk[s.replace('-', '.')]:010d}.json", headers=ua), timeout=60).read())["filings"]["recent"]
   hits = [f"{r['form'][i]} {r['filingDate'][i]} items {r['items'][i]}" for i in range(len(r["form"]))
    if r["form"][i].startswith("8-K") and d0 <= r["filingDate"][i] <= day]
  except Exception as e: print(f"{s}: not in SEC data ({e}); check news"); continue
  p = str(dt.date.fromisoformat(day) - dt.timedelta(days=3 if dt.date.fromisoformat(day).weekday() == 0 else 1))
  print(f"{s}: " + ("; ".join(hits) + (" -> RESULTS RELEASED: the reason" if any("2.02" in h and h.split()[1] >= p for h in hits) else "")
   if hits else "no 8-K in the last 4 days; check news"))

def lint(path):
 import re
 t = open(path).read(); n = 0
 checks = [(r"\b(S&P 500|Nasdaq|Dow)( \w+)?:? ((was|is|closed|ended|fell|rose|gained|lost|up|down) )*[-+−]?\d+(\.\d+)?%", "index percentage"),
  (r"\d+(\.\d+)?% to \d+(\.\d+)?%", "price range"), (r"(?i)no (\w+ )?(outlet )?(gave a )?reason( was)?( found| given)?", "mover with no reason"),
  (r"(?i)\b(notably|it is worth noting|significant(ly)?)\b", "padding word")]
 for pat, why_ in checks:
  for m in re.finditer(pat, t): n += 1; print(f"FLAG {why_}: ...{t[max(0, m.start() - 40):m.end() + 20]!r}")
 seen = {}
 for ln in t.splitlines():
  if re.match(r"\s*-?\s*(If that comes to pass, )?[Ll]ikely to (benefit|suffer)", ln):
   for m in re.finditer(r"\(([A-Z]{1,5})\)( \(listed above\))?", ln):
    if m.group(1) in seen and not m.group(2): n += 1; print(f"FLAG ticker listed twice without (listed above): {m.group(1)}")
    seen[m.group(1)] = 1
 print(f"LINT: {n} flag(s)")

def watch(path):
 """lines: SYM side DATE [note]; side = benefit|suffer; DATE = test day (the stock must beat/trail its sector fund that day)"""
 items = [ln.split() for ln in open(path).read().splitlines() if ln.strip() and not ln.startswith("#")]
 syms = sorted({i[0].upper() for i in items})
 gics = dict(constituents()); fund_of = {v: k for k, v in SECTOR_FUNDS.items()}
 funds = {s: fund_of.get(gics.get(s), "SPY") for s in syms}
 data = daily(sorted(set(syms) | set(funds.values())), "3mo")
 def chg(s, d0):
  pts = data.get(s, [])
  for i, (d, c) in enumerate(pts):
   if d == d0 and i > 0: return pct(c, pts[i - 1][1])
 for it in items:
  s, side, d0 = it[0].upper(), it[1], dt.date.fromisoformat(it[2]); note = " ".join(it[3:])
  a, b = chg(s, d0), chg(funds[s], d0)
  if a is None or b is None: print(f"{s} {side} {d0}: PENDING (no close yet) {note}"); continue
  gap = a - b; ok = gap > 0 if side == "benefit" else gap < 0
  print(f"{s} {side} {d0}: {'RIGHT' if ok else 'WRONG'} ({s} {a:+.2f}% vs {funds[s]} {b:+.2f}%, gap {gap:+.2f}) {note}")

def queue(d0, d1, min_b=10):
 out, d = {}, dt.date.fromisoformat(d0)
 while d <= dt.date.fromisoformat(d1):
  if d.weekday() < 5:
   try: rows = (json.loads(get(f"https://api.nasdaq.com/api/calendar/earnings?date={d}")).get("data") or {}).get("rows") or []
   except Exception as e: print(f"# {d}: {e}", file=sys.stderr); rows = []
   for r in rows:
    try: cap = float(r["marketCap"].replace("$", "").replace(",", "")) / 1e9
    except Exception: continue
    s = (r.get("symbol") or "").strip()
    done = (r.get("eps") or "").strip() or d < now_et().date() or r.get("time") == "time-pre-market"
    if cap >= min_b and s.isalpha() and done: out[s] = (cap, d, r.get("time"), r.get("name"))
  d += dt.timedelta(days=1)
 print(f"Results out (or due before today's open) {d0} to {d1}, worth ${min_b:g}B or more, largest first (Nasdaq calendar; {len(out)}):")
 for s, (cap, d, t, n) in sorted(out.items(), key=lambda x: -x[1][0]):
  print(f"  {s} | {n} | {d} {TMAP.get(t, 'time not given')} | ${cap:,.0f}B")

if __name__ == "__main__":
 a = sys.argv[1:]
 if not a: print(__doc__)
 elif a[0] == "mood": mood()
 elif a[0] == "breadth": breadth(a[1:])
 elif a[0] == "ext" and len(a) > 1: ext(a[1])
 elif a[0] == "earnings" and len(a) > 1: earnings(a[1], float(a[2]) if len(a) > 2 else 10)
 elif a[0] == "email" and len(a) > 3: email(a[1], a[2], a[3])
 elif a[0] == "move" and len(a) > 3: move(a[1], a[2], a[3])
 elif a[0] == "price" and len(a) > 2: price(a[1], a[2])
 elif a[0] == "score" and len(a) > 1: score(a[1])
 elif a[0] == "rel" and len(a) > 2: rel(a[1], a[2])
 elif a[0] == "revs" and len(a) > 1: revs(a[1])
 elif a[0] == "why" and len(a) > 2: why(a[1], a[2])
 elif a[0] == "lint" and len(a) > 1: lint(a[1])
 elif a[0] == "watch" and len(a) > 1: watch(a[1])
 elif a[0] == "queue" and len(a) > 2: queue(a[1], a[2], float(a[3]) if len(a) > 3 else 10)
 else: print(__doc__)