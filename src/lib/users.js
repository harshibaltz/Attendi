import api from './api';

const toData = async (promise) => {
  const res = await promise;
  const body = res?.data;
  if (body && typeof body === 'object' && 'data' in body) return body.data;
  return body;
};

/**
 * Admin user directory and account-state changes.
 *
 * The list endpoint is admin-only. Changing another account's status requires
 * a SYSTEM_ADMIN; restoring an archived (self-deleted) account resets both
 * `status` and `is_active` server-side, so sign-in works again immediately.
 */
export const usersApi = {
  list: () => toData(api.get('/users/')),
  setStatus: (userId, status) => toData(api.patch(`/users/${userId}/`, { status })),
};

export default usersApi;
