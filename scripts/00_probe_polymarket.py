import json
import pandas as pd
from pmbias.http import get_json
from pmbias.polymarket import CLOB

rows = [json.loads(l) for l in open("data/raw/polymarket_markets.jsonl")][:3]
for m in rows:
    tok = m["aux_id"]
    print("\nMARKET", m["market_id"], "|", (m["question"] or "")[:60])
    print("  open", m["open_time"], "| close", m["close_time"], "| token", str(tok)[:12] + "...")
    s = int(pd.Timestamp(m["open_time"]).timestamp())
    e = int(pd.Timestamp(m["close_time"]).timestamp())
    tests = [
        ("interval=max fidelity=1440", {"interval": "max", "fidelity": 1440}),
        ("interval=max fidelity=60", {"interval": "max", "fidelity": 60}),
        ("interval=max (no fidelity)", {"interval": "max"}),
        ("startTs/endTs fidelity=720", {"startTs": s, "endTs": e, "fidelity": 720}),
        ("startTs/endTs fidelity=60", {"startTs": s, "endTs": e, "fidelity": 60}),
    ]
    for name, p in tests:
        try:
            d = get_json(CLOB + "/prices-history", {"market": tok, **p})
            print(f"  {name:32s} -> {len(d.get('history', []))} points")
        except Exception as ex:
            print(f"  {name:32s} -> ERROR {str(ex)[:100]}")
