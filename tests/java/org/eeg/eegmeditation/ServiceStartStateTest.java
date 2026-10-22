package org.eeg.eegmeditation;

/** ServiceStartState's transition table; tests/test_service_start_state.py compiles and runs it. */
public final class ServiceStartStateTest {
    private static int checks;

    private static void check(boolean ok, String what) {
        checks++;
        if (!ok) {
            throw new AssertionError(what);
        }
    }

    public static void main(String[] args) {
        // A session: start, go foreground, stop; a second stop does nothing.
        ServiceStartState s = new ServiceStartState();
        s.starting();
        check(!s.wentForeground(), "with no stop noted, going foreground keeps the service");
        check(s.state() == ServiceStartState.FOREGROUND, "in the foreground");
        check(s.stop(), "a stop in the foreground stops the service");
        check(!s.stop(), "a second stop does nothing");
        check(s.state() == ServiceStartState.STOPPED, "stopped");

        // A start refused or cancelled at once: the stop waits for the foreground, then stops the service.
        s = new ServiceStartState();
        s.starting();
        check(!s.stop(), "a stop while starting is only noted");
        check(s.wentForeground(), "the noted stop is carried out on going foreground");
        check(s.state() == ServiceStartState.STOPPED, "stopped after the noted stop");

        // Start, stop and start again before the first went foreground: the new start keeps the service.
        s = new ServiceStartState();
        s.starting();
        s.stop();
        s.starting();
        check(!s.wentForeground(), "the first start's going foreground leaves the new start's service up");
        check(s.state() == ServiceStartState.STARTING, "still starting: the new start's own call is to come");
        check(!s.wentForeground(), "the new start's going foreground keeps it");
        check(s.state() == ServiceStartState.FOREGROUND, "in the foreground for the new start");

        // A start that throws from stopped: nothing is starting, so a stop has nothing to do.
        s = new ServiceStartState();
        s.startFailed(s.starting());
        check(s.state() == ServiceStartState.STOPPED, "back to stopped");
        check(!s.stop(), "nothing to stop");

        // A start that throws while a service is in the foreground: that service can still be stopped.
        s = new ServiceStartState();
        s.starting();
        s.wentForeground();
        s.startFailed(s.starting());
        check(s.state() == ServiceStartState.FOREGROUND, "the running service is still in the foreground");
        check(s.stop(), "and a stop stops it");

        // A start that throws while an earlier one is starting with a stop noted: the noted stop survives.
        s = new ServiceStartState();
        s.starting();
        s.stop();
        s.startFailed(s.starting());
        check(s.wentForeground(), "the earlier start's noted stop is carried out");

        // Two starts pending, then a stop: it is the latest start's, so its going foreground stops the service.
        s = new ServiceStartState();
        s.starting();
        s.stop();
        s.starting();
        s.stop();
        check(!s.wentForeground(), "the first start's going foreground leaves the stop to the second");
        check(s.wentForeground(), "the second start's going foreground carries out the stop");
        check(s.state() == ServiceStartState.STOPPED, "stopped after both");

        // Two starts pending and no stop: the service stays up after both.
        s = new ServiceStartState();
        s.starting();
        s.starting();
        check(!s.wentForeground() && !s.wentForeground(), "neither start stops it");
        check(s.state() == ServiceStartState.FOREGROUND, "in the foreground");

        // A stop with nothing running leaves nothing behind for the next start.
        s = new ServiceStartState();
        s.stop();
        s.starting();
        check(!s.wentForeground(), "an earlier stop doesn't stop the next session's service");

        System.out.println("OK " + checks);
    }
}
