import api from './api';
import { authApi } from './auth';

const unwrap = (res) => (res?.data && typeof res.data === 'object' && 'data' in res.data ? res.data.data : res?.data);

export const profileApi = {
  me: () => authApi.me().then(unwrap),
  updateMe: (data) => api.patch('/auth/me/', data).then(unwrap),
  activity: (studentId) =>
    api.get(studentId ? `/students/${studentId}/activity/` : '/students/me/activity/').then(unwrap),
};

export const normalizeRole = (role) => {
  const r = (role || '').toLowerCase();
  if (r === 'student' || r === 'lecturer') return r;
  if (r.endsWith('_admin')) return 'admin';
  return r || 'student';
};

export const getDisplayName = (user, fallback = '') => {
  if (!user) return fallback;
  const full = user.fullName || user.full_name;
  if (full) return full;
  const joined = [user.first_name, user.last_name].filter(Boolean).join(' ').trim();
  return joined || user.email?.split('@')[0] || fallback;
};

export const normalizeUser = (user) => (
  user ? { ...user, fullName: getDisplayName(user, user.fullName || '') } : user
);

export default profileApi;