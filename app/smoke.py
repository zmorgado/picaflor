"""
Throwaway smoke test for fast-flights (v0.1 / step 4) — droplet edition.

Run this FROM THE DIGITALOCEAN DROPLET, not locally. The whole point of the
two-cloud split (CLAUDE.md) is that Google serves a cookie-consent / sign-in
wall to flagged IPs. A local run on a residential/Homebrew IP already proved
that: every live query came back as the "Before you continue to Google" page.
This script re-runs the experiment from clean droplet egress and adds a
consent-cookie shim to see if that alone gets us real flight HTML.

It answers four questions:
  A) Does the plain library call (fetch_mode="common") work from this IP?
  B) Does injecting a CONSENT/SOCS cookie at the HTTP layer get past the wall?
  C) Is there a cheapest-by-day "calendar" capability? (make-or-break for step 5)
  D) Detection / cost signals: latency, consent wall, browser deps.

Why "common" and not "fallback": the hosted Playwright fallback service
(try.playwright.tech) now returns 401 "no token provided", so fallback/
force-fallback are dead in v2.2. Don't rely on them.

Run with:  uv run python app/smoke.py
Delete once step 4 is done.
"""

import time
import traceback

SEP = "=" * 70


def banner(title: str) -> None:
    print(f"\n{SEP}\n{title}\n{SEP}")


def looks_like_consent_wall(text: str) -> bool:
    """Google's GDPR interstitial, not flight data."""
    if not text:
        return False
    markers = ("Before you continue to Google", "consent.google", "Sign in")
    return any(m in text for m in markers)


# ----------------------------------------------------------------------
# Block 0 — what does the installed package actually expose?
# ----------------------------------------------------------------------
banner("BLOCK 0 — package surface + environment sanity")

import sys  # noqa: E402

print("Python:", sys.version.split()[0], "(CLAUDE.md pins 3.12 — flag if 3.14)")

import fast_flights  # noqa: E402

print("fast_flights version:", getattr(fast_flights, "__version__", "?? (expect 2.2)"))
print("\nTop-level names exported by fast_flights:")
for name in sorted(n for n in dir(fast_flights) if not n.startswith("_")):
    print(f"  - {name}")

from fast_flights import (  # noqa: E402
    Cookies,
    FlightData,
    Passengers,
    TFSData,
    get_flights,
)

# ~1 month out from 'today' (2026-05-28). Adjust if you run this later.
OUTBOUND = "2026-06-28"


# ----------------------------------------------------------------------
# Block A — plain library call from this IP (the baseline experiment)
# ----------------------------------------------------------------------
banner("BLOCK A — plain get_flights(common) from THIS IP (MAD -> BCN)")

t0 = time.perf_counter()
result = None
elapsed = 0.0
try:
    result = get_flights(
        flight_data=[FlightData(date=OUTBOUND, from_airport="MAD", to_airport="BCN")],
        trip="one-way",
        seat="economy",
        passengers=Passengers(adults=1),
        fetch_mode="common",  # direct HTTP only; fallback service is dead (401)
    )
    elapsed = time.perf_counter() - t0
    print(f"OK — call returned in {elapsed:.2f}s")
except Exception:
    elapsed = time.perf_counter() - t0
    print(f"FAILED after {elapsed:.2f}s")
    print(
        "If the traceback below shows a consent/sign-in page, this IP is being\n"
        "walled (RC1). That's the make-or-break signal for the droplet.\n"
    )
    traceback.print_exc()

if result is not None:
    flights = getattr(result, "flights", None)
    print("\nresult.current_price:", getattr(result, "current_price", "<none>"))
    print("number of flights:", len(flights) if flights is not None else "n/a")
    if flights:
        f0 = flights[0]
        print("\nAttributes on a single flight:")
        for name in sorted(n for n in dir(f0) if not n.startswith("_")):
            value = getattr(f0, name, "<err>")
            if not callable(value):
                print(f"  - {name:20} = {value!r}")
        print("\nFirst 3 flights (repr):")
        for f in flights[:3]:
            print(" ", repr(f))


# ----------------------------------------------------------------------
# Block B — the decisive test: known-good SOCS cookie at the HTTP layer
# ----------------------------------------------------------------------
# get_flights() has NO way to pass cookies (see core.py signature), and its
# internal fetch() builds a bare cookie-less primp Client. So we reproduce the
# same request at the low level and inject a *specific, known-good* SOCS token
# — the exact constant from upstream PR #108
# (github.com/AWeirdDev/flights/pull/108), which proved this value bypasses the
# "Before you continue to Google" consent wall. (Our earlier attempt used the
# library's Cookies.new() — a dynamically built token Google evidently doesn't
# honor; that's why it failed.)
#
# This isolates ONE variable: with a valid consent cookie, does THIS droplet IP
# get real flight HTML, or a second IP-level block?
#   - parseable flights  => IP is clean; the only fix needed is wiring this
#                           cookie into the library (small, known change).
#   - still walled / 0   => the IP itself is blocked; no library fix helps.
banner("BLOCK B — known-good SOCS cookie: does THIS IP get real data?")

from fast_flights.primp import Client  # noqa: E402
from fast_flights.core import parse_response  # noqa: E402

# Exact token from PR #108. Static (baked 2023) — works because Google's
# consent tokens are long-lived; may rot eventually.
SOCS = "CAISNQgDEitib3FfaWRlbnRpdHlmcm9udGVuZHVpc2VydmVyXzIwMjMwODE1LjA3X3AxGgJlbiACGgYIgJnPpwY"

tfs = TFSData.from_interface(
    flight_data=[FlightData(date=OUTBOUND, from_airport="MAD", to_airport="BCN")],
    trip="one-way",
    passengers=Passengers(adults=1),
    seat="economy",
    max_stops=None,
)
params = {
    "tfs": tfs.as_b64().decode("utf-8"),
    "hl": "en",
    "tfu": "EgQIABABIgA",
    "curr": "",
}
print("Injecting cookie: SOCS (known-good token from PR #108)")

try:
    client = Client(impersonate="chrome_126", verify=False)
    t1 = time.perf_counter()
    res = client.get(
        "https://www.google.com/travel/flights",
        params=params,
        cookies={"SOCS": SOCS},
    )
    dt = time.perf_counter() - t1
    print(f"HTTP {res.status_code} in {dt:.2f}s")

    walled = looks_like_consent_wall(res.text_markdown)
    print("Still the consent wall?", "YES — IP appears blocked" if walled else "no — got past it")

    if not walled:
        # The real proof: can the library's own parser extract flights from
        # this HTML? "Not a wall" isn't enough — it must be parseable data.
        try:
            parsed = parse_response(res)
            flights = getattr(parsed, "flights", None)
            n = len(flights) if flights else 0
            print(f"parse_response() -> {n} flight(s); current_price={getattr(parsed, 'current_price', '?')}")
            if n:
                print("  VERDICT: droplet IP is CLEAN with a valid cookie. "
                      "Fix = wire SOCS into the library. Scraper is viable.")
                print("  sample:", repr(flights[0]))
            else:
                print("  Got non-wall HTML but 0 flights — possible soft block "
                      "or parser drift. Inspect res.text_markdown.")
        except Exception:
            print("  parse_response() raised — not the wall, but unparseable:")
            traceback.print_exc()
except Exception:
    print("Low-level fetch raised:")
    traceback.print_exc()


# ----------------------------------------------------------------------
# Block C — the make-or-break probe: cheapest-by-day calendar?
# ----------------------------------------------------------------------
banner("BLOCK C — is there a cheapest-by-day / calendar / price-graph API?")

candidates = [
    n for n in dir(fast_flights)
    if any(kw in n.lower() for kw in ("calendar", "grid", "graph", "date", "price", "cheap"))
]
print("Names in fast_flights that smell like a calendar feature:")
if candidates:
    for c in candidates:
        print(f"  - {c}")
else:
    print("  (NONE — v2.2 has no calendar symbol. get_flights takes a single")
    print("   date per leg, no range. Step 5 must pre-scan day-by-day or find")
    print("   another lib. Confirm at https://aweird.me/flights/)")

import inspect  # noqa: E402

print("\nget_flights signature (note: single 'date' per FlightData, no range):")
try:
    print(" ", inspect.signature(get_flights))
except (TypeError, ValueError):
    print("  <couldn't introspect>")


# ----------------------------------------------------------------------
# Block D — detection / cost signals
# ----------------------------------------------------------------------
banner("BLOCK D — detection + cost signals")

print(f"Block A latency: {elapsed:.2f}s (a fast fail ~1s usually = walled, not slow)")
print(
    "\nBrowser deps: v2.2 pulls only 'primp' (Rust HTTP client) — no Playwright/\n"
    "Selenium locally. 'common' = direct HTTP (cheap, no browser RAM). The\n"
    "'fallback'/'local' modes need a remote/local browser; the hosted fallback\n"
    "(try.playwright.tech) returns 401 now, so treat 'common' as the only path.\n"
    "Verify deps with:  uv tree | grep -iE 'playwright|selenium|primp'\n"
)

print("\nSmoke test done. Read the blocks top-to-bottom. The key question:")
print("did Block A or Block B return real flights from the droplet IP?")

