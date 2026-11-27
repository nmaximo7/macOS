"""
mypoweroff.py - know that the Mac is shutting down, restarting or logging out.

macOS announces it with the notification NSWorkspaceWillPowerOffNotification. At that moment the launcher must go
away at once: since step 9j it ignores "quit" requests (something kept ending it by itself), and an application that
ignores them makes macOS say "Your Mac hasn't restarted because Python failed to quit".

GUIDED TOUR: 20 lines, and a lesson about unintended consequences. In step 9j the launcher was made to IGNORE quit requests (see protect_from_closing in
mylauncher_app.py), because something kept ending it. But a program that refuses to quit also blocks a restart. So we ask macOS to TELL us when a power-off
starts, and then (and only then) leave at once.
HOW THE MECHANISM WORKS: macOS has a NOTIFICATION CENTER, a message board where the system posts events by name. addObserverForName_object_queue_usingBlock_
means "when a notification with this name is posted, run this function". The lambda note: callback() is that function (it ignores the notification itself).
It returns an OBSERVER object; if we did not keep it in a variable, Python would delete it and the subscription would silently end: that is why
mylauncher_app.py stores it in `power_watch` with a comment. `return None` = "PyObjC is not installed here", and the caller does not care.
"""

from __future__ import annotations


def watch(callback):
    """Call `callback()` when the power-off starts. Returns what must be kept alive, or None if PyObjC is not there."""
    try:
        from AppKit import NSWorkspace

        center = NSWorkspace.sharedWorkspace().notificationCenter()
        return center.addObserverForName_object_queue_usingBlock_("NSWorkspaceWillPowerOffNotification", None, None, lambda note: callback())
    except Exception:  # noqa: BLE001 - no PyObjC, or not macOS: the "quit" marker file still works
        return None
