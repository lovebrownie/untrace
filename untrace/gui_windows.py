from __future__ import annotations

import math
import platform
import threading
import tkinter as tk

BG = "#010502"
SURFACE = "#051208"
SURFACE_HOVER = "#0a1f10"
BORDER = "#1a3d24"
BORDER_GLOW = "#33ff66"
TEXT = "#b8ffc8"
MUTED = "#3d7a4e"
GREEN = "#33ff66"
GREEN_BRIGHT = "#b8ffc8"
GREEN_DIM = "#0a2814"
GREEN_DARK = "#03140a"
AMBER = "#c8ff33"
HOT = "#ff5533"
HOT_DIM = "#2a1008"
BTN = "#0a1a10"
BTN_HOVER = "#12301c"
BTN_DISABLED = "#06100a"
TEXT_DISABLED = "#2a4a32"
FONT = "Consolas"


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


def _bind_tree(widget: tk.Misc, sequence: str, handler) -> None:
    widget.bind(sequence, handler, add="+")
    for child in widget.winfo_children():
        _bind_tree(child, sequence, handler)


class GreenRule(tk.Canvas):
    def __init__(self, master: tk.Misc, *, height: int = 3) -> None:
        super().__init__(
            master, height=height, bg=BG, highlightthickness=0, borderwidth=0
        )
        self._height = height
        self.bind("<Configure>", self._redraw)
        self._redraw()

    def _redraw(self, _event=None) -> None:
        self.delete("all")
        w = max(self.winfo_width(), 2)
        self.create_rectangle(0, 0, w, self._height, fill=GREEN_DARK, outline="")


class TypewriterLabel(tk.Label):
    def __init__(self, master: tk.Misc, full: str, **kwargs) -> None:
        super().__init__(master, text="", **kwargs)
        self._full = full
        self._i = 0
        self._job: str | None = None
        self._tick()

    def _tick(self) -> None:
        if self._i <= len(self._full):
            self.configure(text=self._full[: self._i])
            self._i += 1
            self._job = self.after(45, self._tick)

    def stop(self) -> None:
        if self._job is not None:
            self.after_cancel(self._job)
            self._job = None


class BlinkCursor(tk.Label):
    def __init__(self, master: tk.Misc, **kwargs) -> None:
        super().__init__(master, **kwargs)
        self._on = True
        self._job: str | None = None
        self._tick()

    def _tick(self) -> None:
        self._on = not self._on
        self.configure(text="▌" if self._on else " ")
        self._job = self.after(480, self._tick)

    def stop(self) -> None:
        if self._job is not None:
            self.after_cancel(self._job)
            self._job = None


class PulseDot(tk.Canvas):
    def __init__(self, master: tk.Misc, *, on: bool, bg: str) -> None:
        super().__init__(master, width=18, height=18, bg=bg, highlightthickness=0)
        self._on = on
        self._phase = 0
        self._job: str | None = None
        self._paint()
        if on:
            self._tick()

    def _paint(self) -> None:
        self.delete("all")
        if self._on:
            glow = 4 + int(3 * (1 + math.sin(self._phase / 3.5)))
            self.create_oval(
                9 - glow, 9 - glow, 9 + glow, 9 + glow, fill=GREEN_DIM, outline=""
            )
            self.create_oval(4, 4, 14, 14, fill=GREEN, outline="")
            self.create_oval(7, 7, 11, 11, fill=GREEN_BRIGHT, outline="")
        else:
            self.create_oval(4, 4, 14, 14, fill=HOT_DIM, outline=HOT, width=1)
            self.create_oval(7, 7, 11, 11, fill=HOT, outline="")

    def _tick(self) -> None:
        self._phase += 1
        self._paint()
        self._job = self.after(55, self._tick)

    def stop(self) -> None:
        if self._job is not None:
            self.after_cancel(self._job)
            self._job = None


class ActivitySpinner(tk.Label):
    FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")

    def __init__(self, master: tk.Misc, **kwargs) -> None:
        super().__init__(master, text=self.FRAMES[0], **kwargs)
        self._i = 0
        self._job: str | None = None
        self._running = True
        self._tick()

    def _tick(self) -> None:
        if not self._running:
            return
        self._i = (self._i + 1) % len(self.FRAMES)
        self.configure(text=self.FRAMES[self._i])
        self._job = self.after(80, self._tick)

    def stop(self) -> None:
        self._running = False
        if self._job is not None:
            self.after_cancel(self._job)
            self._job = None


class Pill(tk.Frame):
    def __init__(self, master: tk.Misc, text: str, *, on: bool) -> None:
        bg = GREEN_DIM if on else HOT_DIM
        fg = GREEN if on else HOT
        super().__init__(master, bg=bg, padx=12, pady=4)
        self.configure(highlightthickness=1, highlightbackground=fg)
        tk.Label(self, text=text.upper(), bg=bg, fg=fg, font=(FONT, 9, "bold")).pack()


class FeatureCard(tk.Frame):
    def __init__(self, master: tk.Misc, label: str, index: int, *, on: bool) -> None:
        super().__init__(
            master, bg=SURFACE, highlightthickness=1, highlightbackground=BORDER
        )
        self._on = on
        self._dot: PulseDot | None = None
        self._surfaces: list[tk.Misc] = []

        self._accent = tk.Frame(self, bg=GREEN if on else BORDER, width=4)
        self._accent.pack(side=tk.LEFT, fill=tk.Y)

        self._inner = tk.Frame(self, bg=SURFACE, padx=16, pady=14)
        self._inner.pack(fill=tk.X, expand=True)
        self._surfaces.append(self._inner)

        top = tk.Frame(self._inner, bg=SURFACE)
        top.pack(fill=tk.X)
        self._surfaces.append(top)

        left = tk.Frame(top, bg=SURFACE)
        left.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._surfaces.append(left)

        row = tk.Frame(left, bg=SURFACE)
        row.pack(anchor=tk.W)
        self._surfaces.append(row)

        self._dot = PulseDot(row, on=on, bg=SURFACE)
        self._dot.pack(side=tk.LEFT, padx=(0, 10))
        self._idx = tk.Label(
            row, text=f"{index:02d}", bg=SURFACE, fg=MUTED, font=(FONT, 9)
        )
        self._idx.pack(side=tk.LEFT, padx=(0, 8))
        self._surfaces.append(self._idx)
        self._label = tk.Label(
            row,
            text=f"> {label}",
            bg=SURFACE,
            fg=TEXT,
            font=(FONT, 12, "bold"),
        )
        self._label.pack(side=tk.LEFT)
        self._surfaces.append(self._label)

        Pill(top, "Online" if on else "Offline", on=on).pack(side=tk.RIGHT)

        _bind_tree(self, "<Enter>", self._enter)
        _bind_tree(self, "<Leave>", self._leave)

    def _enter(self, _event=None) -> None:
        self.configure(highlightbackground=BORDER_GLOW, bg=SURFACE_HOVER)
        self._accent.configure(bg=GREEN_BRIGHT if self._on else AMBER)
        for widget in self._surfaces:
            try:
                widget.configure(bg=SURFACE_HOVER)
            except tk.TclError:
                pass
        if self._dot is not None:
            self._dot.configure(bg=SURFACE_HOVER)
        self._label.configure(fg=GREEN_BRIGHT)

    def _leave(self, _event=None) -> None:
        self.configure(highlightbackground=BORDER, bg=SURFACE)
        self._accent.configure(bg=GREEN if self._on else BORDER)
        for widget in self._surfaces:
            try:
                widget.configure(bg=SURFACE)
            except tk.TclError:
                pass
        if self._dot is not None:
            self._dot.configure(bg=SURFACE)
        self._label.configure(fg=TEXT)

    def destroy(self) -> None:
        if self._dot is not None:
            self._dot.stop()
        super().destroy()


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
        self._pressed = False
        border = GREEN if primary else (HOT if danger else BORDER)
        self.configure(highlightthickness=1, highlightbackground=border)
        self._btn = tk.Label(
            self,
            text=f"[ {text.upper()} ]",
            font=(FONT, 11, "bold"),
            padx=18,
            pady=12,
            cursor="hand2",
        )
        self._btn.pack()
        self._btn.bind("<ButtonPress-1>", self._press)
        self._btn.bind("<ButtonRelease-1>", self._release)
        self._btn.bind("<Enter>", self._enter)
        self._btn.bind("<Leave>", self._leave)
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self._paint()

    def _paint(self) -> None:
        if not self._enabled:
            self.configure(highlightbackground=BTN_DISABLED)
            self._btn.configure(bg=BTN_DISABLED, fg=TEXT_DISABLED, cursor="arrow")
            return
        if self._pressed:
            if self._primary:
                self.configure(highlightbackground=GREEN_BRIGHT)
                self._btn.configure(bg=GREEN, fg="#021006", cursor="hand2")
            elif self._danger:
                self.configure(highlightbackground=TEXT)
                self._btn.configure(bg=HOT, fg="#1a0508", cursor="hand2")
            else:
                self.configure(highlightbackground=GREEN)
                self._btn.configure(bg=BTN_HOVER, fg=GREEN_BRIGHT, cursor="hand2")
            return
        if self._primary:
            self.configure(highlightbackground=GREEN)
            self._btn.configure(bg=GREEN_DIM, fg=GREEN, cursor="hand2")
        elif self._danger:
            self.configure(highlightbackground=HOT)
            self._btn.configure(bg=HOT_DIM, fg=HOT, cursor="hand2")
        else:
            self.configure(highlightbackground=BORDER)
            self._btn.configure(bg=BTN, fg=TEXT, cursor="hand2")

    def _enter(self, _event=None) -> None:
        if not self._enabled:
            return
        if self._primary:
            self.configure(highlightbackground=GREEN_BRIGHT)
            self._btn.configure(bg=GREEN, fg="#021006")
        elif self._danger:
            self.configure(highlightbackground=TEXT)
            self._btn.configure(bg=HOT, fg="#1a0508")
        else:
            self.configure(highlightbackground=GREEN)
            self._btn.configure(bg=BTN_HOVER, fg=GREEN_BRIGHT)

    def _leave(self, _event=None) -> None:
        self._pressed = False
        self._paint()

    def _press(self, _event=None) -> None:
        if not self._enabled:
            return
        self._pressed = True
        self._paint()

    def _release(self, _event=None) -> None:
        if not self._enabled:
            return
        was = self._pressed
        self._pressed = False
        self._paint()
        if was and self._command:
            self._command()

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        self._pressed = False
        self._paint()


class TerminalOverlay(tk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        title: str,
        message: str,
        on_result,
        *,
        confirm: bool = False,
        danger: bool = False,
    ) -> None:
        super().__init__(master, bg="#010502")
        self._on_result = on_result
        self.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.lift()

        dim = tk.Frame(self, bg="#010502")
        dim.place(relx=0, rely=0, relwidth=1, relheight=1)
        dim.bind("<Button-1>", lambda _e: None)

        card = tk.Frame(self, bg=GREEN_DARK, padx=2, pady=2)
        card.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
        bezel = tk.Frame(card, bg=BORDER, padx=1, pady=1)
        bezel.pack()
        body = tk.Frame(bezel, bg=SURFACE, padx=28, pady=22)
        body.pack()

        tk.Label(
            body, text=f"$ {title.lower()}", bg=SURFACE, fg=MUTED, font=(FONT, 9)
        ).pack(anchor=tk.W)
        tk.Label(
            body,
            text=message,
            bg=SURFACE,
            fg=HOT if danger and not confirm else TEXT,
            font=(FONT, 12, "bold"),
            wraplength=380,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(10, 18))

        actions = tk.Frame(body, bg=SURFACE)
        actions.pack(anchor=tk.E)
        if confirm:
            ActionButton(actions, "Cancel", lambda: self._finish(False)).pack(
                side=tk.LEFT, padx=(0, 10)
            )
            ActionButton(
                actions,
                "Confirm",
                lambda: self._finish(True),
                primary=not danger,
                danger=danger,
            ).pack(side=tk.LEFT)
        else:
            ActionButton(
                actions,
                "Ok",
                lambda: self._finish(True),
                primary=not danger,
                danger=danger,
            ).pack(side=tk.LEFT)

        self.bind("<Escape>", self._on_escape)
        self.focus_set()

    def _on_escape(self, _event=None) -> str:
        self._finish(False)
        return "break"

    def _finish(self, result: bool) -> None:
        callback = self._on_result
        self.destroy()
        if callback is not None:
            callback(result)


def ask_confirm(
    master: tk.Misc,
    title: str,
    message: str,
    on_result,
    *,
    danger: bool = False,
) -> None:
    master.after(
        1,
        lambda: TerminalOverlay(
            master, title, message, on_result, confirm=True, danger=danger
        ),
    )


def show_notice(
    master: tk.Misc,
    title: str,
    message: str,
    *,
    danger: bool = False,
) -> None:
    master.after(
        1,
        lambda: TerminalOverlay(
            master, title, message, lambda _ok: None, confirm=False, danger=danger
        ),
    )


class TerminalScrollbar(tk.Canvas):
    def __init__(self, master: tk.Misc, target: tk.Canvas) -> None:
        super().__init__(
            master, width=16, bg=BG, highlightthickness=0, borderwidth=0, cursor="hand2"
        )
        self._target = target
        self._dragging = False
        self._drag_offset = 0.0
        self._hover = False
        self._first = 0.0
        self._last = 1.0
        self._thumb = (0, 0)
        self._phase = 0
        self._job: str | None = None
        self.bind("<Configure>", lambda _e: self._redraw())
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<MouseWheel>", self._on_wheel)
        self._tick()

    def set(self, first: float | str, last: float | str) -> None:
        self._first = float(first)
        self._last = float(last)
        self._redraw()

    def _redraw(self) -> None:
        self.delete("all")
        h = max(self.winfo_height(), 2)
        w = max(self.winfo_width(), 2)
        span = max(0.05, self._last - self._first)
        self.create_rectangle(0, 0, w, h, fill=BG, outline="")
        self.create_rectangle(5, 18, w - 5, h - 18, fill=GREEN_DARK, outline="")
        self.create_text(
            w // 2, 8, text="▲", fill=GREEN if self._hover else MUTED, font=(FONT, 7)
        )
        self.create_text(
            w // 2,
            h - 8,
            text="▼",
            fill=GREEN if self._hover else MUTED,
            font=(FONT, 7),
        )
        thumb_h = max(32, int(span * (h - 36)))
        thumb_y = 18 + int(self._first * (h - 36 - thumb_h))
        color = GREEN_BRIGHT if self._hover or self._dragging else GREEN
        pad = 3 if self._hover or self._dragging else 4
        self._thumb = (thumb_y, thumb_y + thumb_h)
        self.create_rectangle(
            pad, thumb_y, w - pad, thumb_y + thumb_h, fill=color, outline=""
        )
        mid = thumb_y + thumb_h // 2
        for dy in (-5, 0, 5):
            self.create_line(pad + 2, mid + dy, w - pad - 2, mid + dy, fill=GREEN_DARK)
        if self._hover:
            glow = 1 + (self._phase % 3)
            self.create_rectangle(
                pad - glow,
                thumb_y - glow,
                w - pad + glow,
                thumb_y + thumb_h + glow,
                outline=GREEN_DIM,
            )

    def _tick(self) -> None:
        self._phase += 1
        if self._hover:
            self._redraw()
        self._job = self.after(120, self._tick)

    def stop(self) -> None:
        if self._job is not None:
            self.after_cancel(self._job)
            self._job = None

    def _fraction_at(self, y: int) -> float:
        h = max(self.winfo_height(), 2)
        span = max(0.05, self._last - self._first)
        thumb_h = max(32, int(span * (h - 36)))
        usable = max(1, h - 36 - thumb_h)
        return max(0.0, min(1.0, (y - 18) / usable))

    def _on_press(self, event) -> None:
        if self._thumb[0] <= event.y <= self._thumb[1]:
            self._dragging = True
            self._drag_offset = event.y - self._thumb[0]
        else:
            self._target.yview_moveto(self._fraction_at(event.y))
        self._redraw()

    def _on_drag(self, event) -> None:
        if not self._dragging:
            return
        h = max(self.winfo_height(), 2)
        span = max(0.05, self._last - self._first)
        thumb_h = max(32, int(span * (h - 36)))
        usable = max(1, h - 36 - thumb_h)
        y = event.y - self._drag_offset - 18
        self._target.yview_moveto(max(0.0, min(1.0, y / usable)))

    def _on_release(self, _event=None) -> None:
        self._dragging = False
        self._redraw()

    def _on_enter(self, _event=None) -> None:
        self._hover = True
        self._redraw()

    def _on_leave(self, _event=None) -> None:
        if not self._dragging:
            self._hover = False
            self._redraw()

    def _on_wheel(self, event) -> str:
        self._target.yview_scroll(int(-event.delta / 120), "units")
        return "break"


class UntraceGui(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Untrace")
        self.minsize(540, 480)
        self.geometry("580x720")
        self.state("zoomed")
        self.configure(bg=BG)
        self._busy = False
        self._snapshot: dict | None = None
        self._effects: list = []
        self._hero_edge: tk.Frame | None = None

        outer = tk.Frame(self, bg=GREEN_DARK, padx=2, pady=2)
        outer.pack(fill=tk.BOTH, expand=True)
        bezel = tk.Frame(outer, bg=BORDER, padx=1, pady=1)
        bezel.pack(fill=tk.BOTH, expand=True)
        shell = tk.Frame(bezel, bg=BG)
        shell.pack(fill=tk.BOTH, expand=True)

        self._canvas = tk.Canvas(shell, bg=BG, highlightthickness=0, borderwidth=0)
        self._scrollbar = TerminalScrollbar(shell, self._canvas)
        self._effects.append(self._scrollbar)
        self._canvas.configure(yscrollcommand=self._scrollbar.set)
        self._scrollbar.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 8), pady=10)
        self._canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._body = tk.Frame(self._canvas, bg=BG, padx=40, pady=28)
        self._body_id = self._canvas.create_window(
            (0, 0), window=self._body, anchor=tk.NW
        )
        self._body.bind("<Configure>", self._on_body_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)
        self.bind("<Enter>", self._grab_wheel)
        self.bind("<Leave>", self._release_wheel)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        rule = GreenRule(self._body)
        rule.pack(fill=tk.X, pady=(0, 16))

        brand = tk.Frame(self._body, bg=BG)
        brand.pack(anchor=tk.W)
        tk.Label(brand, text="root@untrace", bg=BG, fg=MUTED, font=(FONT, 10)).pack(
            side=tk.LEFT
        )
        tk.Label(brand, text=":~#", bg=BG, fg=GREEN, font=(FONT, 10, "bold")).pack(
            side=tk.LEFT, padx=(6, 0)
        )
        self._spinner = ActivitySpinner(brand, bg=BG, fg=GREEN, font=(FONT, 10))
        self._spinner.pack(side=tk.LEFT, padx=(10, 0))
        self._effects.append(self._spinner)

        title = tk.Frame(self._body, bg=BG)
        title.pack(anchor=tk.W, pady=(8, 4))
        typed = TypewriterLabel(
            title,
            "untrace",
            bg=BG,
            fg=GREEN,
            font=(FONT, 34, "bold"),
        )
        typed.pack(side=tk.LEFT)
        self._effects.append(typed)
        cursor = BlinkCursor(title, bg=BG, fg=GREEN_BRIGHT, font=(FONT, 22))
        cursor.pack(side=tk.LEFT, padx=(2, 0))
        self._effects.append(cursor)

        rule2 = GreenRule(self._body, height=2)
        rule2.pack(fill=tk.X, pady=(14, 16))

        hero = tk.Frame(
            self._body, bg=SURFACE, highlightthickness=1, highlightbackground=BORDER
        )
        hero.pack(fill=tk.X, pady=(0, 8))
        self._hero_edge = tk.Frame(hero, bg=GREEN, width=4)
        self._hero_edge.pack(side=tk.LEFT, fill=tk.Y)
        hero_inner = tk.Frame(hero, bg=SURFACE, padx=20, pady=16)
        hero_inner.pack(fill=tk.X)
        head = tk.Frame(hero_inner, bg=SURFACE)
        head.pack(fill=tk.X)
        tk.Label(
            head, text="$ status --watch", bg=SURFACE, fg=MUTED, font=(FONT, 8)
        ).pack(side=tk.LEFT)
        self.hero_title = tk.Label(
            hero_inner,
            text="scanning…",
            bg=SURFACE,
            fg=TEXT,
            font=(FONT, 22, "bold"),
        )
        self.hero_title.pack(anchor=tk.W, pady=(8, 0))
        self._hero_sub = tk.Label(
            hero_inner,
            text="",
            bg=SURFACE,
            fg=MUTED,
            font=(FONT, 9),
        )
        self._hero_sub.pack(anchor=tk.W, pady=(4, 0))

        self._busy_bar = tk.Canvas(
            self._body, height=4, bg=BG, highlightthickness=0, borderwidth=0
        )
        self._busy_bar.pack(fill=tk.X, pady=(0, 16))
        self._busy_phase = 0
        self._busy_job: str | None = None

        section = tk.Frame(self._body, bg=BG)
        section.pack(fill=tk.X, pady=(0, 8))
        tk.Label(section, text="┌─ modules", bg=BG, fg=MUTED, font=(FONT, 9)).pack(
            side=tk.LEFT
        )
        tk.Label(section, text="─┐", bg=BG, fg=MUTED, font=(FONT, 9)).pack(
            side=tk.RIGHT
        )

        self.cards = tk.Frame(self._body, bg=BG)
        self.cards.pack(fill=tk.X)

        tk.Label(
            self._body,
            text="└──────────────────────────────┘",
            bg=BG,
            fg=MUTED,
            font=(FONT, 9),
        ).pack(anchor=tk.W, pady=(4, 0))

        actions = tk.Frame(self._body, bg=BG)
        actions.pack(fill=tk.X, pady=(20, 8))
        self.install_btn = ActionButton(
            actions, "Install", lambda: self._run("install"), primary=True
        )
        self.install_btn.pack(side=tk.LEFT, padx=(0, 12))
        self.uninstall_btn = ActionButton(
            actions, "Uninstall", lambda: self._run("uninstall"), danger=True
        )
        self.uninstall_btn.pack(side=tk.LEFT, padx=(0, 12))
        self.refresh_btn = ActionButton(actions, "Refresh", self.refresh_status)
        self.refresh_btn.pack(side=tk.LEFT)

        foot = tk.Frame(self._body, bg=BG)
        foot.pack(fill=tk.X, pady=(24, 0))
        foot_line = GreenRule(foot, height=1)
        foot_line.pack(fill=tk.X, pady=(0, 10))
        self._footer = tk.Label(
            foot,
            text="log → Documents\\Untrace\\untrace.log",
            bg=BG,
            fg=MUTED,
            font=(FONT, 8),
        )
        self._footer.pack(anchor=tk.W)

        self.refresh_status()

    def _draw_busy_bar(self) -> None:
        self._busy_bar.delete("all")
        w = max(self._busy_bar.winfo_width(), 2)
        self._busy_bar.create_rectangle(0, 0, w, 4, fill=GREEN_DARK, outline="")
        if not self._busy:
            return
        span = max(40, w // 4)
        x = int((self._busy_phase * 8) % (w + span)) - span
        self._busy_bar.create_rectangle(x, 0, x + span, 4, fill=GREEN, outline="")
        self._busy_bar.create_rectangle(
            x, 0, x + span // 4, 4, fill=GREEN_BRIGHT, outline=""
        )

    def _tick_busy(self) -> None:
        if not self._busy:
            self._draw_busy_bar()
            return
        self._busy_phase += 1
        self._draw_busy_bar()
        self._busy_job = self.after(30, self._tick_busy)

    def _on_close(self) -> None:
        self._release_wheel()
        if self._busy_job is not None:
            self.after_cancel(self._busy_job)
        for effect in self._effects:
            stop = getattr(effect, "stop", None)
            if callable(stop):
                stop()
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
        active = sum(1 for f in (snapshot.get("features") or []) if f.get("on"))

        if not chrome_found:
            self.hero_title.configure(text="chrome not found", fg=HOT)
            self._hero_sub.configure(text="install chrome then refresh")
            if self._hero_edge is not None:
                self._hero_edge.configure(bg=HOT)
        elif installed:
            self.hero_title.configure(text="online", fg=GREEN_BRIGHT)
            self._hero_sub.configure(text=f"{active}/4 modules active")
            if self._hero_edge is not None:
                self._hero_edge.configure(bg=GREEN)
        else:
            self.hero_title.configure(text="offline", fg=MUTED)
            self._hero_sub.configure(text="ready to install")
            if self._hero_edge is not None:
                self._hero_edge.configure(bg=AMBER)

        self._clear_cards()
        for i, feature in enumerate(snapshot.get("features") or [], start=1):
            card = FeatureCard(
                self.cards,
                feature.get("label") or "",
                i,
                on=bool(feature.get("on")),
            )
            card.pack(fill=tk.X, pady=(0, 10))

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
            self.hero_title.configure(text="status unavailable", fg=HOT)
            self._hero_sub.configure(text="check Documents\\Untrace\\untrace.log")
            if self._hero_edge is not None:
                self._hero_edge.configure(bg=HOT)
            if not self._busy:
                self.uninstall_btn.set_enabled(False)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        if busy:
            self.install_btn.set_enabled(False)
            self.uninstall_btn.set_enabled(False)
            self.refresh_btn.set_enabled(False)
            self._busy_phase = 0
            self._tick_busy()
            return
        if self._busy_job is not None:
            self.after_cancel(self._busy_job)
            self._busy_job = None
        self._draw_busy_bar()
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

        def on_confirm(ok: bool) -> None:
            if not ok:
                return
            self._start_action(action, label)

        ask_confirm(
            self,
            label,
            f"{label} untrace?",
            on_confirm,
            danger=action == "uninstall",
        )

    def _start_action(self, action: str, label: str) -> None:
        self._set_busy(True)
        self.hero_title.configure(text=f"{label.lower()}ing…", fg=GREEN)
        self._hero_sub.configure(text="writing system state")
        if self._hero_edge is not None:
            self._hero_edge.configure(bg=GREEN)

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
            show_notice(self, "error", err, danger=True)
            return
        if code == 0:
            show_notice(
                self,
                "done",
                "install finished." if action == "install" else "uninstall finished.",
            )
        else:
            show_notice(
                self,
                "error",
                f"{action} exited with code {code}.",
                danger=True,
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
