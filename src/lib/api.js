import axios from 'axios';

/**
 * Same-origin by default.
 *
 * `vercel.json` rewrites `/api/*` to the Django backend, so the browser talks
 * to one origin. That matters for Safari: the JWTs live in httpOnly cookies
 * set by the API, and a *cross-site* cookie is a third-party cookie, which
 * iOS Safari (ITP) discards regardless of SameSite/Secure. A same-origin
 * request makes them first-party, so ITP never applies.
 *
 * Leave VITE_API_BASE unset in production. It is only useful for pointing a
 * local dev server at a remote API; the local Vite dev proxy already handles
 * `/api`, so an empty value is correct there too.
 */
const API_BASE = import.meta.env.VITE_API_BASE || '';

// JWTs live ONLY in httpOnly cookies (set by the backend). This client never
// reads or writes tokens from JS-accessible storage, so an XSS cannot steal them.
const api = axios.create({
  baseURL: `${API_BASE}/api/v1`,
  withCredentials: true,
  headers: {
    'Content-Type': 'application/json',
  },
  // Send the Django CSRF cookie back on mutating requests.
  xsrfCookieName: 'csrftoken',
  xsrfHeaderName: 'X-CSRFToken',
});

const AUTH_USER_KEYS = [
  'fet_auth',
  'fet_user',
  'fet_user_role',
  'fet_user_name',
  'access_token',
];

const clearAuthCache = () => {
  AUTH_USER_KEYS.forEach((key) => localStorage.removeItem(key));
};

/**
 * Single-flight refresh.
 *
 * Several requests can 401 at the same moment (the dashboard fans out to
 * multiple endpoints). Without this lock each one fires its own refresh, and
 * because SimpleJWT rotates + blacklists refresh tokens, the 2nd..Nth refresh
 * presents an already-blacklisted token, fails, and logs the user out. Sharing
 * one in-flight promise makes concurrent 401s wait on a single rotation.
 */
let refreshInFlight = null;

const refreshSession = () => {
  if (!refreshInFlight) {
    refreshInFlight = axios
      .post(`${API_BASE}/api/v1/auth/refresh/`, null, { withCredentials: true })
      .finally(() => {
        refreshInFlight = null;
      });
  }
  return refreshInFlight;
};

/**
 * Ask the app shell to drop back to the login screen.
 *
 * Dispatching an event instead of assigning `window.location.href` avoids a
 * full page reload: it keeps the SPA mounted, preserves any deep link, and
 * stops the "401 -> hard redirect -> reload -> 401" loop that left iOS users
 * stuck on the login page.
 */
const notifySessionExpired = () => {
  clearAuthCache();
  window.dispatchEvent(new CustomEvent('fet:session-expired'));
};

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config;
    const status = error.response?.status;
    const url = originalRequest?.url || '';

    if (status === 401 && originalRequest && !originalRequest._retry) {
      // Never try to refresh *while* refreshing, and never bounce the user off
      // the login page because a rejected login/refresh returned 401.
      const isAuthCall = url.includes('/auth/login') || url.includes('/auth/refresh');

      if (!isAuthCall) {
        originalRequest._retry = true;
        try {
          await refreshSession();
          return api(originalRequest);
        } catch {
          notifySessionExpired();
        }
      }
    }
    return Promise.reject(error);
  }
);

export default api;