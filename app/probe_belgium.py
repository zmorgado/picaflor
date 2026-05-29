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
import traceback

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
    """One live query. Returns (price:int, label:str) for the cheapest flight,
    or None if no result / blocked. Never raises — a probe should survive one
    bad leg and keep scanning."""
    try:
        results = get_flights(
            create_query(
                flights=[FlightQuery(date=date, from_airport=origin, to_airport=dest)],
                seat="economy",
                trip="one-way",
                passengers=Passengers(adults=1),
                currency="EUR",
            )
        )
    except FlightsError:
        print(f"    {origin}->{dest} {date}: FlightsError (wall/block/no data)")
        return None
    except Exception as e:  # probe: don't let one leg kill the run
        print(f"    {origin}->{dest} {date}: error {type(e).__name__}: {e}")
        return None

    if not results:
        print(f"    {origin}->{dest} {date}: 0 flights")
        return None

    # results is a MetaList of Flights groups; .price is total EUR for the group.
    cheapest = min(results, key=lambda f: f.price)
    return cheapest.price


def scan(direction: str, pairs):
    """Run one-way scans for a list of (a, b, date) and collect prices."""
    print(f"\n[{direction}] scanning {len(pairs)} legs...")
    prices = {}
    for a, b, date in pairs:
        price = cheapest_one_way(a, b, date)
        if price is not None:
            prices[(a, b)] = price
            print(f"    {a}->{b} {date}: EUR {price}")
        time.sleep(random.uniform(*DELAY_RANGE))
    return prices


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
# In-memory open-jaw combiner: out to city A (from origin O1), back from
# city B (to origin O2). A != B => true open-jaw. A == B => round-trip.
# ----------------------------------------------------------------------
banner("COMBINER — open-jaw + round-trip pairs, ranked by total price")

trips = []
for (o1, dest_a), out_price in out_prices.items():
    for (dest_b, o2), in_price in in_prices.items():
        total = out_price + in_price
        kind = "round-trip" if dest_a == dest_b else "open-jaw"
        trips.append({
            "kind": kind,
            "out": f"{o1}->{dest_a}",
            "back": f"{dest_b}->{o2}",
            "total": total,
        })

trips.sort(key=lambda t: t["total"])

if not trips:
    print("No trips assembled — every leg failed. See errors above.")
else:
    print(f"Assembled {len(trips)} candidate trips. Top 15 by total price:\n")
    print(f"  {'#':>2}  {'kind':<10}  {'out':<10}  {'back':<10}  {'total':>8}")
    print(f"  {'-'*2}  {'-'*10}  {'-'*10}  {'-'*10}  {'-'*8}")
    for i, t in enumerate(trips[:15], 1):
        print(f"  {i:>2}  {t['kind']:<10}  {t['out']:<10}  {t['back']:<10}  EUR {t['total']:>4}")

    # Highlight the best genuine open-jaw (the v0.1 differentiator).
    best_oj = next((t for t in trips if t["kind"] == "open-jaw"), None)
    if best_oj:
        print(f"\nBest OPEN-JAW: out {best_oj['out']}, back {best_oj['back']} "
              f"= EUR {best_oj['total']}")

# ----------------------------------------------------------------------
banner("PROBE STATS")
print(f"Outbound legs with data: {len(out_prices)}/{len(outbound_pairs)}")
print(f"Inbound  legs with data: {len(in_prices)}/{len(inbound_pairs)}")
print(f"Total wall-clock: {elapsed:.1f}s for {len(outbound_pairs) + len(inbound_pairs)} calls")
print("\nProbe done. Watch for: failed legs (detection?), latency creep over the")
print("run (rate-limiting?), and whether any open-jaw beats the round-trips.")
