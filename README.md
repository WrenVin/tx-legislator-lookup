# Texas legislator lookup

Enter a Texas street address and ZIP code and get your state representative and state senator, updated with the November 3, 2026 general election results. A writing space under the results turns your message into a prefilled draft in your own email app or Gmail. GitHub Pages cannot send email, so the visitor sends it themselves.

It is a static page (`index.html` plus two JSON files), so it runs on GitHub Pages with no server.

## How it works

- The address is matched to its House and Senate districts by the [U.S. Census Bureau geocoder](https://geocoding.geo.census.gov/geocoder/), called straight from the browser. The address goes only to the Census Bureau.
- If the geocoder cannot place the address, the page falls back to `data/zips.json`, which maps each ZIP code to every district it touches, and shows all of them, most likely first.
- `data/legislators.json` lists the member for each of the 150 House and 31 Senate districts.

## Data sources

| Data | Source |
| --- | --- |
| Election winners | Texas Secretary of State returns for the November 3, 2026 general election, retrieved November 12, 2026. Unofficial until canvassed. |
| Address to district | U.S. Census Bureau geocoder, current state legislative district layers |
| ZIP to district (fallback) | Texas Legislative Council "ZIP Codes by District" (Red-385) reports for PLANH2316 and PLANS2168, 2020 Census population |
| Sitting members and emails | [Open States](https://openstates.org/) current Texas legislators |
| Name cross-check | Wikipedia's 2026 Texas House and Senate election pages |

## Things to know

- Members elected for the first time take office on January 12, 2027. Until then the page also shows who holds the seat now. That part disappears on its own on January 12.
- Email addresses for new members are **guesses** in the Legislature's usual `first.last@house.texas.gov` / `first.last@senate.texas.gov` format, and the page labels them as unconfirmed. Replace them once the official addresses are published.
- Four House races (districts 26, 61, 67 and 126) were decided by less than half a percentage point and are flagged on the page, since a recount could change them.
- Fifteen Senate seats were not on the 2026 ballot. Those senators are listed as they are.

## Updating the data

Replace the files in `data/raw/`, then:

```bash
pip install xlrd
python3 scripts/build_data.py
```

The script prints a warning for anything that needs a human look, such as a winner that disagrees between sources.

## Running locally

```bash
python3 -m http.server 8000
```

Then open http://localhost:8000.

Not affiliated with the State of Texas.
