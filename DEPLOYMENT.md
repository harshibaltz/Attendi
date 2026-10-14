# Deployment: the iOS login bounce

## The symptom

Signing in returned a spinner, then the user landed back on the login page.
Desktop Chrome and Android were fine. **iPhone Safari was not.**

## Root cause

The SPA and the Django API were two different origins:

```
https://fet-platform.vercel.app        <- SPA (frontend-wirsiy project)
https://<api-project>.vercel.app       <- API (backend project)
```

Both are Vercel, but **"both on Vercel" does not mean same-origin.**
`vercel.app` is on the [Public Suffix List](https://publicsuffix.org), so each
project's `*.vercel.app` hostname is its own *registrable domain* ("site").
The browser therefore treats every API call as a **cross-site** request, which
makes the JWT cookies **third-party cookies**.

iOS Safari's Intelligent Tracking Prevention (ITP) **discards third-party
cookies outright** — regardless of `SameSite` or `Secure`. The failure is silent
and looks like a redirect bug:

1. `POST /api/v1/auth/login/` → **200 OK**, `Set-Cookie` sent...
2. ...and Safari throws the cookie away.
3. `Login.jsx` optimistically calls `onLogin(user)` — login "succeeds".
4. Dashboard mounts, fires `GET /dashboard/` → no cookie → **401**.
5. The axios interceptor tries `/auth/refresh/` → also cookie-less → fails.
6. `window.location.href = '/login'` → hard reload → **back to login**.

Chrome/Android still allow 3P cookies, so only iPhone users were affected.

## The fix: one origin

Rewrite `/api/*` on the **frontend** project so Vercel proxies it server-side.
The browser only ever talks to one origin, the cookies are first-party, and ITP
never engages.

`frontend-wirsiy/vercel.json`:

```json
{
  "rewrites": [
    { "source": "/api/:path*", "destination": "https://YOUR_BACKEND.vercel.app/api/:path*" },
    { "source": "/(.*)",       "destination": "/index.html" }
  ]
}
```

> Order matters — Vercel applies the first matching rewrite. The `/api` rule
> must come before the SPA catch-all, or every API call would return `index.html`.

Replace `YOUR_BACKEND.vercel.app` with the backend project's real hostname, then
redeploy the **frontend** project. Custom domains work identically: point the
rewrite at the backend's custom domain if it has one.

`src/lib/api.js` now defaults to a relative base URL (`/api/v1`), so no
`VITE_API_BASE` is needed in production. Setting it is still supported for a
local dev server talking to a remote API.

## Backend configuration

```env
COOKIE_SAMESITE=Lax          # NOT "None" — see below
COOKIE_SECURE=True
COOKIE_DOMAIN=               # empty = host-only, correct behind the rewrite
```

With one origin, `Lax` is correct *and* more secure than `None`: the browser
still withholds the cookie on cross-site POSTs, which keeps CSRF protection.

`python manage.py check` warns (`fet.W005` / `fet.W006`, **not** an error) if
`COOKIE_SAMESITE=None`, because that is the setting that breaks iPhone. It is a
warning deliberately — the deploy runs `createcachetable` as its build command,
so an error-level check would fail the build outright.

## If you must keep two origins

`SameSite=None; Secure` is *necessary* for cross-site cookies but not
*sufficient* on Safari. The only additional lever is CHIPS
(`Partitioned`), which Safari 17+/iOS 17+ honours:

```env
COOKIE_SAMESITE=None
COOKIE_PARTITIONED=True     # auto-enabled whenever SameSite is "None"
```

This is applied to the CSRF cookie too — a mismatched `Partitioned` flag makes
Safari treat it as a separate cookie.

> **Note:** Django's `set_cookie()` has **no** `partitioned` keyword (checked on
> Django 6.0) — passing one is silently dropped. The backend therefore sets the
> flag on the `http.cookies.Morsel` object Django already stores, which supports
> `Partitioned` natively but **only on Python 3.14+**. Below that the flag is
> skipped and you are back to plain third-party cookies.

Either way, iOS **< 17 still will not work**; there is no attribute that fixes
that. Same-origin is the only complete answer.

## Two related bugs found and fixed

**1. `/auth/refresh/` returned HTTP 500 on every call.**
`views_auth.py` called `RefreshToken.rotate()`, which does not exist in
SimpleJWT, so it raised `AttributeError`. Since the interceptor treats any failed
refresh as a dead session, every user was silently logged out the moment their
2-hour access token expired. It now delegates to SimpleJWT's
`TokenRefreshSerializer`, which handles rotation and blacklisting correctly.

**2. A refresh race could log out healthy users.**
`SIMPLE_JWT` has `ROTATE_REFRESH_TOKENS` + `BLACKLIST_AFTER_ROTATION`. The
dashboard fires several requests at once; each 401 used to trigger its *own*
refresh, so the 2nd..Nth presented an already-blacklisted token and failed.
`src/lib/api.js` now uses a single-flight lock, so concurrent 401s share one
rotation.

## Verifying the fix

1. iPhone Safari → sign in. You should reach the dashboard and **stay** there.
2. Safari → Storage → confirm `fet_access`/`fet_refresh` under the SPA's domain.
3. Wait past the access-token lifetime (`ACCESS_TOKEN_MINUTES`, default 120) and
   confirm an API call transparently refreshes instead of logging you out.
4. Desktop Chrome must still work — same-origin should not regress it.

## Regression tests

`backend/tests/test_auth_cookies.py` locks in the cookie contract: `SameSite`
value, `Partitioned` presence, cookie paths, CSRF cookie readability,
`httpOnly` on the tokens, refresh re-setting cookies, and logout clearing them
with matching paths.