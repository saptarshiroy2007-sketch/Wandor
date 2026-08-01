import { registerPlugin } from '@capacitor/core';

/**
 * Bridge to the native LockTaskPlugin.kt (see /android-plugin-src).
 * On web (browser tab, not wrapped by Capacitor) these calls just no-op -
 * the locked-document test feature is mobile-only by nature, same as the
 * original pitch intended. Web users taking a test simply won't get the
 * lock/flag behavior, which is fine since fee-paying institutes will push
 * students toward the app for tests anyway.
 */
export interface LockTaskPlugin {
  /** Pins the screen (Android Lock Task Mode) and starts listening for exit attempts. */
  startLock(options: { attemptId: string }): Promise<{ started: boolean }>;

  /** Unpins the screen - call this on submit/timeout. */
  stopLock(): Promise<{ stopped: boolean }>;

  /**
   * Subscribe to leave-attempt events. Fires once per detected app-switch/
   * home-press/notification-pull while locked. Wire this straight to the
   * flagAttempt() API call in api/client.ts.
   */
  addListener(
    eventName: 'leaveAttempt',
    listenerFunc: (data: { eventType: string }) => void
  ): Promise<{ remove: () => void }>;
}

export const LockTask = registerPlugin<LockTaskPlugin>('LockTask', {
  web: () => ({
    // Web fallback: no real locking, but keeps the same interface so pages
    // don't need to branch on platform.
    startLock: async () => ({ started: false }),
    stopLock: async () => ({ stopped: true }),
    addListener: async () => ({ remove: () => {} }),
  }),
});
