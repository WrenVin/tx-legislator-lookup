#!/usr/bin/env python3
"""Build data/legislators.json and data/zips.json from the files in data/raw/.

Inputs (all in data/raw/):
  sos_2026_general_legislative.json  Texas Secretary of State returns, Nov 3 2026
  openstates_tx_current.csv          Open States list of sitting legislators (names, emails)
  wikipedia_2026_winners.csv         Used only for nicely-cased names and as a cross-check
  planh2316_r385.xls                 Texas Legislative Council "ZIP Codes by District", House
  plans2168_r385.xls                 Same, Senate

Requires: pip install xlrd
"""
import csv
import json
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

import xlrd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data"

TERM_START = "2027-01-12"  # 90th Legislature convenes
PARTY = {"REP": "R", "DEM": "D", "Rep": "R", "Dem": "D", "Republican": "R",
         "Democratic": "D", "L": "L", "G": "G", "W": "I"}
DOMAIN = {"house": "house.texas.gov", "senate": "senate.texas.gov"}
CLOSE_MARGIN_PCT = 0.5  # flag races this close; recount possible
warnings = []


def norm(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z]", "", s.lower())


def ascii_part(s):
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^A-Za-z]", "", s).lower()


SUFFIXES = {"jr": "Jr.", "sr": "Sr.", "ii": "II", "iii": "III", "iv": "IV"}


def clean_sos_name(s):
    """'HAROLD V. DUTTON, JR (I)' -> 'Harold V. Dutton Jr.'"""
    s = re.sub(r"\(I\)", "", s).replace(",", " ")

    def cap(m):
        w = m.group(0)
        if w.lower() in SUFFIXES:
            return SUFFIXES[w.lower()]
        w = w.capitalize()
        return re.sub(r"^Mc(\w)", lambda k: "Mc" + k.group(1).upper(), w)
    s = re.sub(r"[^\W\d_]+\.?", lambda m: cap(m) if not m.group(0).endswith(".") else cap(re.match(r"[^.]+", m.group(0))) + ".", s)
    return " ".join(s.replace("Jr..", "Jr.").split())


def guess_email(name, chamber):
    """Standard first.last@chamber.texas.gov pattern. Unverified for new members."""
    clean = re.sub(r'"[^"]*"|\([^)]*\)', " ", name)
    parts = [p for p in clean.split() if ascii_part(p) not in SUFFIXES]
    parts = [ascii_part(p) for p in parts if ascii_part(p)]
    if len(parts) < 2:
        return None
    return f"{parts[0]}.{parts[-1]}@{DOMAIN[chamber]}"


def load_sitting():
    sitting = {}
    with open(RAW / "openstates_tx_current.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            chamber = "house" if r["current_chamber"] == "lower" else "senate"
            sitting[(chamber, int(r["current_district"]))] = {
                "name": r["name"],
                "family": r["family_name"],
                "party": PARTY.get(r["current_party"], r["current_party"][:1]),
                "email": r["email"] or None,
            }
    return sitting


def load_wiki():
    wiki = {}
    with open(RAW / "wikipedia_2026_winners.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            wiki[(r["chamber"], int(r["district"]))] = r
    return wiki


def build_legislators():
    sitting = load_sitting()
    wiki = load_wiki()
    sos = json.load(open(RAW / "sos_2026_general_legislative.json"))
    out = {"house": {}, "senate": {}}

    specials = {}
    for race in sos["races"]:
        if race["election"] == "special":
            win = max(race["candidates"], key=lambda c: c["votes"])
            specials[(race["chamber"], race["district"])] = win

    for race in sos["races"]:
        if race["election"] != "general":
            continue
        chamber, dist = race["chamber"], race["district"]
        key = (chamber, dist)
        cands = sorted(race["candidates"], key=lambda c: -c["votes"])
        win = cands[0]
        total = race["total_votes"] or sum(c["votes"] for c in cands)
        margin = None
        if len(cands) > 1 and total:
            margin = round(100 * (win["votes"] - cands[1]["votes"]) / total, 2)

        cur = sitting.get(key)
        w = wiki.get(key)
        sos_name = clean_sos_name(win["name"])
        incumbent_won = "(I)" in win["name"]  # the Secretary of State marks incumbents
        same_person = bool(cur and norm(cur["family"].split()[0]) in norm(win["name"]))
        reelected = incumbent_won
        if incumbent_won and cur and not same_person:
            # Ballot name differs from the name the member uses in office (e.g. a married name).
            # The sitting member of the district is by definition the incumbent.
            same_person = True
        if incumbent_won and not cur:
            warnings.append(f"{chamber} {dist}: incumbent {sos_name} won but no sitting member on file; email unverified")
        if same_person and not incumbent_won:
            warnings.append(f"{chamber} {dist}: winner {sos_name} matches sitting member {cur['name']} but is not marked incumbent")
            reelected = True
        name = cur["name"] if (reelected and same_person) else sos_name

        # Cross-check against Wikipedia
        if w and w["winner"] and norm(w["winner"].replace("Jr.", "").split()[-1]) not in norm(win["name"]):
            warnings.append(f"{chamber} {dist}: SOS winner {sos_name} != Wikipedia {w['winner']}")
        if not (w and w["winner"]):
            warnings.append(f"{chamber} {dist}: no Wikipedia winner listed; using SOS ({sos_name}, margin {margin})")

        rec = {
            "district": dist,
            "name": name,
            "party": PARTY.get(win["party"], win["party"]),
            "votes": win["votes"],
            "margin_pct": margin,
            "unopposed": len(cands) == 1,
            "close": margin is not None and margin < CLOSE_MARGIN_PCT,
        }
        if reelected and same_person:
            rec.update(status="reelected", email=cur["email"], email_verified=bool(cur["email"]))
        elif reelected:
            rec.update(status="reelected", email=guess_email(name, chamber), email_verified=False)
        else:
            rec.update(status="elect", email=guess_email(name, chamber), email_verified=False,
                       takes_office=TERM_START)
            sp = specials.get(key)
            if sp and norm(sp["last"]) == norm(win["last"]):
                rec["note"] = "Also won the special election for the unexpired term, so may be seated before January."
            if cur and not same_person:
                rec["outgoing"] = {"name": cur["name"], "party": cur["party"], "email": cur["email"]}
            elif w and w["incumbent"] and w["incumbent"] != w["winner"]:
                rec["outgoing"] = {"name": w["incumbent"], "party": PARTY.get(w["incumbent_party"]), "email": None}
        out[chamber][str(dist)] = rec

    # Senators whose seats were not on the 2026 ballot
    for d in range(1, 32):
        if str(d) in out["senate"]:
            continue
        cur = sitting.get(("senate", d))
        if not cur:
            warnings.append(f"senate {d}: not on ballot and no sitting senator found")
            continue
        out["senate"][str(d)] = {
            "district": d, "name": cur["name"], "party": cur["party"], "status": "holdover",
            "email": cur["email"], "email_verified": bool(cur["email"]),
        }

    for chamber, n in (("house", 150), ("senate", 31)):
        missing = [d for d in range(1, n + 1) if str(d) not in out[chamber]]
        if missing:
            warnings.append(f"{chamber}: missing districts {missing}")
    return out, sos


def load_zip_report(path):
    """Return {zip: {district: population}} from a TLC Red-385 spreadsheet."""
    sheet = xlrd.open_workbook(str(path), logfile=open("/dev/null", "w")).sheet_by_index(0)
    header = None
    for r in range(sheet.nrows):
        row = sheet.row_values(r)
        if "District" in row and "ZIP Code" in row:
            header = r
            c_dist, c_zip, c_pop = row.index("District"), row.index("ZIP Code"), row.index("Population in District")
            break
    if header is None:
        sys.exit(f"Could not find header row in {path}")
    result = defaultdict(lambda: defaultdict(int))
    dist = None
    for r in range(header + 1, sheet.nrows):
        row = sheet.row_values(r)
        if isinstance(row[c_dist], float):
            dist = int(row[c_dist])
        z = str(row[c_zip]).strip().lstrip("*")
        if not re.fullmatch(r"\d{5}", z) or z == "00000" or dist is None:
            continue
        pop = int(row[c_pop]) if isinstance(row[c_pop], float) else 0
        result[z][dist] += pop
    return result


def shares(by_dist):
    total = sum(by_dist.values())
    items = sorted(by_dist.items(), key=lambda kv: (-kv[1], kv[0]))
    if total == 0:
        return [[d, None] for d, _ in items]
    # Drop slivers with no residents when the ZIP has residents elsewhere
    return [[d, round(100 * p / total, 1)] for d, p in items if p > 0]


def build_zips():
    house = load_zip_report(RAW / "planh2316_r385.xls")
    senate = load_zip_report(RAW / "plans2168_r385.xls")
    zips = {}
    for z in sorted(set(house) | set(senate)):
        zips[z] = {"h": shares(house.get(z, {})), "s": shares(senate.get(z, {}))}
        if not zips[z]["h"] or not zips[z]["s"]:
            warnings.append(f"zip {z}: missing house or senate district")
    return zips


def main():
    legislators, sos = build_legislators()
    zips = build_zips()
    meta = {
        "election": "November 3, 2026 general election",
        "results_source": sos["source"],
        "results_retrieved": sos["retrieved"],
        "term_start": TERM_START,
        "house_plan": "PLANH2316",
        "senate_plan": "PLANS2168",
    }
    (OUT / "legislators.json").write_text(
        json.dumps({"meta": meta, **legislators}, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "zips.json").write_text(json.dumps(zips, separators=(",", ":")), encoding="utf-8")

    h, s = legislators["house"], legislators["senate"]
    print(f"house: {len(h)} members, senate: {len(s)} members, zips: {len(zips)}")
    for chamber, m in (("house", h), ("senate", s)):
        tally = defaultdict(int)
        for r in m.values():
            tally[r["party"]] += 1
        st = defaultdict(int)
        for r in m.values():
            st[r["status"]] += 1
        print(f"  {chamber}: parties {dict(tally)}, status {dict(st)}, close races {[r['district'] for r in m.values() if r.get('close')]}")
    print(f"{len(warnings)} warnings")
    for w in warnings:
        print("  WARN", w)


if __name__ == "__main__":
    main()
