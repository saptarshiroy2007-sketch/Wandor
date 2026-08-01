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
  localStorage.setItem('wandor_role', 'teacher');
  return data;
}

export async function studentLogin(phone: string, password: string) {
  const { data } = await api.post('/auth/student-login', { phone, password });
  localStorage.setItem('wandor_token', data.access_token);
  localStorage.setItem('wandor_role', 'student');
  return data;
}

export async function parentLogin(studentPhone: string, pin: string) {
  const { data } = await api.post('/auth/parent-login', { student_phone: studentPhone, pin });
  localStorage.setItem('wandor_token', data.access_token);
  localStorage.setItem('wandor_role', 'parent');
  return data;
}

export async function instituteLogin(phone: string, password: string) {
  const { data } = await api.post('/auth/institute-login', { phone, password });
  localStorage.setItem('wandor_token', data.access_token);
  localStorage.setItem('wandor_role', 'institute_admin');
  return data;
}

export function logout() {
  localStorage.removeItem('wandor_token');
  localStorage.removeItem('wandor_role');
}

export function getRole(): 'teacher' | 'student' | 'parent' | 'institute_admin' | null {
  return (localStorage.getItem('wandor_role') as 'teacher' | 'student' | 'parent' | 'institute_admin' | null) ?? null;
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

// student_id no longer passed manually - the backend reads it off the bearer token
// (see get_current_student in auth.py), so this now just needs the test id.
export async function startTestAttempt(testId: string) {
  const { data } = await api.post(`/tests/${testId}/start`);
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

export async function sendFeeRemindersNow() {
  const { data } = await api.post('/payments/send-reminders-now');
  return data; // { checked, sent, failed }
}

// ---------- Students (teacher-facing) ----------
export async function createStudent(payload: {
  name: string; phone: string; parent_phone?: string; batch?: string; password: string;
}) {
  const { data } = await api.post('/students', payload);
  return data;
}

export async function listStudents(batch?: string) {
  const { data } = await api.get('/students', { params: batch ? { batch } : {} });
  return data;
}

export async function bulkImportStudents(file: File) {
  const form = new FormData();
  form.append('file', file);
  const { data } = await api.post('/students/bulk-import', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return data; // { created, skipped, total_rows, created_count, skipped_count }
}

// ---------- Uploads (teacher-facing) ----------
export async function uploadTestDocument(file: File) {
  const form = new FormData();
  form.append('file', file);
  const { data } = await api.post('/uploads/test-document', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return data; // { url, filename }
}

// ---------- Attendance ----------
export async function markAttendance(classSessionId: string, marks: { student_id: string; present: boolean }[]) {
  const { data } = await api.post('/attendance/mark', { class_session_id: classSessionId, marks });
  return data;
}

export async function getClassAttendance(classSessionId: string) {
  const { data } = await api.get(`/attendance/class/${classSessionId}`);
  return data;
}

export async function myAttendanceSummary() {
  const { data } = await api.get('/attendance/me/summary');
  return data;
}

export async function studentAttendanceSummary(studentId: string) {
  const { data } = await api.get(`/attendance/student/${studentId}/summary`);
  return data; // { student_id, total_classes, present_count, attendance_pct }
}

export async function batchAttendanceAnalytics(batch: string) {
  const { data } = await api.get(`/attendance/batch/${encodeURIComponent(batch)}/analytics`);
  return data; // { batch, student_count, batch_average_pct, students: [...] }
}

// ---------- Parents (parent-facing, read-only) ----------
export async function myChild() {
  const { data } = await api.get('/parents/me');
  return data;
}

export async function myChildAttendance() {
  const { data } = await api.get('/parents/attendance');
  return data;
}

export async function myChildFees() {
  const { data } = await api.get('/parents/fees');
  return data;
}

export async function myChildTests() {
  const { data } = await api.get('/parents/tests');
  return data;
}

// ---------- Tests ----------
export async function createMcqTest(payload: {
  title: string; topic: string; num_questions: number; duration_minutes: number;
}) {
  const { data } = await api.post('/tests/mcq', payload);
  return data; // { test_id, questions_generated }
}

export async function createDocumentTest(payload: {
  title: string; document_url: string; duration_minutes: number;
}) {
  const { data } = await api.post('/tests/document', payload);
  return data; // { test_id }
}

export async function listTests() {
  const { data } = await api.get('/tests');
  return data;
}

export async function listAvailableTests() {
  const { data } = await api.get('/tests/available');
  return data;
}

export async function testAnalytics(testId: string) {
  const { data } = await api.get(`/tests/${testId}/analytics`);
  return data; // { test_id, title, attempt_count, average_score, average_score_pct, weak_question_count, questions: [...] }
}

// ---------- Students: set parent PIN (teacher-facing) ----------
export async function setParentPin(studentId: string, pin: string) {
  const { data } = await api.post(`/students/${studentId}/set-parent-pin`, { pin });
  return data;
}

// ---------- Institute (institute-admin dashboard) ----------
export async function getInstitute() {
  const { data } = await api.get('/institute/me');
  return data;
}

export async function updateInstitute(name: string) {
  const { data } = await api.patch('/institute/me', { name });
  return data;
}

export async function listInstituteTeachers() {
  const { data } = await api.get('/institute/teachers');
  return data;
}

export async function createTeacher(payload: { name: string; phone: string; password: string; is_owner?: boolean }) {
  const { data } = await api.post('/institute/teachers', payload);
  return data;
}

export async function deleteTeacher(teacherId: string) {
  const { data } = await api.delete(`/institute/teachers/${teacherId}`);
  return data;
}
