package com.wandor.app.plugins

import android.os.Bundle
import com.getcapacitor.JSObject
import com.getcapacitor.Plugin
import com.getcapacitor.PluginCall
import com.getcapacitor.PluginMethod
import com.getcapacitor.annotation.CapacitorPlugin

/**
 * Drop this file into android/app/src/main/java/com/wandor/app/plugins/ after running
 * `npx cap add android` from webapp/, then register it in MainActivity.java:
 *
 *   registerPlugin(LockTaskPlugin.class)
 *
 * This is the ONLY piece of this app that needs to be native Kotlin - everything else
 * (scheduling UI, tests UI, payments UI) lives in the shared React app and just gets
 * wrapped. That's the whole point of doing it this way: minimal native surface area.
 *
 * Tier 1 (what this implements): plain screen-pinning via Activity.startLockTask().
 * Works with zero extra device setup. Student can still force-exit via the
 * long-press Back+Overview unpin gesture - we catch that attempt via onUserLeaveHint()
 * on the host Activity and emit it as a JS event rather than physically preventing it.
 *
 * Tier 2 (not implemented here, noted for later): device-owner/MDM provisioning makes
 * startLockTask() truly un-exitable. Bigger ask of the institute (they'd need to enroll
 * the device), worth building only once a paying customer needs it.
 */
@CapacitorPlugin(name = "LockTask")
class LockTaskPlugin : Plugin() {

    private var currentAttemptId: String? = null

    @PluginMethod
    fun startLock(call: PluginCall) {
        currentAttemptId = call.getString("attemptId")
        activity.startLockTask()

        val result = JSObject()
        result.put("started", true)
        call.resolve(result)
    }

    @PluginMethod
    fun stopLock(call: PluginCall) {
        activity.stopLockTask()
        currentAttemptId = null

        val result = JSObject()
        result.put("stopped", true)
        call.resolve(result)
    }

    /**
     * Called from WandorMainActivity.onUserLeaveHint() / onPause() overrides - see the
     * snippet below. Capacitor's default MainActivity doesn't expose these lifecycle
     * hooks to plugins automatically, so the host activity needs a two-line override
     * that calls back into this plugin.
     */
    fun notifyLeaveAttempt(eventType: String) {
        val data = JSObject()
        data.put("eventType", eventType)
        notifyListeners("leaveAttempt", data)
    }
}

/*
 * Add to android/app/src/main/java/com/wandor/app/MainActivity.java (created by
 * `npx cap add android`):
 *
 *   public class MainActivity extends BridgeActivity {
 *       @Override
 *       public void onUserLeaveHint() {
 *           super.onUserLeaveHint();
 *           LockTaskPlugin plugin = (LockTaskPlugin) getBridge().getPlugin("LockTask").getInstance();
 *           if (plugin != null) plugin.notifyLeaveAttempt("app_switch");
 *       }
 *   }
 */
