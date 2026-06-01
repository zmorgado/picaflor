"""
Throwaway probe: cheap open-jaw trips out of Belgium, Jul 10 -> Jul 15.

This is a MINI-PROTOTYPE of v0.1 steps 5+6 (pre-scan + in-memory open-jaw
combiner), run against the live 3.0 fork to see real numbers before we design
those steps properly.

Library constraints discovered while building this (matter for v0.1 design):
  - NO "everywhere" destination search — to_airport is a required concrete
    code, so we must scan a hardcoded shortlist.
  - NO multi-city / open-jaw in a single query (proto says MULTI_CITY is "not
    implemented"). So open-jaw = two independent one-way scans combined in
    memory, exactly as CLAUDE.md's search-space note prescribes.

Scope (deliberately tight to stay polite to Google):
  - Origins:  BRU, CRL (Brussels + Charleroi/Brussels-South low-cost base)
  - Dests:    Ryanair/Wizz-heavy leisure cities CRL actually flies cheap to
  - Outbound: depart Jul 10 (one-way, each origin -> each dest)   = 16 calls
  - Inbound:  depart Jul 15 (one-way, each dest -> each origin)   = 16 calls
  - Combine:  pair (out to A) + (back from B) = open-jaw; A==B = round-trip.
              Rank by total price.

Run on the droplet (needs the consent-fix fork install):
  docker run --rm picaflor uv run python app/probe_belgium.py
Delete once we've seen the numbers.
"""

import random
import time

from fast_flights import (
    FlightQuery,
    FlightsError,
    Passengers,
    create_query,
    get_flights,
)

SEP = "=" * 70

ORIGINS = ["BRU", "CRL"]
DESTS = ["AGP", "ALC", "FAO", "BUD", "KRK", "OTP", "PMI", "CTA"]
DEPART = "2026-07-10"
RETURN = "2026-07-15"

# Politeness: random delay between live calls so we don't hammer Google.
DELAY_RANGE = (1.5, 3.5)


def banner(title: str) -> None:
    print(f"\n{SEP}\n{title}\n{SEP}")


def cheapest_one_way(origin: str, dest: str, date: str):
    """One live query. Returns (price, url) for the cheapest flight, or None
    on failure. URL is the Google Flights search link for this leg — the
    library has no per-itinerary booking URL, but Query.url() gives a search
    that re-runs the exact same query, with our result at the top. Never
    raises — a probe should survive one bad leg and keep scanning."""
    query = create_query(
        flights=[FlightQuery(date=date, from_airport=origin, to_airport=dest)],
        seat="economy",
        trip="one-way",
        passengers=Passengers(adults=1),
        currency="EUR",
    )
    url = query.url()
    try:
        results = get_flights(query)
    except FlightsError:
        print(f"    {origin}->{dest} {date}: FlightsError (wall/block/no data)")
        return None
    except Exception as e:  # probe: don't let one leg kill the run
        print(f"    {origin}->{dest} {date}: error {type(e).__name__}: {e}")
        return None

    if not results:
        print(f"    {origin}->{dest} {date}: 0 flights")
        return None

    cheapest = min(results, key=lambda f: f.price)
    return cheapest.price, url


def scan(direction: str, pairs):
    """Run one-way scans; collect {(a,b): (price, url)} for legs that returned data."""
    print(f"\n[{direction}] scanning {len(pairs)} legs...")
    legs = {}
    for a, b, date in pairs:
        result = cheapest_one_way(a, b, date)
        if result is not None:
            price, url = result
            legs[(a, b)] = (price, url)
            print(f"    {a}->{b} {date}: EUR {price}")
        time.sleep(random.uniform(*DELAY_RANGE))
    return legs


# ----------------------------------------------------------------------
banner("PROBE — open-jaw out of Belgium, Jul 10 -> Jul 15")
print(f"Origins: {ORIGINS}  |  Dests: {DESTS}")
print(f"Outbound depart {DEPART}, inbound depart {RETURN}")
print(f"Total legs: {len(ORIGINS) * len(DESTS) * 2} (with {DELAY_RANGE}s jitter between)")

t0 = time.perf_counter()

# --- Outbound: each origin -> each dest, departing Jul 10 ---
outbound_pairs = [(o, d, DEPART) for o in ORIGINS for d in DESTS]
out_prices = scan("OUTBOUND", outbound_pairs)  # keys: (origin, dest)

# --- Inbound: each dest -> each origin, departing Jul 15 ---
inbound_pairs = [(d, o, RETURN) for o in ORIGINS for d in DESTS]
in_prices = scan("INBOUND", inbound_pairs)  # keys: (dest, origin)

elapsed = time.perf_counter() - t0

# ----------------------------------------------------------------------
# In-memory combiner — rules from design discussion:
#   - SAME METRO: out-origin and back-origin must both be in {BRU, CRL}.
#     You have to actually come home to Brussels. (No flying out from BRU
#     and "home" to Madrid.) Both ORIGINS here are Brussels-area so this
#     is just "back-origin in ORIGINS" — kept explicit for when origins
#     span multiple metros in the real code.
#   - kind:
#       * round-trip  : A == B (same destination city, regular trip)
#       * open-jaw    : A != B (out to A, ground-link A->B, back from B)
#   - GEO FLAG on open-jaw:
#       * 'ok'   : A and B in the same region table entry — plausible
#                  ground link (train/bus/short hop).
#       * 'wild' : A and B in different regions — surfaced but flagged so
#                  the user can see it's not a realistic city-hop.
#
# Region table is intentionally small + hand-rolled; cheap and readable.
# ----------------------------------------------------------------------

# Coarse regions for the destinations we scan. Tune as we add cities.
REGIONS = {
    "iberia":       {"AGP", "ALC", "PMI", "FAO"},     # Spain coast + Algarve
    "central_eu":   {"BUD", "KRK"},                   # Budapest + Krakow
    "balkans":      {"OTP"},                          # Bucharest
    "sicily":       {"CTA"},                          # Catania
}


def region_of(code: str) -> str | None:
    for name, members in REGIONS.items():
        if code in members:
            return name
    return None


def open_jaw_flag(dest_a: str, dest_b: str) -> str:
    ra, rb = region_of(dest_a), region_of(dest_b)
    if ra and rb and ra == rb:
        return "ok"        # plausible ground link
    return "wild"          # different regions — surfaced but flagged


banner("COMBINER — same-metro trips, open-jaw + round-trip, geo-flagged")

trips = []
for (o1, dest_a), (out_price, out_url) in out_prices.items():
    for (dest_b, o2), (in_price, in_url) in in_prices.items():
        # Same-metro rule: must come home to a Brussels-area airport.
        if o2 not in ORIGINS:
            continue
        total = out_price + in_price
        if dest_a == dest_b:
            kind, flag = "round-trip", "-"
        else:
            kind = "open-jaw"
            flag = open_jaw_flag(dest_a, dest_b)
        trips.append({
            "kind": kind,
            "flag": flag,
            "out": f"{o1}->{dest_a}",
            "back": f"{dest_b}->{o2}",
            "total": total,
            "out_url": out_url,
            "in_url": in_url,
        })

trips.sort(key=lambda t: t["total"])

if not trips:
    print("No trips assembled — every leg failed. See errors above.")
else:
    print(f"Assembled {len(trips)} same-metro candidates. Top 10 by total price:")
    print("(URLs are Google Flights search links — your result is at the top of the page.)\n")
    for i, t in enumerate(trips[:10], 1):
        print(f"  #{i:<2} {t['kind']:<10} {t['flag']:<5} "
              f"out {t['out']:<10} back {t['back']:<10}  EUR {t['total']}")
        print(f"      out link:  {t['out_url']}")
        print(f"      back link: {t['in_url']}")
        print()

    # The interesting find: cheapest *plausible* open-jaw (kind=open-jaw, flag=ok).
    # If one beats the cheapest round-trip, that's a real v0.1 differentiator.
    plausible_oj = [t for t in trips if t["kind"] == "open-jaw" and t["flag"] == "ok"]
    cheapest_rt = next((t for t in trips if t["kind"] == "round-trip"), None)
    print()
    if plausible_oj:
        best = plausible_oj[0]
        print(f"Best PLAUSIBLE open-jaw: out {best['out']}, back {best['back']} = EUR {best['total']}")
        print(f"  out link:  {best['out_url']}")
        print(f"  back link: {best['in_url']}")
        if cheapest_rt and best["total"] < cheapest_rt["total"]:
            saving = cheapest_rt["total"] - best["total"]
            print(f"  -> beats cheapest round-trip ({cheapest_rt['out']} {cheapest_rt['back']} "
                  f"EUR {cheapest_rt['total']}) by EUR {saving}.")
        elif cheapest_rt:
            print(f"  (cheapest round-trip is still cheaper: {cheapest_rt['out']} "
                  f"{cheapest_rt['back']} EUR {cheapest_rt['total']})")
    else:
        print("No plausible open-jaws found — every A!=B pair crosses regions.")

# ----------------------------------------------------------------------
banner("PROBE STATS")
print(f"Outbound legs with data: {len(out_prices)}/{len(outbound_pairs)}")
print(f"Inbound  legs with data: {len(in_prices)}/{len(inbound_pairs)}")
print(f"Total wall-clock: {elapsed:.1f}s for {len(outbound_pairs) + len(inbound_pairs)} calls")
print("\nProbe done. Watch for: failed legs (detection?), latency creep over the")
print("run (rate-limiting?), and whether any open-jaw beats the round-trips.")
