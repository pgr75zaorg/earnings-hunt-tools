#!/usr/bin/env python3
"""edge.py release SYM SINCE [LIMIT] | prior-release SYM BEFORE [LIMIT]"""
import json, re, sys, html, urllib.request
UA = {"User-Agent": "Pedro Rodrigues research pedro.g.rodrigues@edu.ulisboa.pt"}

def get(u):
 return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60).read()

def _cik(sym):
 return next(v["cik_str"] for v in json.loads(get("https://www.sec.gov/files/company_tickers.json")).values()
    if v["ticker"] == sym.upper())

def _text(raw):
 raw = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
 t = html.unescape(re.sub(r"<[^>]+>", " ", raw))
 t = re.sub(r"[ \t\xa0]+", " ", t)
 return re.sub(r"\s*\n\s*", "\n", t).strip()

def _release(sym, date, before=False, limit=150000):
 cik = _cik(sym)
 r = json.loads(get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json"))["filings"]["recent"]
 idx = [i for i in range(len(r["form"])) if r["form"][i] in ("8-K", "8-K/A") and "2.02" in r["items"][i]]
 if before:
  idx = [i for i in idx if r["filingDate"][i] < date]; hit = idx[0] if idx else None
 else:
  idx = [i for i in idx if r["filingDate"][i] >= date]; hit = idx[-1] if idx else None
 if hit is None:
  print(f"NO 8-K item 2.02 for {sym} {'before' if before else 'since'} {date}"); return
 acc = r["accessionNumber"][hit].replace("-", "")
 base = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/"
 items = json.loads(get(base + "index.json"))["directory"]["item"]
 docs = [x["name"] for x in items if x["name"].lower().endswith((".htm", ".html"))
   and not x["name"].startswith(("R", acc[:4])) and "index" not in x["name"]]
 main = r["primaryDocument"][hit]
 exh = [d for d in docs if d != main] or docs
 out = [f"8-K filed {r['filingDate'][hit]} {base}"]
 for d in exh:
  t = _text(get(base + d).decode("utf-8", "ignore"))
  label = re.search(r"EX-99\.?\d+", t[:300])
  out.append(f"\n===== {label.group(0) if label else d} :: {base}{d} :: {len(t)} chars =====\n{t}")
 s = "\n".join(out)
 print(s[:limit])
 if len(s) > limit: print(f"\n[TRUNCATED at {limit} of {len(s)} chars; rerun with a larger limit]")

if __name__ == "__main__":
 a = sys.argv[1:]
 if not a: print(__doc__); sys.exit(0)
 if a[0] == "release": _release(a[1], a[2], False, int(a[3]) if len(a) > 3 else 150000)
 elif a[0] == "prior-release": _release(a[1], a[2], True, int(a[3]) if len(a) > 3 else 150000)
 else: print(__doc__)
