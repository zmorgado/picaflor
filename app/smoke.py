"""
Throwaway smoke test for fast-flights — 3.0 / consent-fix edition.

WHY THIS EXISTS (the story so far):
  - v2.2 (PyPI) is globally broken: Google now serves a "Before you continue"
    consent wall to every request. Confirmed from the DO droplet: a raw curl
    gets "Sign in" + a 302 to consent.google.com. Not our bug — a Google
    change that broke all fast-flights users (see upstream PR #108).
  - This script targets the 3.0rc1 API on thoughtpunch/flights@dev (commit
    3c77b46, 2026-05-25), which carries the strongest fix available:
      1. pre-sets a known-good SOCS consent cookie, AND
      2. if the wall STILL appears, parses the consent form and POSTs
         "Reject all" to consent.google.com/save, then retries — i.e. it
         re-accepts consent the way a browser would, so it doesn't depend on
         the (2023-era, possibly stale) hardcoded token holding up.

THE ONE QUESTION THIS ANSWERS:
  With proper consent handling, does THIS droplet IP get real, parseable
  flight data — or is the IP itself blocked at a level no cookie can fix?
    - flights returned   => IP is clean; the scraper path is viable on 3.0.
    - FlightsError / wall => IP-level block; no library fix helps -> pivot.

INSTALL (on the droplet, experiment only — keep uncommitted):
  uv add "fast-flights @ git+https://github.com/thoughtpunch/flights@dev"
  docker build -t picaflor . && docker run --rm picaflor uv run python app/smoke.py

NOTE: This uses the 3.0 API (create_query / FlightQuery / get_flights ->
MetaList / FlightsError), which is INCOMPATIBLE with v2.2. If you run it on a
2.2 install it will ImportError immediately — that means "wrong version
installed", not "the fix failed".

Delete once step 4 is done.
"""

import time
import traceback

SEP = "=" * 70


def banner(title: str) -> None:
    print(f"\n{SEP}\n{title}\n{SEP}")


# ----------------------------------------------------------------------
# Block 0 — environment + package surface (must be 3.0, not 2.2)
# ----------------------------------------------------------------------
banner("BLOCK 0 — environment + package surface (expect 3.0, NOT 2.2)")

import sys  # noqa: E402

print("Python:", sys.version.split()[0])

import fast_flights  # noqa: E402

print("fast_flights version:", getattr(fast_flights, "__version__", "?? (expect 3.0rc1)"))
print("\nTop-level names exported by fast_flights:")
for name in sorted(n for n in dir(fast_flights) if not n.startswith("_")):
    print(f"  - {name}")

# 3.0 API. If any of these fail to import, you're on the wrong version.
try:
    from fast_flights import (  # noqa: E402
        FlightQuery,
        FlightsError,
        Passengers,
        create_query,
        fetch_flights_html,
        get_flights,
    )
    print("\n3.0 API imported OK (create_query / get_flights / FlightsError).")
except ImportError:
    print("\n!!! 3.0 API import FAILED — you are NOT on thoughtpunch@dev.")
    print("    Install:  uv add 'fast-flights @ git+https://github.com/thoughtpunch/flights@dev'")
    traceback.print_exc()
    sys.exit(1)

# ~1 month out from 'today' (2026-05-29). Adjust if you run this later.
OUTBOUND = "2026-06-28"


def build_query():
    return create_query(
        flights=[FlightQuery(date=OUTBOUND, from_airport="MAD", to_airport="BCN")],
        seat="economy",
        trip="one-way",
        passengers=Passengers(adults=1),
        language="en",
        currency="",
    )


# ----------------------------------------------------------------------
# Block A — the decisive test: does the consent fix get real data from THIS IP?
# ----------------------------------------------------------------------
# In 3.0 the consent handling is automatic inside fetch_flights_html (sets
# SOCS, retries via reject-form if walled). So we just call get_flights — no
# manual cookie injection needed. A FlightsError here is the library's own
# signal that Google returned a wall / error / block.
banner("BLOCK A — get_flights() with auto consent fix (MAD -> BCN)")

t0 = time.perf_counter()
result = None
elapsed = 0.0
try:
    result = get_flights(build_query())
    elapsed = time.perf_counter() - t0
    n = len(result)
    print(f"OK — returned in {elapsed:.2f}s with {n} flight(s)")
    if n:
        print("\n  VERDICT: droplet IP is CLEAN with consent handling. "
              "Scraper path is VIABLE on 3.0. No pivot needed.")
    else:
        print("\n  Returned 0 flights but no error — possible soft block or "
              "parser drift. Inspect Block B's raw HTML below.")
except FlightsError:
    elapsed = time.perf_counter() - t0
    print(f"FlightsError after {elapsed:.2f}s — Google returned a wall/error/block.")
    print("  This is the library telling us consent handling did not yield data.")
    print("  VERDICT leaning: IP-level block (see Block B to confirm). Consider pivot.")
    traceback.print_exc()
except Exception:
    elapsed = time.perf_counter() - t0
    print(f"Unexpected exception after {elapsed:.2f}s:")
    traceback.print_exc()

# Inspect the MetaList shape (3.0 differs from 2.2's Result object).
if result is not None and len(result):
    print("\nType of result:", type(result))
    print("Metadata attrs on result:")
    for name in sorted(n for n in dir(result) if not n.startswith("_")):
        if name not in dir(list):  # only the metadata MetaList adds beyond list
            val = getattr(result, name, "<err>")
            if not callable(val):
                print(f"  - {name} = {val!r}")
    print("\nFirst result group (repr):")
    print(" ", repr(result[0]))


# ----------------------------------------------------------------------
# Block B — raw HTML: see exactly what Google served (wall vs data)
# ----------------------------------------------------------------------
# fetch_flights_html returns the post-consent-handling HTML. This tells us
# WHICH failure mode we're in if Block A came back empty/errored.
banner("BLOCK B — raw HTML after consent handling (failure-mode diagnosis)")

try:
    html = fetch_flights_html(build_query())
    print("HTML length:", len(html))
    wall = "Before you continue" in html or "consent.google.com/save" in html
    signin = "Sign in" in html and "travel/flights" not in html[:2000]
    has_script = "ds:1" in html or 'script' in html and 'data:' in html
    print("Still a consent wall?      ", "YES — IP/consent block survives the fix" if wall else "no")
    print("Looks like a sign-in page? ", "yes" if signin else "no")
    print("Has a flights data script? ", "yes (parseable data present)" if has_script else "no")
    if wall:
        print("\n  => The reject-form fallback did not clear the wall. Strong signal")
        print("     this IP is blocked at a level no cookie fixes. Lean: PIVOT.")
except FlightsError:
    print("fetch_flights_html raised FlightsError (wall/error response):")
    traceback.print_exc()
except Exception:
    print("fetch_flights_html raised:")
    traceback.print_exc()


# ----------------------------------------------------------------------
# Block C — make-or-break: cheapest-by-day / calendar API in 3.0?
# ----------------------------------------------------------------------
banner("BLOCK C — does 3.0 expose a cheapest-by-day / calendar / price-graph API?")

candidates = [
    n for n in dir(fast_flights)
    if any(kw in n.lower() for kw in ("calendar", "grid", "graph", "date", "price", "cheap"))
]
print("Names that smell like a calendar feature:")
if candidates:
    for c in candidates:
        print(f"  - {c}")
else:
    print("  (NONE by name. v2.2 had none; check whether 3.0 changed this.")
    print("   FlightQuery still takes a single 'date' per leg => step 5 must")
    print("   pre-scan day-by-day unless a range API exists. Confirm in docs.)")

import inspect  # noqa: E402

print("\ncreate_query signature (note: single 'date' per FlightQuery):")
try:
    print(" ", inspect.signature(create_query))
except (TypeError, ValueError):
    print("  <couldn't introspect>")


# ----------------------------------------------------------------------
# Block D — detection / cost signals
# ----------------------------------------------------------------------
banner("BLOCK D — detection + cost signals")

print(f"Block A latency: {elapsed:.2f}s (a ~1s fast-fail usually = walled, not slow)")
print(
    "\n3.0 fetcher impersonates chrome_145 on macOS with referer=True (a stronger\n"
    "fingerprint than 2.2's failed chrome_126). Still pure HTTP via primp — no\n"
    "Playwright/Selenium pulled in, so 'common' fetch = no browser RAM on the\n"
    "droplet. Verify deps with:  uv tree | grep -iE 'playwright|selenium|primp'\n"
)

print("\nSmoke test done. THE decision line is in Block A (flights vs FlightsError)")
print("and confirmed by Block B (real HTML vs consent wall).")
