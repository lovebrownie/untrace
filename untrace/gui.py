from __future__ import annotations

import math
import random
import threading
import time
import tkinter as tk
from pathlib import Path

from untrace import applog
from untrace.paths import IS_WINDOWS, assets_dir
from untrace.version import version_tag

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
WM_CLASS = "Untrace"

ASSETS_DIR = assets_dir()
ICON_PNG = ASSETS_DIR / "icon.png"
ICON_ICO = ASSETS_DIR / "icon.ico"


def _fetch_status() -> dict:
    from untrace.__main__ import gui_status

    return gui_status()


def _run_action(action: str) -> tuple[int, str]:
    from untrace.__main__ import install, uninstall

    applog.write(f"gui: starting {action}")
    try:
        if action == "install":
            install(
                stealth_extension=True,
                launch_wrapper=True,
                chromedriver_cdc=True,
            )
        elif action == "uninstall":
            uninstall()
        else:
            raise ValueError(action)
    except SystemExit as exc:
        raw = exc.code
        if raw is None:
            applog.write(f"gui: {action} finished code=0")
            return 0, ""
        if isinstance(raw, str):
            msg = raw.strip()
            applog.write(f"gui: {action} exit: {msg}")
            applog.write(f"gui: {action} finished code=1")
            return 1, msg or f"{action} failed."
        code = raw if isinstance(raw, int) else 1
        applog.write(f"gui: {action} finished code={code}")
        if code == 0:
            return 0, ""
        return code, f"{action} exited with code {code}."
    except Exception as exc:
        applog.write(f"gui: {action} failed: {exc!r}")
        raise
    applog.write(f"gui: {action} finished code=0")
    return 0, ""


def _bind_tree(widget: tk.Misc, sequence: str, handler) -> None:
    widget.bind(sequence, handler, add="+")
    for child in widget.winfo_children():
        _bind_tree(child, sequence, handler)


def phosphor_shell(
    master: tk.Misc, *, content_bg: str = BG, pad: int = 0
) -> tuple[tk.Frame, tk.Frame]:
    glow = tk.Frame(master, bg=GREEN, padx=1, pady=1)
    mid = tk.Frame(glow, bg=GREEN_DIM, padx=2, pady=2)
    mid.pack(fill=tk.BOTH, expand=True)
    edge = tk.Frame(mid, bg=MUTED, padx=1, pady=1)
    edge.pack(fill=tk.BOTH, expand=True)
    body = tk.Frame(edge, bg=content_bg, padx=pad, pady=pad)
    body.pack(fill=tk.BOTH, expand=True)
    return glow, body


class GreenRule(tk.Canvas):
    def __init__(self, master: tk.Misc, *, height: int = 3) -> None:
        super().__init__(
            master, height=height, bg=BG, highlightthickness=0, borderwidth=0
        )
        self._height = height
        self._last_w = -1
        self.bind("<Configure>", self._redraw)
        self._redraw()

    def _redraw(self, _event=None) -> None:
        w = max(self.winfo_width(), 2)
        if w == self._last_w:
            return
        self._last_w = w
        self.delete("all")
        h = self._height
        self.create_rectangle(0, 0, w, h, fill=GREEN_DIM, outline="")
        if h >= 2:
            self.create_rectangle(0, 0, w, 1, fill=GREEN, outline="")
            self.create_rectangle(0, h - 1, w, h, fill=BORDER, outline="")
        else:
            self.create_rectangle(0, 0, w, h, fill=GREEN, outline="")


class TypewriterLabel(tk.Label):
    def __init__(
        self,
        master: tk.Misc,
        full: str,
        *,
        type_ms: int = 220,
        hold_ms: int = 4500,
        erase_ms: int = 140,
        gap_ms: int = 900,
        typo_chance: float = 0.08,
        **kwargs,
    ) -> None:
        super().__init__(master, text=full, **kwargs)
        self._full = full
        self._display = full
        self._target_i = len(full)
        self._type_ms = type_ms
        self._hold_ms = hold_ms
        self._erase_ms = erase_ms
        self._gap_ms = gap_ms
        self._typo_chance = typo_chance
        self._typo_left = 0
        self._typo_count = 0
        self._fix_left = 0
        self._typo_used = False
        self._hesitate = False
        self._phase = "hold"
        self._job: str | None = None
        self._running = True
        self._paused = False
        self._job = self.after(self._hold_ms, self._tick)

    def _wrong_char(self, correct: str) -> str:
        pool = "abcdefghijklmnopqrstuvwxyz"
        options = [c for c in pool if c != correct.lower()]
        ch = random.choice(options)
        return ch.upper() if correct.isupper() else ch

    def pause(self) -> None:
        self._paused = True
        if self._job is not None:
            self.after_cancel(self._job)
            self._job = None

    def resume(self) -> None:
        if not self._paused:
            return
        self._paused = False
        if self._running and self._job is None:
            self._job = self.after(self._type_ms, self._tick)

    def _tick(self) -> None:
        self._job = None
        if not self._running or self._paused:
            return
        if self._phase == "type":
            if self._hesitate:
                self._hesitate = False
                self._job = self.after(self._erase_ms * 2, self._tick)
                return
            if self._fix_left > 0:
                self._display = self._display[:-1]
                self._fix_left -= 1
                self.configure(text=self._display)
                self._job = self.after(self._erase_ms, self._tick)
                return
            if self._typo_left > 0:
                correct = (
                    self._full[self._target_i]
                    if self._target_i < len(self._full)
                    else "a"
                )
                self._display += self._wrong_char(correct)
                self._typo_left -= 1
                if self._typo_left == 0:
                    self._fix_left = self._typo_count
                    self._hesitate = True
                self.configure(text=self._display)
                self._job = self.after(self._type_ms, self._tick)
                return
            if self._target_i >= len(self._full):
                self.configure(text=self._full)
                self._phase = "hold"
                self._job = self.after(self._hold_ms, self._tick)
                return
            if (
                not self._typo_used
                and self._target_i > 0
                and self._target_i < len(self._full)
                and random.random() < self._typo_chance
            ):
                self._typo_used = True
                self._typo_count = random.randint(1, 2)
                self._typo_left = self._typo_count
                self._tick()
                return
            self._display += self._full[self._target_i]
            self._target_i += 1
            self.configure(text=self._display)
            self._job = self.after(self._type_ms, self._tick)
        elif self._phase == "hold":
            self._phase = "erase"
            self._tick()
        elif self._phase == "erase":
            if self._display:
                self._display = self._display[:-1]
                self._target_i = min(self._target_i, len(self._display))
                self.configure(text=self._display)
                self._job = self.after(self._erase_ms, self._tick)
            else:
                self._target_i = 0
                self._phase = "gap"
                self._job = self.after(self._gap_ms, self._tick)
        else:
            self._phase = "type"
            self._display = ""
            self._target_i = 0
            self._typo_left = 0
            self._fix_left = 0
            self._typo_used = False
            self._hesitate = False
            self._tick()

    def stop(self) -> None:
        self._running = False
        self._paused = True
        if self._job is not None:
            self.after_cancel(self._job)
            self._job = None


class BlinkCursor(tk.Label):
    def __init__(self, master: tk.Misc, **kwargs) -> None:
        super().__init__(master, **kwargs)
        self._on = True
        self._job: str | None = None
        self._paused = False
        self._tick()

    def pause(self) -> None:
        self._paused = True
        if self._job is not None:
            self.after_cancel(self._job)
            self._job = None

    def resume(self) -> None:
        if not self._paused:
            return
        self._paused = False
        if self._job is None:
            self._job = self.after(480, self._tick)

    def _tick(self) -> None:
        self._job = None
        if self._paused:
            return
        self._on = not self._on
        self.configure(text="▌" if self._on else " ")
        self._job = self.after(480, self._tick)

    def stop(self) -> None:
        self._paused = True
        if self._job is not None:
            self.after_cancel(self._job)
            self._job = None


class PulseDot(tk.Canvas):
    def __init__(self, master: tk.Misc, *, on: bool, bg: str) -> None:
        super().__init__(master, width=18, height=18, bg=bg, highlightthickness=0)
        self._on = on
        self._phase = 0
        self._job: str | None = None
        self._paused = True
        self._paint()

    def pause(self) -> None:
        self._paused = True
        if self._job is not None:
            self.after_cancel(self._job)
            self._job = None

    def resume(self) -> None:
        if not self._paused:
            return
        self._paused = False
        if self._on and self._job is None:
            self._job = self.after(55, self._tick)

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
        self._job = None
        if self._paused or not self._on:
            return
        self._phase += 1
        self._paint()
        self._job = self.after(55, self._tick)

    def stop(self) -> None:
        self.pause()


class ActivitySpinner(tk.Label):
    FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")

    def __init__(self, master: tk.Misc, **kwargs) -> None:
        super().__init__(master, text=self.FRAMES[0], **kwargs)
        self._i = 0
        self._job: str | None = None
        self._running = True
        self._paused = False
        self._tick()

    def pause(self) -> None:
        self._paused = True
        if self._job is not None:
            self.after_cancel(self._job)
            self._job = None

    def resume(self) -> None:
        if not self._paused:
            return
        self._paused = False
        if self._running and self._job is None:
            self._job = self.after(80, self._tick)

    def _tick(self) -> None:
        self._job = None
        if not self._running or self._paused:
            return
        self._i = (self._i + 1) % len(self.FRAMES)
        self.configure(text=self.FRAMES[self._i])
        self._job = self.after(80, self._tick)

    def stop(self) -> None:
        self._running = False
        self._paused = True
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
            master, bg=SURFACE, highlightthickness=1, highlightbackground=MUTED
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
        self.configure(highlightbackground=MUTED, bg=SURFACE)
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
        border = GREEN if primary else (HOT if danger else MUTED)
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
            self.configure(highlightbackground=MUTED)
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

    def set_text(self, text: str) -> None:
        self._btn.configure(text=f"[ {text.upper()} ]")


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

        card, body = phosphor_shell(self, content_bg=SURFACE, pad=0)
        card.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
        body.configure(padx=28, pady=22)

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


class LoadingOverlay(tk.Frame):
    def __init__(self, master: tk.Misc, message: str = "refreshing status…") -> None:
        super().__init__(master, bg="#010502")
        self._job: str | None = None
        self._phase = 0
        self.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.lift()

        dim = tk.Frame(self, bg="#010502")
        dim.place(relx=0, rely=0, relwidth=1, relheight=1)

        card, body = phosphor_shell(self, content_bg=SURFACE)
        card.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
        body.configure(padx=36, pady=28)

        row = tk.Frame(body, bg=SURFACE)
        row.pack()
        self._spinner = ActivitySpinner(row, bg=SURFACE, fg=GREEN, font=(FONT, 16))
        self._spinner.pack(side=tk.LEFT, padx=(0, 12))
        self._label = tk.Label(
            row,
            text=message,
            bg=SURFACE,
            fg=GREEN_BRIGHT,
            font=(FONT, 12, "bold"),
        )
        self._label.pack(side=tk.LEFT)

        self._bar = tk.Canvas(
            body, width=220, height=4, bg=SURFACE, highlightthickness=0, borderwidth=0
        )
        self._bar.pack(pady=(18, 0))
        self._tick()

    def set_message(self, message: str) -> None:
        self._label.configure(text=message)

    def _tick(self) -> None:
        self._phase += 1
        self._bar.delete("all")
        w = 220
        self._bar.create_rectangle(0, 0, w, 4, fill=GREEN_DARK, outline="")
        span = 70
        x = int((self._phase * 10) % (w + span)) - span
        self._bar.create_rectangle(x, 0, x + span, 4, fill=GREEN, outline="")
        self._bar.create_rectangle(
            x, 0, x + span // 3, 4, fill=GREEN_BRIGHT, outline=""
        )
        self._job = self.after(40, self._tick)

    def close(self) -> None:
        if self._job is not None:
            self.after_cancel(self._job)
            self._job = None
        self._spinner.stop()
        self.destroy()


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
        self._paused = False
        self.bind("<Configure>", lambda _e: self._redraw())
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<MouseWheel>", self._on_wheel)
        self._tick()

    def pause(self) -> None:
        self._paused = True
        if self._job is not None:
            self.after_cancel(self._job)
            self._job = None

    def resume(self) -> None:
        if not self._paused:
            return
        self._paused = False
        if self._job is None:
            self._job = self.after(120, self._tick)

    def set(self, first: float | str, last: float | str) -> None:
        self._first = max(0.0, min(1.0, float(first)))
        self._last = max(0.0, min(1.0, float(last)))
        if self._last < self._first:
            self._last = self._first
        self._redraw()

    def _track_metrics(self) -> tuple[int, int, int, float]:
        h = max(self.winfo_height(), 2)
        track = max(1, h - 36)
        span = max(0.0, self._last - self._first)
        if span >= 0.999:
            thumb_h = track
        else:
            thumb_h = max(28, int(span * track))
            thumb_h = min(thumb_h, track)
        return h, track, thumb_h, span

    def _thumb_y(self, track: int, thumb_h: int, span: float) -> int:
        travel = max(0, track - thumb_h)
        if travel == 0 or span >= 0.999:
            return 18
        max_first = max(1e-9, 1.0 - span)
        ratio = max(0.0, min(1.0, self._first / max_first))
        return 18 + int(ratio * travel)

    def _redraw(self) -> None:
        self.delete("all")
        h, track, thumb_h, span = self._track_metrics()
        w = max(self.winfo_width(), 2)
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
        thumb_y = self._thumb_y(track, thumb_h, span)
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
        self._job = None
        if self._paused:
            return
        self._phase += 1
        if self._hover:
            self._redraw()
        self._job = self.after(120, self._tick)

    def stop(self) -> None:
        self._paused = True
        if self._job is not None:
            self.after_cancel(self._job)
            self._job = None

    def _moveto_from_y(self, y: int) -> None:
        _h, track, thumb_h, span = self._track_metrics()
        travel = max(1, track - thumb_h)
        if span >= 0.999:
            self._target.yview_moveto(0.0)
            return
        ratio = max(0.0, min(1.0, (y - 18) / travel))
        self._target.yview_moveto(ratio * (1.0 - span))

    def _on_press(self, event) -> None:
        if self._thumb[0] <= event.y <= self._thumb[1]:
            self._dragging = True
            self._drag_offset = event.y - self._thumb[0]
        else:
            self._moveto_from_y(event.y - (self._thumb[1] - self._thumb[0]) // 2)
        self._redraw()

    def _on_drag(self, event) -> None:
        if not self._dragging:
            return
        self._moveto_from_y(event.y - self._drag_offset)

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
        super().__init__(className=WM_CLASS)
        self.title(f"untrace {version_tag()}")
        self.minsize(540, 480)
        self.configure(bg=GREEN)
        self.geometry("960x700")
        try:
            if IS_WINDOWS:
                self.state("zoomed")
            else:
                self.attributes("-zoomed", True)
        except tk.TclError:
            pass
        self._busy = False
        self._refreshing = False
        self._loading: LoadingOverlay | None = None
        self._snapshot: dict | None = None
        self._effects: list = []
        self._hero_edge: tk.Frame | None = None
        self._icon_images: list[tk.PhotoImage] = []
        self._resizing = False
        self._resize_job: str | None = None
        self._last_size = (0, 0)
        self._apply_window_icon()

        border = tk.Frame(self, bg=GREEN, padx=1, pady=1)
        border.pack(fill=tk.BOTH, expand=True)
        shell = tk.Frame(border, bg=BG)
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
        self.bind("<Configure>", self._on_root_configure)
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
            self._body, bg=SURFACE, highlightthickness=1, highlightbackground=MUTED
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

        section = tk.Frame(self._body, bg=BG)
        section.pack(fill=tk.X, pady=(16, 8))
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
        foot_row = tk.Frame(foot, bg=BG)
        foot_row.pack(anchor=tk.W)
        self._footer = tk.Label(
            foot_row,
            text=f"{version_tag()}  ·  ",
            bg=BG,
            fg=MUTED,
            font=(FONT, 8),
        )
        self._footer.pack(side=tk.LEFT)
        self._footer_log = tk.Label(
            foot_row,
            text=f"log → {applog.display_log_path()}",
            bg=BG,
            fg=MUTED,
            font=(FONT, 8, "underline"),
            cursor="hand2",
        )
        self._footer_log.pack(side=tk.LEFT)
        self._footer_log.bind("<Button-1>", lambda _e: self._open_log())
        self._footer_log.bind(
            "<Enter>", lambda _e: self._footer_log.configure(fg=GREEN)
        )
        self._footer_log.bind(
            "<Leave>", lambda _e: self._footer_log.configure(fg=MUTED)
        )

        self.refresh_status()

    def _open_log(self) -> None:
        try:
            applog.reveal_in_file_manager()
        except OSError:
            show_notice(self, "Log", "Could not open the log folder.")

    def _show_loading(self, message: str) -> None:
        self._set_effects_paused(True)
        if self._loading is not None:
            self._loading.set_message(message)
            self._loading.lift()
            return
        self._loading = LoadingOverlay(self, message)

    def _hide_loading(self) -> None:
        if self._loading is not None:
            self._loading.close()
            self._loading = None

    def _finish_ui_busy(self) -> None:
        def resume() -> None:
            try:
                self.update_idletasks()
            except tk.TclError:
                return
            self._set_effects_paused(False)

        self.after(120, resume)

    def _keep_image(self, image: tk.PhotoImage) -> tk.PhotoImage:
        self._icon_images.append(image)
        return image

    def _load_photo(
        self, path: Path, *, subsample: int | None = None
    ) -> tk.PhotoImage | None:
        if not path.is_file():
            return None
        try:
            image = tk.PhotoImage(file=str(path))
        except tk.TclError:
            return None
        if subsample and subsample > 1:
            image = image.subsample(subsample, subsample)
        return self._keep_image(image)

    def _apply_window_icon(self) -> None:
        if IS_WINDOWS and ICON_ICO.is_file():
            try:
                self.iconbitmap(default=str(ICON_ICO.resolve()))
            except tk.TclError:
                pass
        photos: list[tk.PhotoImage] = []
        seen: set[str] = set()
        for path in (
            ASSETS_DIR / "icon-128.png",
            ICON_PNG,
            ASSETS_DIR / "icon-48.png",
            ASSETS_DIR / "icon-16.png",
        ):
            if not path.is_file():
                continue
            key = str(path.resolve())
            if key in seen:
                continue
            seen.add(key)
            photo = self._load_photo(path)
            if photo is not None:
                photos.append(photo)
        if not photos:
            return
        try:
            self.iconphoto(True, *photos)
        except tk.TclError:
            try:
                self.iconphoto(True, photos[0])
            except tk.TclError:
                pass

    def _set_effects_paused(self, paused: bool) -> None:
        for effect in self._effects:
            method = getattr(effect, "pause" if paused else "resume", None)
            if callable(method):
                method()
        cards = getattr(self, "cards", None)
        if cards is None:
            return
        for card in cards.winfo_children():
            dot = getattr(card, "_dot", None)
            if dot is None:
                continue
            method = getattr(dot, "pause" if paused else "resume", None)
            if callable(method):
                method()

    def _begin_resize(self) -> None:
        if self._resizing or self._loading is not None:
            return
        self._resizing = True
        self._set_effects_paused(True)

    def _schedule_end_resize(self) -> None:
        if self._resize_job is not None:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(150, self._end_resize)

    def _end_resize(self) -> None:
        self._resize_job = None
        if not self._resizing:
            return
        self._resizing = False
        try:
            self._on_body_configure()
            self._canvas.itemconfigure(self._body_id, width=self._canvas.winfo_width())
        except tk.TclError:
            pass
        self._finish_ui_busy()

    def _on_root_configure(self, event) -> None:
        if event.widget is not self:
            return
        size = (event.width, event.height)
        if size == self._last_size:
            return
        prev = self._last_size
        self._last_size = size
        if prev == (0, 0):
            return
        if self._loading is not None:
            return
        self._begin_resize()
        self._schedule_end_resize()

    def _on_close(self) -> None:
        self._release_wheel()
        self._hide_loading()
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
        if self._resizing:
            return
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_configure(self, event) -> None:
        if self._resizing:
            return
        self._canvas.itemconfigure(self._body_id, width=event.width)

    def _clear_cards(self) -> None:
        for child in self.cards.winfo_children():
            child.destroy()

    def _set_hero_sub(self, text: str, *, open_log: bool = False) -> None:
        self._hero_sub.unbind("<Button-1>")
        if open_log:
            self._hero_sub.configure(
                text=text,
                fg=MUTED,
                font=(FONT, 9, "underline"),
                cursor="hand2",
            )
            self._hero_sub.bind("<Button-1>", lambda _e: self._open_log())
            return
        self._hero_sub.configure(
            text=text,
            fg=MUTED,
            font=(FONT, 9),
            cursor="",
        )

    def _render(self, snapshot: dict) -> None:
        self._snapshot = snapshot
        installed = bool(snapshot.get("installed"))
        chrome_found = bool(snapshot.get("chrome_found"))
        active = sum(1 for f in (snapshot.get("features") or []) if f.get("on"))

        if not chrome_found:
            self.hero_title.configure(text="chrome not found", fg=HOT)
            self._set_hero_sub("install chrome then refresh")
            if self._hero_edge is not None:
                self._hero_edge.configure(bg=HOT)
        elif installed:
            self.hero_title.configure(text="online", fg=GREEN_BRIGHT)
            self._set_hero_sub(f"{active}/4 modules active")
            if self._hero_edge is not None:
                self._hero_edge.configure(bg=GREEN)
        else:
            self.hero_title.configure(text="offline", fg=MUTED)
            self._set_hero_sub("ready to install")
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
            self.install_btn.set_text("Update" if installed else "Install")
            self.install_btn.set_enabled(bool(snapshot.get("can_install")))
            self.uninstall_btn.set_enabled(bool(snapshot.get("can_uninstall")))
            self.refresh_btn.set_enabled(True)

    def refresh_status(self, on_done=None) -> None:
        if self._busy or self._refreshing:
            if on_done is not None:
                on_done()
            return
        self._refreshing = True
        self._refresh_on_done = on_done
        self.install_btn.set_enabled(False)
        self.uninstall_btn.set_enabled(False)
        self.refresh_btn.set_enabled(False)
        self._show_loading("refreshing status…")
        started = time.monotonic()

        def worker() -> None:
            snap = None
            failed = False
            try:
                snap = _fetch_status()
            except Exception:
                failed = True

            def finish() -> None:
                elapsed_ms = int((time.monotonic() - started) * 1000)
                delay = max(0, 450 - elapsed_ms)
                self.after(delay, lambda: self._refresh_done(snap, failed))

            self.after(0, finish)

        threading.Thread(target=worker, daemon=True).start()

    def _refresh_done(self, snapshot: dict | None, failed: bool) -> None:
        self._set_effects_paused(True)
        self._refreshing = False
        callback = getattr(self, "_refresh_on_done", None)
        self._refresh_on_done = None
        if failed or snapshot is None:
            self._clear_cards()
            self.hero_title.configure(text="status unavailable", fg=HOT)
            self._set_hero_sub(
                f"check {applog.display_log_path()} (click to open)",
                open_log=True,
            )
            if self._hero_edge is not None:
                self._hero_edge.configure(bg=HOT)
            if not self._busy:
                self.install_btn.set_enabled(
                    bool((self._snapshot or {}).get("can_install"))
                )
                self.uninstall_btn.set_enabled(False)
                self.refresh_btn.set_enabled(True)
            try:
                self.update_idletasks()
            except tk.TclError:
                pass
            self._hide_loading()
            self._finish_ui_busy()
            if callback is not None:
                callback()
            return
        self._render(snapshot)
        try:
            self.update_idletasks()
        except tk.TclError:
            pass
        self._hide_loading()
        self._finish_ui_busy()
        if callback is not None:
            callback()

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        if busy:
            self.install_btn.set_enabled(False)
            self.uninstall_btn.set_enabled(False)
            self.refresh_btn.set_enabled(False)
            return
        if self._refreshing:
            return
        snap = self._snapshot or {}
        installed = bool(snap.get("installed"))
        self.install_btn.set_text("Update" if installed else "Install")
        self.install_btn.set_enabled(bool(snap.get("can_install", True)))
        self.uninstall_btn.set_enabled(bool(snap.get("can_uninstall")))
        self.refresh_btn.set_enabled(True)

    def _run(self, action: str) -> None:
        if self._busy or self._refreshing:
            return
        if action == "uninstall" and not (self._snapshot or {}).get("can_uninstall"):
            return
        if action == "install" and not (self._snapshot or {}).get("can_install"):
            return

        if action == "install":
            label = "Update" if (self._snapshot or {}).get("installed") else "Install"
        else:
            label = "Uninstall"

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
        self._show_loading(f"{label.lower()}ing…")

        def worker() -> None:
            code = 1
            err = ""
            try:
                code, err = _run_action(action)
            except Exception as exc:
                err = str(exc)
            self.after(0, lambda: self._done(action, label, code, err))

        threading.Thread(target=worker, daemon=True).start()

    def _done(self, action: str, label: str, code: int, err: str) -> None:
        self._set_busy(False)

        def after_status() -> None:
            if err:
                show_notice(self, "error", err, danger=True)
                return
            if code == 0:
                if action == "uninstall":
                    msg = "untrace uninstalled."
                elif label.lower() == "update":
                    msg = "untrace updated."
                else:
                    msg = "untrace installed."
                show_notice(self, "done", msg)
            else:
                show_notice(
                    self,
                    "error",
                    f"{label.lower()} exited with code {code}.",
                    danger=True,
                )

        self.refresh_status(on_done=after_status)


def main() -> None:
    from untrace.__main__ import ensure_privileges, hide_windows_console

    applog.enable(command="--gui")
    hide_windows_console()
    ensure_privileges(show_console=False)
    hide_windows_console()
    app = UntraceGui()
    app.mainloop()


if __name__ == "__main__":
    main()
