import axios from 'axios';

// Same backend, same client, whether this is running in a browser tab or wrapped
// by Capacitor on a phone - that's the whole point of the "mirror app" approach.
const BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

export const api = axios.create({ baseURL: BASE_URL });

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('wandor_token');
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

export async function login(phone: string, password: string) {
  const { data } = await api.post('/auth/login', { phone, password });
  localStorage.setItem('wandor_token', data.access_token);
  return data;
}

export async function scheduleClass(payload: {
  batch: string; subject: string; start_time: string; end_time: string;
}) {
  const { data } = await api.post('/classes', payload);
  return data;
}

export async function cancelClass(classId: string, reason?: string) {
  const { data } = await api.post(`/classes/${classId}/cancel`, { reason });
  return data;
}

export async function listClasses() {
  const { data } = await api.get('/classes');
  return data;
}

export async function startTestAttempt(testId: string, studentId: string) {
  const { data } = await api.post(`/tests/${testId}/start`, null, { params: { student_id: studentId } });
  return data;
}

export async function submitTestAttempt(attemptId: string, answers: { question_id: string; chosen_option: string }[]) {
  const { data } = await api.post(`/tests/attempts/${attemptId}/submit`, { answers });
  return data;
}

export async function flagAttempt(attemptId: string, eventType: string) {
  const { data } = await api.post('/tests/attempts/flag', {
    attempt_id: attemptId,
    event_type: eventType,
    timestamp: new Date().toISOString(),
  });
  return data;
}

export async function listDueFees() {
  const { data } = await api.get('/payments/due');
  return data;
}

export async function createPaymentOrder(feeRecordId: string) {
  const { data } = await api.post('/payments/create-order', { fee_record_id: feeRecordId });
  return data;
}
