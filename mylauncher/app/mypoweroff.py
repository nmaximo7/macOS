"""
mypoweroff.py - know that the Mac is shutting down, restarting or logging out.

macOS announces it with the notification NSWorkspaceWillPowerOffNotification. At that moment the launcher must go
away at once: since step 9j it ignores "quit" requests (something kept ending it by itself), and an application that
ignores them makes macOS say "Your Mac hasn't restarted because Python failed to quit".
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
