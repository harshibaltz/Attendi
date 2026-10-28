/**
 * Self-healing against a service worker pinned to an old build.
 *
 * This app has never shipped a service worker, but if any earlier deployment
 * on this origin ever registered one, it keeps answering navigations from its
 * own cache — and no HTTP cache header can get past that (a SW cache ignores
 * Cache-Control entirely, and a phone's "hard refresh" does not exist).
 * Clearing registrations and Cache Storage on boot costs nothing when there
 * is none, and unpins the device when there is.
 */
export const clearStaleServiceWorkers = async () => {
  if (typeof navigator === 'undefined' || !('serviceWorker' in navigator)) return;

  try {
    const registrations = await navigator.serviceWorker.getRegistrations();
    await Promise.all(registrations.map((registration) => registration.unregister()));
  } catch {
    /* not supported or already gone */
  }

  try {
    if (typeof caches !== 'undefined' && caches.keys) {
      const keys = await caches.keys();
      await Promise.all(keys.map((key) => caches.delete(key)));
    }
  } catch {
    /* Cache Storage unavailable (private mode) */
  }
};

export default clearStaleServiceWorkers;
