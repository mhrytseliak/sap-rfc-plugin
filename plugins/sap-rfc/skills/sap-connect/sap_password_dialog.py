"""SAP password dialog — near terminal line, plain dark style."""
import sys
import tkinter as tk

BG = "#0c0c0c"
FG = "#cccccc"
FONT = ("Menlo" if sys.platform == "darwin" else "Consolas", 10)


def _dark_title_bar(root):
    try:
        import ctypes
        root.update()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 20, ctypes.byref(ctypes.c_int(1)), 4
        )
    except Exception:
        pass


def _center_on_cursor_monitor(root, w, h):
    """Center on the monitor where the cursor is."""
    px, py = root.winfo_pointerxy()
    try:
        import ctypes
        import ctypes.wintypes as wt

        class MONITORINFO(ctypes.Structure):
            _fields_ = [("cbSize", wt.DWORD),
                        ("rcMonitor", wt.RECT),
                        ("rcWork", wt.RECT),
                        ("dwFlags", wt.DWORD)]

        pt = wt.POINT(px, py)
        hmon = ctypes.windll.user32.MonitorFromPoint(pt, 2)  # NEAREST
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        ctypes.windll.user32.GetMonitorInfoW(hmon, ctypes.byref(mi))
        rc = mi.rcWork
        x = rc.left + (rc.right - rc.left - w) // 2
        y = rc.top + (rc.bottom - rc.top - h) // 2
    except Exception:
        # Fallback: center near cursor
        x = max(0, px - w // 2)
        y = max(0, py - h // 2)
    root.geometry(f"{w}x{h}+{x}+{y}")


def main():
    user = sys.argv[1] if len(sys.argv) > 1 else "SAP User"
    result = {"pw": None}

    root = tk.Tk()
    root.title("SAP Connection")
    root.configure(bg=BG)
    root.resizable(False, False)
    root.attributes("-topmost", True)
    root.protocol("WM_DELETE_WINDOW", root.destroy)

    _center_on_cursor_monitor(root, 360, 120)
    _dark_title_bar(root)

    # Force focus
    root.focus_force()
    root.lift()

    tk.Label(root, text=f"Password for {user}:", font=FONT,
             bg=BG, fg=FG).pack(padx=16, pady=(14, 4), anchor="w")

    entry = tk.Entry(root, show="*", width=40, font=FONT,
                     bg="#1a1a1a", fg="#ffffff", insertbackground=FG,
                     relief="flat")
    entry.pack(padx=16, pady=(0, 10))
    entry.focus_set()

    bf = tk.Frame(root, bg=BG)
    bf.pack(padx=16, anchor="e")

    def ok():
        result["pw"] = entry.get()
        root.destroy()

    tk.Button(bf, text="OK", width=8, font=FONT, bg="#333333", fg=FG,
              activebackground="#444444", relief="flat",
              command=ok).pack(side="left", padx=(0, 6))

    tk.Button(bf, text="Cancel", width=8, font=FONT, bg="#222222", fg="#888888",
              activebackground="#333333", relief="flat",
              command=root.destroy).pack(side="left")

    root.bind("<Return>", lambda e: ok())
    root.bind("<Escape>", lambda e: root.destroy())
    root.mainloop()

    if result["pw"] is not None:
        print(result["pw"])
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
