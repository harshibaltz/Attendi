import { useEffect, useRef, useState } from 'react';
import { RefreshCw } from 'lucide-react';

/**
 * Converges every device onto the newest build.
 *
 * Phone browsers keep tabs alive for days, and a tab that is never reloaded
 * keeps running the JS it loaded when it opened — so one device gets a deploy
 * and another, older tab, does not. This asks the server which bundle it is
 * serving now, and when it differs from the one in memory, reloads (if the
 * user is idle, so nothing in progress is lost) or offers a Reload button.
 *
 * It runs outside the Router on purpose: the login and loading screens are
 * rendered without one, and a stale tab parked on the login screen is exactly
 * the case this has to cover.
 */

const IDLE_MS = 45 * 1000;      // no input for this long -> safe to reload
const CHECK_MS = 5 * 60 * 1000; // background re-check cadence
const FIRST_CHECK_MS = 8 * 1000; // let first paint settle before checking

/** The module script the current index.html points at: /assets/index-<hash>.js */
const loadedBundle = () => {
  const el = document.querySelector('script[type="module"][src]');
  return el ? el.getAttribute('src').split('?')[0] : null;
};

/**
 * What index.html points at *right now*. The unique query string bypasses the
 * browser cache and the CDN edge, so this can never answer with the shell the
 * tab is already running.
 */
const deployedBundle = async () => {
  const res = await fetch(`/?fet-build=${Date.now()}`, { cache: 'no-store' });
  if (!res.ok) return null;
  const html = await res.text();
  const match = html.match(/<script type="module"[^>]*src="([^"]+)"/);
  return match ? match[1] : null;
};

const isEditing = (el) =>
  Boolean(
    el &&
      (el.isContentEditable ||
        ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName))
  );

const UpdateNotifier = () => {
  const [pending, setPending] = useState(false);
  const pendingRef = useRef(false);
  const checkingRef = useRef(false);
  const lastActivity = useRef(Date.now());

  useEffect(() => {
    // Dev server has no hashed bundles to compare, and its HTML is not cached.
    if (!import.meta.env.PROD) return undefined;

    const markPending = () => {
      if (pendingRef.current) return;
      pendingRef.current = true;
      setPending(true);
    };

    const reloadIfIdle = () => {
      const idle = Date.now() - lastActivity.current > IDLE_MS;
      if (pendingRef.current && idle && !isEditing(document.activeElement)) {
        window.location.reload();
        return true;
      }
      return false;
    };

    const check = async () => {
      if (checkingRef.current || document.hidden) return;
      checkingRef.current = true;
      try {
        const remote = await deployedBundle();
        const local = loadedBundle();
        if (remote && local && remote !== local) markPending();
      } catch {
        // Offline or a transient network error — the next tick retries.
      } finally {
        checkingRef.current = false;
      }
      reloadIfIdle();
    };

    const onVisible = () => {
      if (document.hidden) return;
      // An update already found while hidden: apply it if it cannot
      // interrupt anything, otherwise ask.
      if (pendingRef.current) {
        if (!reloadIfIdle()) setPending(true);
        return;
      }
      check();
    };

    // Activity tracking so an auto-reload never lands mid-task.
    const noteActivity = () => {
      lastActivity.current = Date.now();
    };
    const activityEvents = ['pointerdown', 'keydown', 'input', 'wheel'];
    activityEvents.forEach((evt) =>
      window.addEventListener(evt, noteActivity, { passive: true, capture: true })
    );

    document.addEventListener('visibilitychange', onVisible);
    window.addEventListener('focus', onVisible);
    window.addEventListener('pageshow', onVisible); // restored from bfcache

    const first = window.setTimeout(check, FIRST_CHECK_MS);
    const interval = window.setInterval(check, CHECK_MS);

    return () => {
      window.clearTimeout(first);
      window.clearInterval(interval);
      document.removeEventListener('visibilitychange', onVisible);
      window.removeEventListener('focus', onVisible);
      window.removeEventListener('pageshow', onVisible);
      activityEvents.forEach((evt) =>
        window.removeEventListener(evt, noteActivity, { capture: true })
      );
    };
  }, []);

  if (!pending) return null;

  return (
    <div
      className="pointer-events-none fixed inset-x-0 top-0 z-[200] flex justify-center p-3"
      role="status"
      aria-live="polite"
    >
      <div className="pointer-events-auto flex max-w-[min(92vw,34rem)] items-center gap-3 rounded-xl border border-border-default bg-surface px-4 py-3 shadow-lg">
        <span
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-white"
          style={{ backgroundColor: '#3F35B5' }}
        >
          <RefreshCw size={15} />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-[13px] font-semibold text-text-primary">
            A new version is available
          </p>
          <p className="text-[12px] text-text-secondary">
            Reload to get the latest updates.
          </p>
        </div>
        <button
          type="button"
          className="fet-btn-primary inline-flex shrink-0 items-center gap-1.5 text-[12px]"
          onClick={() => window.location.reload()}
        >
          Reload
        </button>
      </div>
    </div>
  );
};

export default UpdateNotifier;
