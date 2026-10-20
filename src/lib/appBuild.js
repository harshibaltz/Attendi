/* global __APP_BUILD__ */

/**
 * The build id Vite baked in at build time (the short git sha).
 *
 * Shown on the Profile page so "which version is this device on?" is a
 * five-second question instead of a debugging session — a device running an
 * old bundle simply will not show the line at all.
 */
export const APP_BUILD =
  typeof __APP_BUILD__ === 'string' ? __APP_BUILD__ : 'dev';

export default APP_BUILD;
