# Obscura — CDP gaps and inline-`<script>` execution issues

Draft of an issue for https://github.com/h4ckf0r0day/obscura/issues. Three
distinct problems surfaced while wiring Obscura into a Playwright-based
Facebook Ads Library scraper via `connect_over_cdp`. Listed worst-first.

## Environment

| Field | Value |
|---|---|
| Obscura | v0.1.0 (from `obscura serve` banner) |
| Binary sha256 prefix | `bd6763c2f269c076…` |
| Container base | `debian:12-slim` (`docker/obscura.Dockerfile`) |
| Driver | Playwright 1.59.1 (Python) over CDP |
| Repro env | docker-compose; api → obscura over a docker network |

---

## 1. Page-loaded inline `<script>` tags don't execute (highest impact)

`page.evaluate(...)` works — a JS execution context exists and round-trips
values correctly. But `<script>` tags embedded in HTML served by
`page.goto(...)` are not run. Pages that depend on their own bootstrap
scripts (i.e. anything React/Relay/Vue/Angular) render only the SSR
fallback or the initial static HTML.

### Repro

```python
import asyncio
from playwright.async_api import async_playwright

# A minimal page that proves inline <script> never fires:
URL = "https://www.example.com"  # any page works; FB shows it dramatically

async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.connect_over_cdp("http://localhost:9222")
        ctx = await b.new_context()
        page = await ctx.new_page()
        await page.goto(URL, wait_until="domcontentloaded")
        # Ad-hoc JS works:
        print(await page.evaluate("1 + 2"))                       # → 3
        print(await page.evaluate("typeof navigator.webdriver"))  # → 'undefined'
        await ctx.close(); await b.close()

asyncio.run(main())
```

### Real-world symptom (Facebook Ads Library)

Facebook serves a 481-byte stub when it doesn't trust a browser:

```html
<script>
  function executeChallenge() {
    fetch('/__rd_verify_<token>?challenge=3', {method:'POST'})
      .finally(() => window.location.reload());
  }
  if (document.readyState !== 'loading') executeChallenge();
  else document.addEventListener('DOMContentLoaded', executeChallenge);
</script>
```

**Expected:** the inline `<script>` runs, fetches the verify URL, sets the
`rd_challenge` cookie, reloads, FB serves the real page.

**Observed:** `document.body.innerText.length` stays at 380 for at least
24 s — no fetch is made, no reload happens. `page.evaluate("1+2")` still
returns `3` during this window, so the JS context is live; the page's own
`<script>` block simply never fired.

**Workaround** (used in `backend/src/fb_ads_scraper/fb_challenge.py`):
manually run the verify fetch via `page.evaluate` and re-navigate to the
URL. The cookie persists and FB serves the real page. This is a
workaround, not a fix — every JS-heavy site exhibits the same SSR-only
behavior until its bootstrap is manually triggered.

### Impact

Modern web apps don't render server-side. Without inline-`<script>`
execution, Obscura cannot navigate Twitter/X, Facebook, LinkedIn,
Instagram, or any other SPA past the initial SSR shell.

---

## 2. Several Playwright CDP methods are unimplemented

When Playwright issues these calls, Obscura replies with
`Unknown Page method` errors that Playwright surfaces as
`Protocol error` exceptions:

| Playwright API | Obscura response |
|---|---|
| `page.reload()` | `Protocol error (Page.reload): Unknown Page method: reload` |
| `page.set_content("…")` | `Page.set_content: Timeout 30000ms exceeded` (no `load` event ever fires) |
| `page.goto("data:text/html,…")` | `Protocol error (Page.navigate): Network error … builder error: invalid format (source: Some(InvalidUri(InvalidFormat)))` |

### Repro (Page.reload)

```python
await page.goto("https://example.com", wait_until="domcontentloaded")
await page.reload(wait_until="domcontentloaded")
# → playwright._impl._errors.Error: Page.reload: Protocol error
#   (Page.reload): Unknown Page method: reload
```

### Repro (data: URL)

```python
await page.goto("data:text/html,<h1>hi</h1>", wait_until="domcontentloaded")
# → builder error: invalid format (source: Some(InvalidUri(InvalidFormat)))
```

### Impact

Any tooling that uses these methods — and they're standard CDP, not
exotic — has to special-case Obscura. `set_content` is the canonical way
to inject HTML for offline parsing; `reload` is mandatory for OAuth /
captcha flows; `data:` URLs are used by Playwright itself in some
default flows.

---

## 3. CDP server binds to `127.0.0.1` only (cross-container blocker)

In a container, `obscura serve --port 9222` binds the listener to the
container's loopback. From `/proc/net/tcp` inside the container:

```
local_address  state
0100007F:2406  0A   # 127.0.0.1:9222
0100007F:2407  0A   # 127.0.0.1:9223
0100007F:2408  0A   # 127.0.0.1:9224
```

So any client outside the container (sibling docker service, host process)
sees `ECONNREFUSED` on the published port even though Docker DNS resolves
the container correctly. The container's `EXPOSE 9222` and
`-p 9222:9222` mapping have no effect because nothing is listening on
the external interface.

There's also no `--host`/`--bind` flag in `obscura serve --help`.

### Repro

```bash
docker run -d --name obscura -p 9222:9222 obscura serve --port 9222
curl -v http://localhost:9222/json/version
# → curl: (56) Recv failure: Connection reset by peer
```

### Workaround

Add an nginx reverse proxy inside the same container that listens on
`0.0.0.0:9222` and forwards to `127.0.0.1:9222` / `127.0.0.1:9223`. Also
rewrite the `webSocketDebuggerUrl` in `/json/version` because Playwright
uses the advertised URL verbatim (no host substitution — see
`chromium.js:343 urlToWSEndpoint`) and the response would otherwise
point clients at `ws://127.0.0.1:9223/devtools/browser`. Full config in
this repo at `docker/obscura-nginx.conf` / `docker/obscura-entrypoint.sh`.

### Suggested fix

Add a `--host <addr>` flag (default `127.0.0.1`, suggest `0.0.0.0` for
docker images) and ensure the discovery JSON either binds to the same
host or returns a URL templated from the request's `Host:` header.

---

## Why these together matter

Issues 1 + 2 mean Obscura is currently usable for static-DOM scraping
only. Anything client-rendered fails silently — the SSR shell renders,
no errors are thrown, but the page never advances. A user wiring Obscura
to a real target spends time on selectors and finds out the hard way
that the DOM they're targeting was never going to render.

Happy to test patches against the FB Ads Library workload that exposed
all three — it's a thorough reproducer.
