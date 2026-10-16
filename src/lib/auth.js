import api from './api';

export const authApi = {
  login: (credentials) => api.post('/auth/login/', credentials),
  logout: () => api.post('/auth/logout/'),
  me: () => api.get('/auth/me/'),
  refresh: () => api.post('/auth/refresh/'),
  changePassword: (data) => api.post('/auth/change-password/', data),
  selfRegister: (data) => api.post('/auth/self-register/', data),
  requestOtp: (data) => api.post('/auth/forgot-password/request-otp/', data),
  verifyOtp: (data) => api.post('/auth/reset-password/verify-otp/', data),
  confirmReset: (data) => api.post('/auth/reset-password/confirm/', data),
};