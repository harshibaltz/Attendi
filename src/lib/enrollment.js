import api from './api';

const toData = async (promise) => {
  const res = await promise;
  const body = res?.data;
  if (body && typeof body === 'object' && 'data' in body) return body.data;
  return body;
};

/**
 * Course registration and carry-over applications.
 *
 * Both hang off the student's own record, and both depend on the active
 * semester existing -- without one the backend answers
 * `NO_ACTIVE_SEMESTER`, which is worth surfacing rather than showing an
 * empty list that looks like "nothing to register for".
 */
export const enrollmentApi = {
  // GET returns { semester, registration_deadline, level, department, courses[] }
  availableCourses: () => toData(api.get('/students/me/available-courses/')),
  register: (offeringIds) => toData(api.post('/students/me/register/', { offering_ids: offeringIds })),
  myCourses: () => toData(api.get('/students/me/courses/')),
  dropCourse: (offeringId, studentId) => toData(api.delete(`/course-offerings/${offeringId}/enrollments/${studentId}/`)),

  // Students see their own applications, staff see all of them.
  listCarryOver: (status) =>
    toData(api.get('/carry-over/', status ? { params: { status } } : undefined)),
  applyCarryOver: (courseOfferingId, reason) =>
    toData(api.post('/carry-over/apply/', { course_offering_id: courseOfferingId, reason })),
  // Approving is what actually creates the enrollment (BR-031).
  reviewCarryOver: (applicationId, decision, note) =>
    toData(api.post(`/carry-over/${applicationId}/review/`, { decision, note })),
};

/** Pull the human message out of the standard error envelope. */
export const errorMessage = (err, fallback = 'Something went wrong.') => {
  const body = err?.response?.data;
  const candidate = body?.error?.message
    || body?.message
    || (typeof body?.error === 'string' ? body.error : '');

  // Axios's default text ("Request failed with status code 500") tells a user
  // nothing useful, so translate the status instead of surfacing it.
  if (candidate && !/request failed with status code/i.test(candidate)) return candidate;

  const status = err?.response?.status;
  if (!err?.response) return 'Network problem. Check your connection and try again.';
  if (status === 400) return 'Some of the information is not valid. Please check it and try again.';
  if (status === 401) return 'Your session has expired. Please sign in again.';
  if (status === 403) return 'You do not have permission to do that.';
  if (status === 404) return 'We could not find what you were looking for.';
  if (status === 409) return 'That conflicts with something that already exists.';
  if (status === 429) return 'Too many requests. Please wait a moment and try again.';
  if (status >= 500) return 'The server had a problem. Please try again shortly.';
  return fallback;
};

export default enrollmentApi;
