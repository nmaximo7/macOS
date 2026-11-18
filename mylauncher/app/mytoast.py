"""
mytoast.py - a small message that appears for a moment where the launcher was ("✔ ;bsite copied").

Why: macOS notifications depend on permissions, Focus modes and which program posts them, and fail without a word.
The toast is drawn by the launcher itself, so it always works, and it needs no permission. The macOS notification
(mynotify.py) is still sent too, for the times you are looking at another screen.

It is a window with no title bar (`overrideredirect`): fine here because it only DISPLAYS something, it never
needs the keyboard (that is why the launcher window itself cannot be borderless, see mychrome.py).
"""

from __future__ import annotations

import sys
import tkinter as tk

from mytheme import shorten

WIDTH_CHARACTERS = 80


def _rgb(hex_color: str):
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def native_panel(text: str, theme, top: int):
    """Show the toast as a real Cocoa panel (PyObjC). Returns the panel, or None if that is not possible.

    Why not only Tk: the launcher hides itself (`root.withdraw()`) right before the toast, and on macOS a Tk window
    that belongs to a hidden window stays hidden too. A Cocoa panel does not depend on the Tk window at all.
    """
    if sys.platform != "darwin":
        return None
    try:
        import AppKit as ak
        label = ak.NSTextField.labelWithString_(text)
        label.setFont_(ak.NSFont.systemFontOfSize_(theme.row_size + 2))
        label.setTextColor_(ak.NSColor.colorWithSRGBRed_green_blue_alpha_(*_rgb(theme.text), 1))
        label.sizeToFit()
        pad = 18
        width, height = label.frame().size.width + 2 * pad, label.frame().size.height + 2 * pad // 1.5
        screen = ak.NSScreen.mainScreen().frame()
        x = screen.origin.x + (screen.size.width - width) / 2
        y = screen.origin.y + screen.size.height - top - height
        panel = ak.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            ak.NSMakeRect(x, y, width, height), 0, ak.NSBackingStoreBuffered, False)  # 0 = borderless
        panel.setLevel_(ak.NSStatusWindowLevel)
        panel.setOpaque_(False)
        panel.setHasShadow_(True)
        panel.setIgnoresMouseEvents_(True)
        panel.setReleasedWhenClosed_(False)
        panel.setCollectionBehavior_((1 << 0) | (1 << 8))  # on every Space, also over full-screen apps
        panel.setBackgroundColor_(ak.NSColor.colorWithSRGBRed_green_blue_alpha_(*_rgb(theme.input_background), 1))
        label.setFrameOrigin_(ak.NSMakePoint(pad, pad // 1.5))
        panel.contentView().addSubview_(label)
        panel.orderFrontRegardless()
        return panel
    except Exception as error:  # no PyObjC, or a changed API: fall back to Tk
        print(f"[toast] native panel failed ({error}); using the Tk window", file=sys.stderr)
        return None


class Toast:
    def __init__(self, root, theme, seconds: float, top: int, native=native_panel):
        self.root, self.theme, self.seconds, self.top = root, theme, seconds, top
        self.native = native
        self.panel = None  # the Cocoa panel, when it could be made
        self.window = None
        self._timer = None

    def show(self, text: str) -> None:
        self.close()
        text = shorten(text, WIDTH_CHARACTERS)
        t = self.theme
        self.panel = self.native(text, t, self.top)
        if self.panel is not None:
            self._timer = self.root.after(int(self.seconds * 1000), self.close)
            return
        window = tk.Toplevel(self.root)
        window.overrideredirect(True)  # no title bar, no buttons
        window.attributes("-topmost", True)
        window.configure(bg=t.selection)
        tk.Label(window, text=text, bg=t.input_background, fg=t.text, font=(t.font, t.row_size), padx=18, pady=10).pack(padx=2, pady=2)
        window.update_idletasks()
        x = (window.winfo_screenwidth() - window.winfo_reqwidth()) // 2
        window.geometry(f"+{x}+{self.top}")
        self.window = window
        self._timer = self.root.after(int(self.seconds * 1000), self.close)

    def close(self) -> None:
        if self._timer is not None:
            self.root.after_cancel(self._timer)
            self._timer = None
        if self.panel is not None:
            self.panel.orderOut_(None)
            self.panel = None
        if self.window is not None:
            self.window.destroy()
            self.window = None
