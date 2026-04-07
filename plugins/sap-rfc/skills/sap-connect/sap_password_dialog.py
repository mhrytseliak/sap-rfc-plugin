"""SAP password dialog — tkinter GUI for secure password entry."""
import sys
import tkinter as tk


def main():
    username = sys.argv[1] if len(sys.argv) > 1 else "SAP User"

    root = tk.Tk()
    root.title("SAP Connection")
    root.resizable(False, False)
    root.attributes("-topmost", True)

    # Center on screen
    w, h = 360, 140
    x = (root.winfo_screenwidth() - w) // 2
    y = (root.winfo_screenheight() - h) // 2
    root.geometry(f"{w}x{h}+{x}+{y}")

    # Remove minimize/maximize buttons (Windows)
    root.protocol("WM_DELETE_WINDOW", lambda: _cancel(root))

    result = {"password": None}

    # Label
    label = tk.Label(root, text=f"Enter password for {username}:", font=("Segoe UI", 10))
    label.pack(padx=20, pady=(16, 4), anchor="w")

    # Password entry
    entry = tk.Entry(root, show="\u2022", width=38, font=("Segoe UI", 10))
    entry.pack(padx=20, pady=(0, 12))
    entry.focus_set()

    # Buttons frame
    btn_frame = tk.Frame(root)
    btn_frame.pack(padx=20, pady=(0, 12), anchor="e")

    ok_btn = tk.Button(
        btn_frame, text="OK", width=10, font=("Segoe UI", 9),
        command=lambda: _ok(root, entry, result),
    )
    ok_btn.pack(side="left", padx=(0, 8))

    cancel_btn = tk.Button(
        btn_frame, text="Cancel", width=10, font=("Segoe UI", 9),
        command=lambda: _cancel(root),
    )
    cancel_btn.pack(side="left")

    # Key bindings
    root.bind("<Return>", lambda e: _ok(root, entry, result))
    root.bind("<Escape>", lambda e: _cancel(root))

    root.mainloop()

    if result["password"] is not None:
        print(result["password"])
        sys.exit(0)
    else:
        sys.exit(1)


def _ok(root, entry, result):
    result["password"] = entry.get()
    root.destroy()


def _cancel(root):
    root.destroy()


if __name__ == "__main__":
    main()
