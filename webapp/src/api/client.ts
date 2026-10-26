import axios from 'axios';

// Same backend, same client, whether this is running in a browser tab or wrapped
// by Capacitor on a phone - that's the whole point of the "mirror app" approach.
export const BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

export const api = axios.create({ baseURL: BASE_URL });

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('wandor_token');
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// A locked account gets 403 + X-Account-Status from every guarded route. Send the user to the
// locked screen (never from the locked/login pages themselves, to avoid a redirect loop). The
// can-pay header is only sent to payers; remember it for the locked screen's Billing link.
const CAN_PAY_KEY = 'wandor_can_pay';
export function canPayFlag(): boolean {
  try { return sessionStorage.getItem(CAN_PAY_KEY) === '1'; } catch { return false; }
}
function clearCanPay() {
  try { sessionStorage.removeItem(CAN_PAY_KEY); } catch { /* storage unavailable */ }
}
api.interceptors.response.use(
  (res) => res,
  (err) => {
    const h = err?.response?.headers;
    const why = err?.response?.status === 403 ? h?.['x-account-status'] : null;
    if (why === 'banned_payment' || why === 'banned_admin') {
      try {
        if (h?.['x-account-can-pay'] === '1') sessionStorage.setItem(CAN_PAY_KEY, '1');
        else sessionStorage.removeItem(CAN_PAY_KEY);
      } catch { /* storage unavailable */ }
      const path = window.location.pathname;
      if (path !== '/account-locked' && !/login$/.test(path)) {
        window.location.assign(`/account-locked?why=${why}`);
      }
    }
    return Promise.reject(err);
  },
);

export async function login(phone: string, password: string) {
  const { data } = await api.post('/auth/login', { phone, password });
  localStorage.setItem('wandor_token', data.access_token);
  clearCanPay();
  localStorage.setItem('wandor_role', 'teacher');
  return data;
}

/** Thrown by studentLogin/parentLogin when one phone+PIN matches several accounts (a child with two
 *  tutors). The login page shows `choices` and retries with the picked student id. */
export class AccountChoiceError extends Error {
  choices: { student_id: string; label: string }[];
  constructor(choices: { student_id: string; label: string }[]) {
    super('Pick an account');
    this.choices = choices;
  }
}

function asChoiceError(err: any): never {
  const d = err?.response?.data?.detail;
  if (err?.response?.status === 409 && d && Array.isArray(d.choices)) throw new AccountChoiceError(d.choices);
  throw err;
}

/** The API sends instants as UTC with a trailing Z; <input type="datetime-local"> wants LOCAL
 *  'YYYY-MM-DDTHH:mm'. (The old code sliced the string, which showed UTC clock time as if local.) */
export function toLocalInput(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** Stored document URLs may be relative ('/uploads/x.pdf' from local storage) - those live on the
 *  API server, not on whatever host serves this web app. */
export function resolveApiUrl(url: string): string {
  return url.startsWith('/') ? `${BASE_URL}${url}` : url;
}

export async function studentLogin(phone: string, password: string, studentId?: string) {
  let data;
  try {
    ({ data } = await api.post('/auth/student-login', { phone, password, student_id: studentId }));
  } catch (err) { asChoiceError(err); }
  localStorage.setItem('wandor_token', data.access_token);
  clearCanPay();
  localStorage.setItem('wandor_role', 'student');
  return data;
}

export async function parentLogin(studentPhone: string, pin: string, studentId?: string) {
  let data;
  try {
    ({ data } = await api.post('/auth/parent-login', { student_phone: studentPhone, pin, student_id: studentId }));
  } catch (err) { asChoiceError(err); }
  localStorage.setItem('wandor_token', data.access_token);
  clearCanPay();
  localStorage.setItem('wandor_role', 'parent');
  return data;
}

export async function instituteLogin(phone: string, password: string) {
  const { data } = await api.post('/auth/institute-login', { phone, password });
  localStorage.setItem('wandor_token', data.access_token);
  clearCanPay();
  localStorage.setItem('wandor_role', 'institute_admin');
  return data;
}

export type ResetRole = 'teacher' | 'student' | 'institute_admin';

export async function requestPasswordReset(role: ResetRole, phone: string, instituteId?: string) {
  const { data } = await api.post('/auth/password-reset/request', {
    role, phone, institute_id: instituteId || undefined,
  });
  return data as { message: string };
}

export async function confirmPasswordReset(
  role: ResetRole, phone: string, code: string, newPassword: string, instituteId?: string,
) {
  // Mirrors login()/studentLogin()/instituteLogin() - a successful reset logs the
  // user straight in, no need to make them type their brand-new password again.
  const { data } = await api.post('/auth/password-reset/confirm', {
    role, phone, code, new_password: newPassword, institute_id: instituteId || undefined,
  });
  localStorage.setItem('wandor_token', data.access_token);
  clearCanPay();
  localStorage.setItem('wandor_role', role);
  return data;
}

export async function teacherSignup(name: string, phone: string, password: string) {
  // Always creates an INDEPENDENT teacher - there's no institute selector on this
  // form on purpose. An independent teacher who later needs to join an institute
  // does it afterwards, from their own account, via joinInstitute() below.
  //
  // No token here anymore - signup now only sends an OTP to verify the phone; the
  // account can't log in until verifyTeacherSignup() below confirms it. See
  // ForgotPassword-style two-step flow in TeacherSignup.tsx.
  const { data } = await api.post('/auth/teacher-signup', { name, phone, password });
  return data as { phone: string; message: string };
}

export async function verifyTeacherSignup(phone: string, code: string) {
  const { data } = await api.post('/auth/teacher-signup/verify', { phone, code });
  localStorage.setItem('wandor_token', data.access_token);
  clearCanPay();
  localStorage.setItem('wandor_role', 'teacher');
  return data;
}

export async function instituteSignup(name: string, ownerPhone: string, password: string) {
  const { data } = await api.post('/auth/institute-signup', {
    name, owner_phone: ownerPhone, password,
  });
  return data as { phone: string; message: string };
}

export async function verifyInstituteSignup(ownerPhone: string, code: string) {
  const { data } = await api.post('/auth/institute-signup/verify', { phone: ownerPhone, code });
  localStorage.setItem('wandor_token', data.access_token);
  clearCanPay();
  localStorage.setItem('wandor_role', 'institute_admin');
  return data;
}

export function logout() {
  localStorage.removeItem('wandor_token');
  localStorage.removeItem('wandor_role');
  clearCanPay();
}

export type Role = 'teacher' | 'student' | 'parent' | 'institute_admin' | 'platform_admin';
export function getRole(): Role | null {
  return (localStorage.getItem('wandor_role') as Role | null) ?? null;
}

// ---------- Theme toggle — wired to [data-theme="dark"] on <html> ----------
// Call setTheme(true) from the Settings page when the user flips the dark-mode switch.
// The preference is stored in localStorage so index.html's inline script can apply it
// before React hydrates, preventing the white flash on dark-mode users.
export function setTheme(dark: boolean): void {
  if (dark) {
    document.documentElement.setAttribute('data-theme', 'dark');
    localStorage.setItem('wandor_theme', 'dark');
  } else {
    document.documentElement.removeAttribute('data-theme');
    localStorage.setItem('wandor_theme', 'light');
  }
}

export function isDarkTheme(): boolean {
  return localStorage.getItem('wandor_theme') === 'dark';
}

// ---------- Profile + password change ----------
export interface MyProfile {
  id: string;
  name: string;
  phone: string;
  institute_id?: string | null;
  bio?: string | null;
  photo_url?: string | null;
  education?: string | null; // teacher only
  email?: string | null;
  profile_completion_pct: number;
}

export async function getMyProfile(): Promise<MyProfile> {
  // Teacher-only endpoint. Students/parents/institute-admins have their own /me routes.
  const { data } = await api.get('/auth/me');
  return data;
}

export async function updateMyProfile(payload: {
  name?: string; bio?: string; education?: string; email?: string;
}): Promise<MyProfile> {
  const { data } = await api.patch('/auth/me', payload);
  return data;
}

export async function getMyStudentProfile(): Promise<MyProfile> {
  const { data } = await api.get('/students/me');
  return data;
}

export async function updateMyStudentProfile(payload: {
  name?: string; bio?: string; email?: string;
}): Promise<MyProfile> {
  const { data } = await api.patch('/students/me', payload);
  return data;
}

export async function getMyInstituteProfile(): Promise<MyProfile> {
  const { data } = await api.get('/institute/me');
  return data;
}

export async function updateMyInstituteProfile(payload: {
  name: string; bio?: string; email?: string;
}): Promise<MyProfile> {
  const { data } = await api.patch('/institute/me', payload);
  return data;
}

export async function uploadProfilePhoto(role: 'teacher' | 'student' | 'institute_admin', file: File): Promise<string> {
  const form = new FormData();
  form.append('file', file);
  const endpoint = role === 'institute_admin' ? 'institute' : role;
  const { data } = await api.post(`/uploads/profile-photo/${endpoint}`, form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return data.url as string;
}

export async function changePassword(old_password: string, new_password: string): Promise<void> {
  await api.post('/auth/change-password', { old_password, new_password });
}

export async function joinInstitute(instituteOwnerPhone: string, institutePassword: string) {
  // For an independent teacher attaching their existing account to an institute -
  // see TeacherJoinInstitute on the backend for why this reuses the institute's own
  // login as the "invite code" instead of a separate invite-code system.
  const { data } = await api.post('/auth/teacher/join-institute', {
    institute_owner_phone: instituteOwnerPhone,
    institute_password: institutePassword,
  });
  return data as { id: string; name: string; phone: string; institute_id: string | null };
}

export interface BatchOut {
  id: string;
  name: string;
}

export async function listBatches() {
  const { data } = await api.get('/batches');
  return data as BatchOut[];
}

export async function createBatch(name: string) {
  const { data } = await api.post('/batches', { name });
  return data as BatchOut;
}

export async function renameBatch(batchId: string, name: string) {
  const { data } = await api.patch(`/batches/${batchId}`, { name });
  return data as BatchOut;
}

export async function deleteBatch(batchId: string) {
  const { data } = await api.delete(`/batches/${batchId}`);
  return data;
}

export async function scheduleClass(payload: {
  batch_id: string; subject: string; start_time: string; end_time: string;
}) {
  const { data } = await api.post('/classes', payload);
  return data;
}

export async function cancelClass(classId: string, reason?: string) {
  const { data } = await api.post(`/classes/${classId}/cancel`, { reason });
  return data;
}

export async function rescheduleClass(classId: string, payload: { start_time: string; end_time: string; reason?: string }) {
  const { data } = await api.post(`/classes/${classId}/reschedule`, payload);
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

export async function createPaymentOrder(feeRecordId: string, amount?: number) {
  const { data } = await api.post('/payments/create-order', { fee_record_id: feeRecordId, ...(amount ? { amount } : {}) });
  return data;
}

export async function sendFeeRemindersNow() {
  const { data } = await api.post('/payments/send-reminders-now');
  return data as { checked: number; sent: number; failed: number; skipped_plan: number };
}

// ---------- Fees: teacher side ----------
export interface FeeRecordDetail {
  id: string; student_id: string; student_name: string; batch_name: string | null;
  amount_due: number; amount_paid: number; is_paid: boolean; due_date: string;
  paid_at: string | null; description: string | null; payment_mode: string | null;
  duplicate_payment: boolean; // more money taken than owed - the extra needs refunding
  allow_partial: boolean; payments: FeePayment[];
}

export async function listFeeRecords(): Promise<FeeRecordDetail[]> {
  const { data } = await api.get('/payments/records');
  return data;
}

export async function createFees(payload: {
  student_ids?: string[]; batch_id?: string | null; amount: number; due_date: string; description?: string;
  allow_partial?: boolean;
}): Promise<{ created_count: number }> {
  const { data } = await api.post('/payments/fees', payload);
  return data;
}

/** Records money received outside the app. Leave `amount` out for the whole balance. */
export async function markFeePaid(feeId: string, amount?: number): Promise<FeeRecordDetail> {
  const { data } = await api.post(`/payments/fees/${feeId}/mark-paid`, amount ? { amount } : undefined);
  return data;
}

export async function deleteFee(feeId: string): Promise<void> {
  await api.delete(`/payments/fees/${feeId}`);
}

export interface PayoutStatus { configured: boolean; online_fee_collection_allowed: boolean; ready: boolean; }
export async function getPayoutStatus(): Promise<PayoutStatus> {
  const { data } = await api.get('/payments/payout-status');
  return data;
}

// ---------- Fees: student side ----------
export interface FeePayment {
  id: string; amount: number; refunded_amount: number;
  status: 'paid' | 'partially_refunded' | 'refunded'; mode: 'online' | 'manual';
  paid_by: 'student' | 'parent' | 'teacher' | null; paid_at: string | null; receipt_no: string;
}
export interface MyFee {
  id: string; amount_due: number; amount_paid: number; is_paid: boolean; due_date: string;
  paid_at: string | null; description: string | null; payment_mode: string | null;
  allow_partial: boolean; payments: FeePayment[];
}
export interface Receipt {
  receipt_no: string; issued_to: string; issued_by: string; fee_description: string | null;
  fee_total: number; amount: number; refunded_amount: number; status: string; mode: string;
  paid_by: string | null; paid_at: string | null; razorpay_payment_id: string | null; fee_balance: number;
}
/** Fetches a receipt from the endpoint that matches who is logged in. */
export async function getReceipt(paymentId: string): Promise<Receipt> {
  const role = getRole();
  const base = role === 'student' ? '/payments/my-receipts' : role === 'parent' ? '/parents/receipts' : '/payments/receipts';
  const { data } = await api.get(`${base}/${paymentId}`);
  return data;
}
export async function getMyFees(): Promise<{ fees: MyFee[]; online_payment_available: boolean }> {
  const { data } = await api.get('/payments/my-fees');
  return data;
}

export async function verifyFeePayment(p: { razorpay_order_id: string; razorpay_payment_id: string; razorpay_signature: string }) {
  const { data } = await api.post('/payments/verify', p);
  return data;
}

// ---------- Billing (institute / independent-teacher subscription) ----------
export interface Plan {
  key: string; label: string; price_monthly: number; price_yearly: number;
  max_students: number | null; max_teachers: number | null; online_fee_collection: boolean;
  fee_reminders: boolean; // reminders AND fee/receipt notices
  monthly_available: boolean; yearly_available: boolean;
  // price_monthly / price_yearly are BASE prices in rupees, EXCLUDING GST. These are exact paise.
  gst_rate_percent: number;
  gst_monthly_paise: number; total_monthly_paise: number;
  gst_yearly_paise: number; total_yearly_paise: number;
}
export interface BillingStatus {
  plan: string; plan_label: string;
  status: 'free' | 'trialing' | 'active' | 'past_due' | 'cancelled' | 'expired';
  billing_cycle: 'monthly' | 'yearly' | null;
  current_period_end: string | null; cancel_at_period_end: boolean;
  scheduled_plan: string | null; scheduled_cycle: string | null;
  students_used: number; students_limit: number | null;
  teachers_used: number; teachers_limit: number | null;
  online_fee_collection: boolean; fee_reminders: boolean; can_manage: boolean; owner_kind: 'institute' | 'teacher';
  // After an "upgrade now": 'scheduled' (next renewal at the new price), 'reauthorise' (subscribe again
  // to continue), 'failed' (renews at the OLD price, operator alerted), or null.
  upgrade_renewal: 'scheduled' | 'reauthorise' | 'failed' | null;
  access_state: 'active' | 'grace' | 'banned'; access_reason: 'payment' | 'admin' | null; ban_at: string | null;
}
export interface Invoice {
  id: string; invoice_number: string; kind: 'subscription' | 'proration';
  plan: string; plan_label: string; billing_cycle: string | null; description: string | null;
  base_paise: number; gst_rate_percent: number; gst_paise: number; total_paise: number; currency: string;
  period_start: string | null; period_end: string | null; issued_at: string;
}
export interface Seller { legal_name: string; gstin: string; address: string; }
export interface UpgradeQuote {
  from_plan: string; from_plan_label: string; to_plan: string; to_plan_label: string; cycle: string;
  period_start: string; period_end: string; remaining_days: number;
  credit_base_paise: number; charge_base_paise: number; base_paise: number;
  gst_rate_percent: number; gst_paise: number; total_paise: number;
}
export interface UpgradeOrder extends UpgradeQuote { order_id: string; key_id: string; name: string; contact: string; }
export type BillingCycle = 'monthly' | 'yearly';

export async function listPlans(): Promise<Plan[]> {
  const { data } = await api.get('/billing/plans');
  return data;
}
export async function getBillingStatus(): Promise<BillingStatus> {
  const { data } = await api.get('/billing/me');
  return data;
}
export async function startSubscription(plan: string, cycle: BillingCycle) {
  const { data } = await api.post('/billing/subscribe', { plan, cycle });
  return data as { subscription_id: string; key_id: string; plan: string; cycle: string; name: string; contact: string };
}
export async function verifySubscription(p: { razorpay_payment_id: string; razorpay_subscription_id: string; razorpay_signature: string }): Promise<BillingStatus> {
  const { data } = await api.post('/billing/verify', p);
  return data;
}
export async function cancelSubscription(): Promise<BillingStatus> {
  const { data } = await api.post('/billing/cancel');
  return data;
}
export async function changePlan(plan: string, cycle: BillingCycle): Promise<BillingStatus> {
  const { data } = await api.post('/billing/change-plan', { plan, cycle });
  return data;
}

// ---------- Students (teacher-facing) ----------
export async function createStudent(payload: {
  name: string; phone: string; parent_phone?: string; batch_id?: string; password: string;
}) {
  const { data } = await api.post('/students', payload);
  return data;
}

export async function listStudents(batchId?: string) {
  const { data } = await api.get('/students', { params: batchId ? { batch_id: batchId } : {} });
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

export async function batchAttendanceAnalytics(batchId: string) {
  const { data } = await api.get(`/attendance/batch/${batchId}/analytics`);
  return data; // { batch_id, batch_name, student_count, batch_average_pct, students: [...] }
}

// ---------- Parents (parent-facing; read-only except paying fees) ----------
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

// Parent paying the child's fee - same shapes as the student's own pay calls above.
export async function getChildFeesPayable(): Promise<{ fees: MyFee[]; online_payment_available: boolean }> {
  const { data } = await api.get('/parents/my-fees');
  return data;
}

export async function createParentPaymentOrder(feeRecordId: string, amount?: number) {
  const { data } = await api.post('/parents/create-order', { fee_record_id: feeRecordId, ...(amount ? { amount } : {}) });
  return data;
}

export async function verifyParentFeePayment(p: { razorpay_order_id: string; razorpay_payment_id: string; razorpay_signature: string }) {
  const { data } = await api.post('/parents/verify', p);
  return data;
}

export async function myChildTests() {
  const { data } = await api.get('/parents/tests');
  return data;
}

// ---------- Tests ----------
export interface QuestionIn {
  text: string;
  option_a: string;
  option_b: string;
  option_c: string;
  option_d: string;
  correct_option: 'a' | 'b' | 'c' | 'd';
}

export interface TestAttemptOut {
  id: string;
  test_id: string;
  test_title: string;
  started_at: string;
  submitted_at: string | null;
  score: number | null;
  max_score: number | null;
  graded_at: string | null; // null = submitted but not yet graded (document_locked only)
  is_flagged: boolean;
  flag_count: number;
}

export async function createMcqTest(payload: {
  title: string; duration_minutes: number; batch_id?: string; questions: QuestionIn[];
}) {
  const { data } = await api.post('/tests/mcq', payload);
  return data; // { test_id, questions_created }
}

export async function createDocumentTest(payload: {
  title: string; document_url: string; duration_minutes: number; batch_id?: string;
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

export async function listUngradedAttempts(testId: string) {
  const { data } = await api.get(`/tests/${testId}/ungraded`);
  return data as TestAttemptOut[];
}

export async function gradeAttempt(attemptId: string, score: number, max_score: number) {
  const { data } = await api.post(`/tests/attempts/${attemptId}/grade`, { score, max_score });
  return data as TestAttemptOut;
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

export async function createTeacher(payload: {
  name: string; phone: string; password: string; is_owner?: boolean; batch_ids?: string[];
}) {
  // batch_ids is ignored by the backend when is_owner is true - owners aren't batch-scoped.
  const { data } = await api.post('/institute/teachers', payload);
  return data;
}

export async function setTeacherBatches(teacherId: string, batchIds: string[]) {
  // Full replacement, not additive - send every batch this teacher should be
  // assigned to, not just new ones.
  const { data } = await api.put(`/institute/teachers/${teacherId}/batches`, { batch_ids: batchIds });
  return data;
}

export async function deleteTeacher(teacherId: string) {
  const { data } = await api.delete(`/institute/teachers/${teacherId}`);
  return data;
}

// ---------- Students (institute-admin-facing - unscoped by batch, unlike a teacher) ----------
export async function listInstituteStudents(batchId?: string) {
  const { data } = await api.get('/institute/students', { params: batchId ? { batch_id: batchId } : {} });
  return data;
}

export async function createInstituteStudent(payload: {
  name: string; phone: string; parent_phone?: string; batch_id?: string; password: string;
}) {
  const { data } = await api.post('/institute/students', payload);
  return data;
}

export async function listInvoices(): Promise<Invoice[]> {
  const { data } = await api.get('/billing/invoices');
  return data;
}
export async function getInvoice(id: string): Promise<Invoice> {
  const { data } = await api.get(`/billing/invoices/${id}`);
  return data;
}
export async function getSeller(): Promise<Seller> {
  const { data } = await api.get('/billing/seller');
  return data;
}
export async function quoteUpgrade(plan: string): Promise<UpgradeQuote> {
  const { data } = await api.post('/billing/upgrade/quote', { plan });
  return data;
}
export async function startUpgrade(plan: string): Promise<UpgradeOrder> {
  const { data } = await api.post('/billing/upgrade', { plan });
  return data;
}
export async function verifyUpgrade(p: { razorpay_order_id: string; razorpay_payment_id: string; razorpay_signature: string }): Promise<BillingStatus> {
  const { data } = await api.post('/billing/upgrade/verify', p);
  return data;
}


// ---------- Added in the QA-fix pass ----------
export interface ClassOut {
  id: string; batch_id: string; batch_name: string; subject: string;
  start_time: string; end_time: string; status: 'scheduled' | 'cancelled' | 'completed';
}
export interface AttemptOut {
  id: string; test_id: string; test_title: string; started_at: string; submitted_at: string | null;
  score: number | null; max_score: number | null; graded_at: string | null;
}

export async function listMyClasses(): Promise<ClassOut[]> {
  const { data } = await api.get('/classes/my');
  return data;
}

export async function listMyAttempts(): Promise<AttemptOut[]> {
  const { data } = await api.get('/tests/my-attempts');
  return data;
}

export async function deleteStudent(studentId: string) {
  const { data } = await api.delete(`/students/${studentId}`);
  return data;
}

export async function setStudentPassword(studentId: string, password: string) {
  const { data } = await api.post(`/students/${studentId}/set-password`, { password });
  return data;
}

export async function listInstituteBatches(): Promise<BatchOut[]> {
  const { data } = await api.get('/institute/batches');
  return data;
}

export async function createInstituteBatch(name: string): Promise<BatchOut> {
  const { data } = await api.post('/institute/batches', { name });
  return data;
}

export async function deleteInstituteStudent(studentId: string) {
  const { data } = await api.delete(`/institute/students/${studentId}`);
  return data;
}


// ---------- Platform admin (the founder) ----------
export async function adminLogin(phone: string, password: string) {
  const { data } = await api.post('/admin/login', { phone, password });
  localStorage.setItem('wandor_token', data.access_token);
  localStorage.setItem('wandor_role', 'platform_admin');
  clearCanPay();
  return data;
}
export interface AdminMoney { base_paise: number; gst_paise: number }
export interface AdminStats {
  paying_accounts: number; total_users: number; users_gained_week: number;
  revenue: { total: AdminMoney; week: AdminMoney; month: AdminMoney };
}
export interface AdminAccount {
  subscription_id: string; kind: 'institute' | 'teacher'; name: string; phone: string;
  plan: string; status: string; is_paying: boolean;
  access_state: 'active' | 'grace' | 'banned'; access_reason: 'payment' | 'admin' | null;
  current_period_end: string | null; ban_at: string | null;
  admin_banned: boolean; admin_ban_reason: string | null;
}
export type AdminStatusFilter = 'all' | 'active' | 'grace' | 'banned' | 'trial';
export async function getAdminStats(): Promise<AdminStats> {
  const { data } = await api.get('/admin/stats');
  return data;
}
export async function listAdminAccounts(status: AdminStatusFilter = 'all'): Promise<AdminAccount[]> {
  const { data } = await api.get('/admin/accounts', { params: { status } });
  return data;
}
export async function extendGrace(subscriptionId: string, until: string, note?: string): Promise<AdminAccount> {
  const { data } = await api.post(`/admin/accounts/${subscriptionId}/extend-grace`, { until, note: note || undefined });
  return data;
}
export async function banAccount(subscriptionId: string, reason: string): Promise<AdminAccount> {
  const { data } = await api.post(`/admin/accounts/${subscriptionId}/ban`, { reason });
  return data;
}
export async function liftBan(subscriptionId: string): Promise<AdminAccount> {
  const { data } = await api.post(`/admin/accounts/${subscriptionId}/lift-ban`);
  return data;
}
