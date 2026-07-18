from __future__ import annotations

import platform
import threading
import tkinter as tk
from tkinter import messagebox

BG = "#0e1116"
SURFACE = "#171b22"
SURFACE_2 = "#1e2430"
BORDER = "#2a3140"
TEXT = "#eef1f6"
MUTED = "#8b93a7"
ACCENT = "#5ee1a8"
ACCENT_DIM = "#1a3d32"
OFF = "#f07178"
OFF_DIM = "#3a2226"
BTN = "#2a3344"
BTN_HOVER = "#354054"
BTN_DISABLED = "#1a1e28"
TEXT_DISABLED = "#5c6478"


def _ensure_windows() -> None:
    if platform.system() != "Windows":
        raise SystemExit("The Untrace GUI is Windows-only.")


def _fetch_status() -> dict:
    from untrace.__main__ import windows_gui_status

    return windows_gui_status()


def _run_action(action: str) -> int:
    from untrace import applog
    from untrace.__main__ import install, uninstall

    applog.write(f"gui: starting {action}")
    try:
        if action == "install":
            install(stealth=True, flags=True, chromedriver=True)
        elif action == "uninstall":
            uninstall()
        else:
            raise ValueError(action)
    except SystemExit as exc:
        code = exc.code
        if code is None:
            code = 0
        elif not isinstance(code, int):
            applog.write(f"gui: {action} exit: {code}")
            code = 1
        applog.write(f"gui: {action} finished code={code}")
        return code
    except Exception as exc:
        applog.write(f"gui: {action} failed: {exc!r}")
        raise
    applog.write(f"gui: {action} finished code=0")
    return 0


class Pill(tk.Frame):
    def __init__(self, master: tk.Misc, text: str, *, on: bool) -> None:
        super().__init__(master, bg=ACCENT_DIM if on else OFF_DIM, padx=12, pady=5)
        color = ACCENT if on else OFF
        tk.Label(
            self,
            text=text,
            bg=ACCENT_DIM if on else OFF_DIM,
            fg=color,
            font=("Segoe UI Semibold", 10),
        ).pack()


class FeatureCard(tk.Frame):
    def __init__(self, master: tk.Misc, label: str, *, on: bool) -> None:
        super().__init__(
            master, bg=SURFACE, highlightthickness=1, highlightbackground=BORDER
        )
        inner = tk.Frame(self, bg=SURFACE, padx=14, pady=14)
        inner.pack(fill=tk.X)

        left = tk.Frame(inner, bg=SURFACE)
        left.pack(side=tk.LEFT, fill=tk.X, expand=True)

        top = tk.Frame(left, bg=SURFACE)
        top.pack(anchor=tk.W)
        dot = tk.Canvas(top, width=10, height=10, bg=SURFACE, highlightthickness=0)
        dot.pack(side=tk.LEFT, padx=(0, 8))
        dot.create_oval(1, 1, 9, 9, fill=ACCENT if on else OFF, outline="")
        tk.Label(
            top,
            text=label,
            bg=SURFACE,
            fg=TEXT,
            font=("Segoe UI Semibold", 11),
        ).pack(side=tk.LEFT)

        state = Pill(inner, "On" if on else "Off", on=on)
        state.pack(side=tk.RIGHT)


class ActionButton(tk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        text: str,
        command,
        *,
        primary: bool = False,
        danger: bool = False,
    ) -> None:
        super().__init__(master, bg=BG)
        self._command = command
        self._enabled = True
        self._primary = primary
        self._danger = danger
        self._btn = tk.Label(
            self,
            text=text,
            font=("Segoe UI Semibold", 11),
            padx=18,
            pady=10,
            cursor="hand2",
        )
        self._btn.pack()
        self._btn.bind("<Button-1>", self._click)
        self._btn.bind("<Enter>", self._enter)
        self._btn.bind("<Leave>", self._leave)
        self._paint()

    def _paint(self) -> None:
        if not self._enabled:
            self._btn.configure(bg=BTN_DISABLED, fg=TEXT_DISABLED, cursor="arrow")
            return
        if self._primary:
            self._btn.configure(bg=ACCENT, fg="#0c1210", cursor="hand2")
        elif self._danger:
            self._btn.configure(bg=OFF_DIM, fg=OFF, cursor="hand2")
        else:
            self._btn.configure(bg=BTN, fg=TEXT, cursor="hand2")

    def _enter(self, _event=None) -> None:
        if not self._enabled:
            return
        if self._primary:
            self._btn.configure(bg="#7aebba")
        elif self._danger:
            self._btn.configure(bg="#4a2a2e")
        else:
            self._btn.configure(bg=BTN_HOVER)

    def _leave(self, _event=None) -> None:
        self._paint()

    def _click(self, _event=None) -> None:
        if self._enabled and self._command:
            self._command()

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        self._paint()


class UntraceGui(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Untrace")
        self.minsize(480, 420)
        self.geometry("520x620")
        self.state("zoomed")
        self.configure(bg=BG)
        self._busy = False
        self._snapshot: dict | None = None

        self._canvas = tk.Canvas(self, bg=BG, highlightthickness=0, borderwidth=0)
        scrollbar = tk.Scrollbar(
            self,
            orient=tk.VERTICAL,
            command=self._canvas.yview,
            bg=SURFACE,
            troughcolor=BG,
            activebackground=BTN_HOVER,
            highlightthickness=0,
            bd=0,
            width=12,
        )
        self._canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._body = tk.Frame(self._canvas, bg=BG, padx=28, pady=24)
        self._body_id = self._canvas.create_window(
            (0, 0), window=self._body, anchor=tk.NW
        )
        self._body.bind("<Configure>", self._on_body_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)
        self.bind("<Enter>", self._grab_wheel)
        self.bind("<Leave>", self._release_wheel)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        tk.Label(
            self._body,
            text="Untrace",
            bg=BG,
            fg=TEXT,
            font=("Segoe UI", 26, "bold"),
        ).pack(anchor=tk.W, pady=(0, 20))

        hero = tk.Frame(
            self._body, bg=SURFACE, highlightthickness=1, highlightbackground=BORDER
        )
        hero.pack(fill=tk.X, pady=(0, 16))
        hero_inner = tk.Frame(hero, bg=SURFACE, padx=18, pady=16)
        hero_inner.pack(fill=tk.X)
        self.hero_title = tk.Label(
            hero_inner,
            text="Checking…",
            bg=SURFACE,
            fg=TEXT,
            font=("Segoe UI Semibold", 16),
        )
        self.hero_title.pack(anchor=tk.W)

        self.cards = tk.Frame(self._body, bg=BG)
        self.cards.pack(fill=tk.X)

        actions = tk.Frame(self._body, bg=BG)
        actions.pack(fill=tk.X, pady=(16, 8))
        self.install_btn = ActionButton(
            actions, "Install", lambda: self._run("install"), primary=True
        )
        self.install_btn.pack(side=tk.LEFT, padx=(0, 10))
        self.uninstall_btn = ActionButton(
            actions, "Uninstall", lambda: self._run("uninstall"), danger=True
        )
        self.uninstall_btn.pack(side=tk.LEFT, padx=(0, 10))
        self.refresh_btn = ActionButton(actions, "Refresh", self.refresh_status)
        self.refresh_btn.pack(side=tk.LEFT)

        self.refresh_status()

    def _on_close(self) -> None:
        self._release_wheel()
        self.destroy()

    def _grab_wheel(self, _event=None) -> None:
        self.bind_all("<MouseWheel>", self._on_mousewheel)

    def _release_wheel(self, _event=None) -> None:
        self.unbind_all("<MouseWheel>")

    def _on_mousewheel(self, event) -> str:
        self._canvas.yview_scroll(int(-event.delta / 120), "units")
        return "break"

    def _on_body_configure(self, _event=None) -> None:
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_configure(self, event) -> None:
        self._canvas.itemconfigure(self._body_id, width=event.width)

    def _clear_cards(self) -> None:
        for child in self.cards.winfo_children():
            child.destroy()

    def _render(self, snapshot: dict) -> None:
        self._snapshot = snapshot
        installed = bool(snapshot.get("installed"))
        chrome_found = bool(snapshot.get("chrome_found"))

        if not chrome_found:
            self.hero_title.configure(text="Chrome not found", fg=OFF)
        elif installed:
            self.hero_title.configure(text="Installed", fg=ACCENT)
        else:
            self.hero_title.configure(text="Not installed", fg=TEXT)

        self._clear_cards()
        for feature in snapshot.get("features") or []:
            card = FeatureCard(
                self.cards,
                feature.get("label") or "",
                on=bool(feature.get("on")),
            )
            card.pack(fill=tk.X, pady=(0, 8))

        self.after_idle(self._on_body_configure)

        if not self._busy:
            self.install_btn.set_enabled(bool(snapshot.get("can_install")))
            self.uninstall_btn.set_enabled(bool(snapshot.get("can_uninstall")))
            self.refresh_btn.set_enabled(True)

    def refresh_status(self) -> None:
        try:
            self._render(_fetch_status())
        except Exception:
            self._clear_cards()
            self.hero_title.configure(text="Status unavailable", fg=OFF)
            if not self._busy:
                self.uninstall_btn.set_enabled(False)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        if busy:
            self.install_btn.set_enabled(False)
            self.uninstall_btn.set_enabled(False)
            self.refresh_btn.set_enabled(False)
            return
        snap = self._snapshot or {}
        self.install_btn.set_enabled(bool(snap.get("can_install", True)))
        self.uninstall_btn.set_enabled(bool(snap.get("can_uninstall")))
        self.refresh_btn.set_enabled(True)

    def _run(self, action: str) -> None:
        if self._busy:
            return
        if action == "uninstall" and not (self._snapshot or {}).get("can_uninstall"):
            return
        if action == "install" and not (self._snapshot or {}).get("can_install"):
            return

        label = "Install" if action == "install" else "Uninstall"
        if not messagebox.askokcancel(label, f"{label} Untrace?"):
            return

        self._set_busy(True)
        self.hero_title.configure(text=f"{label}ing…", fg=MUTED)

        def worker() -> None:
            code = 1
            err = ""
            try:
                code = _run_action(action)
            except Exception as exc:
                err = str(exc)
            self.after(0, lambda: self._done(action, code, err))

        threading.Thread(target=worker, daemon=True).start()

    def _done(self, action: str, code: int, err: str) -> None:
        self._set_busy(False)
        self.refresh_status()
        if err:
            messagebox.showerror("Untrace", err)
            return
        if code == 0:
            messagebox.showinfo(
                "Untrace",
                "Install finished." if action == "install" else "Uninstall finished.",
            )
        else:
            messagebox.showerror(
                "Untrace",
                f"{action.capitalize()} exited with code {code}.",
            )


def main() -> None:
    _ensure_windows()
    from untrace import applog
    from untrace.__main__ import ensure_admin_windows

    applog.enable(command="--gui")
    ensure_admin_windows()
    app = UntraceGui()
    app.mainloop()


if __name__ == "__main__":
    main()
