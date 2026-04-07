"""SAP Logon dialog — dark terminal style, collects client/user/password/language."""
import sys
import tkinter as tk

BG = "#0c0c0c"
FG = "#cccccc"
ENTRY_BG = "#1a1a1a"
REQ = "#ff6666"
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
    """Center on the monitor where the cursor is.
    Windows: uses MonitorFromPoint for precise monitor detection.
    Mac/Linux: falls back to cursor-relative positioning.
    """
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
        hmon = ctypes.windll.user32.MonitorFromPoint(pt, 2)
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        ctypes.windll.user32.GetMonitorInfoW(hmon, ctypes.byref(mi))
        rc = mi.rcWork
        x = rc.left + (rc.right - rc.left - w) // 2
        y = rc.top + (rc.bottom - rc.top - h) // 2
    except Exception:
        x = max(0, px - w // 2)
        y = max(0, py - h // 2)
    root.geometry(f"{w}x{h}+{x}+{y}")


def _make_field(parent, label, row, default="", show=None, required=False):
    lbl = label
    if required:
        f = tk.Frame(parent, bg=BG)
        f.grid(row=row, column=0, sticky="e", padx=(0, 8), pady=4)
        tk.Label(f, text=label, font=FONT, bg=BG, fg=FG).pack(side="left")
        tk.Label(f, text=" *", font=FONT, bg=BG, fg=REQ).pack(side="left")
    else:
        tk.Label(parent, text=label, font=FONT, bg=BG, fg=FG).grid(
            row=row, column=0, sticky="e", padx=(0, 8), pady=4)

    entry = tk.Entry(parent, width=24, font=FONT, bg=ENTRY_BG, fg="#ffffff",
                     insertbackground=FG, relief="flat",
                     **({"show": show} if show else {}))
    entry.grid(row=row, column=1, sticky="w", pady=4)
    if default:
        entry.insert(0, default)
    return entry


def main():
    system_name = sys.argv[1] if len(sys.argv) > 1 else "SAP"
    result = {"ok": False}

    root = tk.Tk()
    root.title(f"SAP Logon — {system_name}")
    root.configure(bg=BG)
    root.resizable(False, False)
    root.attributes("-topmost", True)
    root.protocol("WM_DELETE_WINDOW", root.destroy)

    _center_on_cursor_monitor(root, 380, 210)
    _dark_title_bar(root)
    root.focus_force()
    root.lift()

    form = tk.Frame(root, bg=BG)
    form.pack(padx=24, pady=(16, 8))

    e_client = _make_field(form, "Client:", 0, default="100")
    e_user = _make_field(form, "User:", 1, required=True)
    e_pass = _make_field(form, "Password:", 2, show="*", required=True)
    e_lang = _make_field(form, "Language:", 3, default="EN")

    e_user.focus_set()

    bf = tk.Frame(root, bg=BG)
    bf.pack(padx=24, pady=(4, 12), anchor="e")

    def ok():
        if not e_user.get().strip() or not e_pass.get().strip():
            e_user.configure(highlightbackground=REQ, highlightthickness=1)
            e_pass.configure(highlightbackground=REQ, highlightthickness=1)
            return
        result["ok"] = True
        result["client"] = e_client.get().strip() or "100"
        result["user"] = e_user.get().strip()
        result["pass"] = e_pass.get()
        result["lang"] = e_lang.get().strip() or "EN"
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

    if result["ok"]:
        print(f"{result['client']}|{result['user']}|{result['pass']}|{result['lang']}")
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
