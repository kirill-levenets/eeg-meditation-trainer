package org.eeg.eegmeditation;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.os.Build;
import android.os.IBinder;

/**
 * The running session's foreground service, declared without android:process so it runs in the app's own process:
 * a foreground service raises the process that hosts it, and this is the process that runs the session. It doesn't stop
 * on its own: it can't outlive the process, and the session's ending stops it, after the save.
 */
public class SessionForegroundService extends Service {
    private static final String CHANNEL_ID = "session";
    private static final int NOTIFICATION_ID = 1;
    private static final String EXTRA_TITLE = "title";
    private static final String EXTRA_TEXT = "text";

    // A stop that reaches the system before onStartCommand's startForeground crashes this process ("startForegroundService()
    // did not then call startForeground()"), so until then a stop is only noted and onStartCommand carries it out.
    private static final Object LOCK = new Object();
    private static boolean foreground;
    private static boolean stopNoted;

    public static void start(Context context, String title, String text) {
        synchronized (LOCK) {
            foreground = false;
            stopNoted = false;
        }
        Intent intent = new Intent(context, SessionForegroundService.class);
        intent.putExtra(EXTRA_TITLE, title);
        intent.putExtra(EXTRA_TEXT, text);
        if (Build.VERSION.SDK_INT >= 26) {
            context.startForegroundService(intent);
        } else {
            context.startService(intent);
        }
    }

    public static void stop(Context context) {
        synchronized (LOCK) {
            if (!foreground) {
                stopNoted = true;
                return;
            }
            foreground = false;
        }
        context.stopService(new Intent(context, SessionForegroundService.class));
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        String title = intent != null ? intent.getStringExtra(EXTRA_TITLE) : null;
        String text = intent != null ? intent.getStringExtra(EXTRA_TEXT) : null;
        startForeground(NOTIFICATION_ID, buildNotification(title, text));
        boolean stopNow;
        synchronized (LOCK) {
            foreground = !stopNoted;
            stopNow = stopNoted;
        }
        if (stopNow) {
            stopSelf();
        }
        return START_NOT_STICKY;  // a session that died stays ended: a revived service would outlive it alone
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    private Notification buildNotification(String title, String text) {
        Intent open = getPackageManager().getLaunchIntentForPackage(getPackageName());
        int piFlags = Build.VERSION.SDK_INT >= 23 ? PendingIntent.FLAG_IMMUTABLE : 0;
        PendingIntent tap = PendingIntent.getActivity(this, 0, open, piFlags);
        Notification.Builder builder;
        if (Build.VERSION.SDK_INT >= 26) {
            NotificationChannel channel = new NotificationChannel(
                    CHANNEL_ID, "Meditation session", NotificationManager.IMPORTANCE_LOW);
            channel.setShowBadge(false);
            getSystemService(NotificationManager.class).createNotificationChannel(channel);
            builder = new Notification.Builder(this, CHANNEL_ID);
        } else {
            builder = new Notification.Builder(this).setPriority(Notification.PRIORITY_LOW);
        }
        return builder
                .setContentTitle(title != null ? title : "")
                .setContentText(text != null ? text : "")
                .setSmallIcon(getApplicationInfo().icon)
                .setContentIntent(tap)
                .setOngoing(true)
                .build();
    }
}
