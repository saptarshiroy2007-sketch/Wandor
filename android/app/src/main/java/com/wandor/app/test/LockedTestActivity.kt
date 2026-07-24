package com.wandor.app.test

import android.app.Activity
import android.app.admin.DevicePolicyManager
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.os.CountDownTimer
import android.widget.Toast
import com.wandor.app.api.ApiClient
import com.wandor.app.api.FlagEventRequest

/**
 * Handles the "PDF/image test that locks the screen" feature.
 *
 * How the lock actually works, since this trips people up:
 * Android's screen pinning (Lock Task Mode) is the real primitive here - it's the same
 * API proctoring apps and exam-hall kiosk apps use. There are two tiers:
 *
 *  1. startLockTask() without device-owner privileges = "Screen Pinning". Works out of
 *     the box, no special install. BUT the student can still long-press Back+Overview
 *     to request an unpin (shows a system prompt) - that's your "attempted to leave" signal,
 *     caught by onUserLeaveHint(). Good enough for v1.
 *
 *  2. If you go the device-owner / MDM route (institute enrolls the app as a device owner
 *     via QR provisioning), startLockTask() becomes UN-exitable without your app calling
 *     stopLockTask(). This is the "actually can't leave" tier - worth it later once you
 *     have institutes serious enough to hand you MDM control, not for an MVP.
 *
 * For now this skeleton implements tier 1: pin on start, flag on any attempted exit or
 * onPause (covers app-switch, notification-shade pull, etc - err on the side of over-flagging,
 * teacher can review).
 */
class LockedTestActivity : Activity() {

    private lateinit var attemptId: String
    private var flagCount = 0
    private var timer: CountDownTimer? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // setContentView(R.layout.activity_locked_test) -- render the PDF/image here,
        // e.g. via PdfRenderer for PDFs or a plain ImageView for images.

        attemptId = intent.getStringExtra("attempt_id") ?: run {
            finish(); return
        }
        val durationMinutes = intent.getIntExtra("duration_minutes", 30)

        startLockTask() // pin the screen - this is the actual "lock" the pitch refers to
        startTimer(durationMinutes * 60_000L)
    }

    /**
     * This fires when the user does ANYTHING that would normally background the activity:
     * hits Home, pulls down notifications, switches apps, initiates the screen-pinning
     * unpin gesture. This is the core anti-cheat hook.
     */
    override fun onUserLeaveHint() {
        super.onUserLeaveHint()
        reportFlagEvent("app_switch")
    }

    override fun onPause() {
        super.onPause()
        // Belt-and-suspenders: onUserLeaveHint doesn't always fire for every exit path
        // (e.g. power button / screen off). Catch those here too.
        if (!isFinishing) {
            reportFlagEvent("screen_off_or_paused")
        }
    }

    private fun reportFlagEvent(eventType: String) {
        flagCount++
        Toast.makeText(this, "Warning: leaving the test screen has been logged ($flagCount)", Toast.LENGTH_SHORT).show()

        // Fire-and-forget to backend - see ApiClient, hits POST /tests/attempts/flag
        ApiClient.testService.flagAttempt(
            FlagEventRequest(attemptId = attemptId, eventType = eventType)
        ) // in real code: launch this in a coroutine, don't block the UI thread
    }

    private fun startTimer(durationMillis: Long) {
        timer = object : CountDownTimer(durationMillis, 1000) {
            override fun onTick(millisUntilFinished: Long) {
                // update a TextView with millisUntilFinished
            }

            override fun onFinish() {
                submitAndExit()
            }
        }.start()
    }

    private fun submitAndExit() {
        // POST /tests/attempts/{id}/submit with whatever answer state you're tracking
        // (for document tests this might just be "marked as viewed/completed" -
        // grading a locked PDF test is presumably done by the teacher separately)
        stopLockTask()
        finish()
    }

    override fun onDestroy() {
        timer?.cancel()
        super.onDestroy()
    }
}

/**
 * Optional tier-2 helper for when you add device-owner/MDM support later.
 * Not wired up in the MVP - included so the upgrade path is obvious.
 */
object DeviceOwnerHelper {
    fun isDeviceOwner(context: Context): Boolean {
        val dpm = context.getSystemService(Context.DEVICE_POLICY_SERVICE) as DevicePolicyManager
        return dpm.isDeviceOwnerApp(context.packageName)
    }
}
