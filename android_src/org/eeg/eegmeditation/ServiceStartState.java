package org.eeg.eegmeditation;

/**
 * Whether the session's foreground service is stopped, starting or in the foreground, and what a start or a stop must
 * do. A stop that reaches the system before onStartCommand's startForeground crashes the process ("startForegroundService()
 * did not then call startForeground()"), so while starting a stop is only noted and carried out once it went foreground.
 */
final class ServiceStartState {
    static final int STOPPED = 0;
    static final int STARTING = 1;
    static final int FOREGROUND = 2;

    /** What a start found, to put back if the start fails. */
    static final class Before {
        final int state;
        final boolean stopNoted;
        final int pending;

        Before(int state, boolean stopNoted, int pending) {
            this.state = state;
            this.stopNoted = stopNoted;
            this.pending = pending;
        }
    }

    private int state = STOPPED;
    private boolean stopNoted;  // a stop after the latest start, carried out when that start goes foreground
    private int pending;  // starts whose onStartCommand hasn't run yet

    synchronized Before starting() {
        Before before = new Before(state, stopNoted, pending);
        state = STARTING;
        stopNoted = false;
        pending++;
        return before;
    }

    /** The start threw: as it was, so a later stop still finds a service that was already running. */
    synchronized void startFailed(Before before) {
        state = before.state;
        stopNoted = before.stopNoted;
        pending = before.pending;
    }

    /** True when the caller must stop the service now; while it is starting the stop is only noted. */
    synchronized boolean stop() {
        if (state == STARTING) {
            stopNoted = true;
        }
        if (state != FOREGROUND) {
            return false;
        }
        state = STOPPED;
        return true;
    }

    /** After startForeground: true when a stop noted after the latest start must now stop the service. */
    synchronized boolean wentForeground() {
        if (pending > 0) {
            pending--;
        }
        if (pending > 0) {
            return false;  // a later start is still coming: the noted stop is its to carry out
        }
        boolean stopNow = stopNoted;
        stopNoted = false;
        state = stopNow ? STOPPED : FOREGROUND;
        return stopNow;
    }

    synchronized int state() {
        return state;
    }
}
