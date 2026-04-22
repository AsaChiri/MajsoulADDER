"""MajsoulAdder — a tiny mouse-click looper with annotation overlay.

Run:   uv run python MajsoulAdder.py
Tests: uv run pytest
"""

from __future__ import annotations

import threading
import time
import tkinter as tk
from dataclasses import dataclass
from tkinter import ttk
from typing import Callable, Optional

from pynput import keyboard, mouse


# ---------------------------------------------------------------------------
# Win32 click-through helper (pure; no ctypes call, testable in isolation)
# ---------------------------------------------------------------------------

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020


def _compute_ex_style(current: int) -> int:
    return current | WS_EX_LAYERED | WS_EX_TRANSPARENT


# ---------------------------------------------------------------------------
# Pure data + model
# ---------------------------------------------------------------------------


@dataclass
class Position:
    x: int
    y: int
    extra_delay: float = 0.0


class PositionModel:
    """In-memory list of Positions with change notifications."""

    def __init__(self) -> None:
        self._positions: list[Position] = []
        self._listeners: list[Callable[[], None]] = []

    def add_listener(self, fn: Callable[[], None]) -> None:
        self._listeners.append(fn)

    def _notify(self) -> None:
        for fn in list(self._listeners):
            fn()

    def __len__(self) -> int:
        return len(self._positions)

    def __getitem__(self, i: int) -> Position:
        return self._positions[i]

    def snapshot(self) -> list[Position]:
        return [Position(p.x, p.y, p.extra_delay) for p in self._positions]

    def add(self, x: int, y: int, extra_delay: float = 0.0) -> None:
        self._positions.append(Position(int(x), int(y), float(extra_delay)))
        self._notify()

    def replace(self, i: int, x: int, y: int) -> None:
        prev = self._positions[i]
        self._positions[i] = Position(int(x), int(y), prev.extra_delay)
        self._notify()

    def delete(self, i: int) -> None:
        del self._positions[i]
        self._notify()

    def move_up(self, i: int) -> None:
        if i <= 0 or i >= len(self._positions):
            return
        a, b = i - 1, i
        self._positions[a], self._positions[b] = self._positions[b], self._positions[a]
        self._notify()

    def move_down(self, i: int) -> None:
        if i < 0 or i >= len(self._positions) - 1:
            return
        a, b = i, i + 1
        self._positions[a], self._positions[b] = self._positions[b], self._positions[a]
        self._notify()

    def clear(self) -> None:
        if not self._positions:
            self._notify()
            return
        self._positions.clear()
        self._notify()

    def set_extra_delay(self, i: int, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("extra_delay must be >= 0")
        prev = self._positions[i]
        self._positions[i] = Position(prev.x, prev.y, float(seconds))
        self._notify()


# ---------------------------------------------------------------------------
# Click worker
# ---------------------------------------------------------------------------


class ClickWorker:
    """Replays a snapshot of positions in a loop with pause/resume/stop."""

    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"

    def __init__(
        self,
        snapshot: list[Position],
        *,
        interval_ms: int = 20,
        loop_delay_ms: int = 100,
        click_fn: Optional[Callable[[int, int], None]] = None,
        sleep_fn: Callable[[float], None] = time.sleep,
        on_step: Optional[Callable[[int, int], None]] = None,
        on_state: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._snapshot = list(snapshot)
        self._interval_s = interval_ms / 1000.0
        self._loop_delay_s = loop_delay_ms / 1000.0
        self._click = click_fn if click_fn is not None else self._default_click
        self._sleep = sleep_fn
        self._on_step = on_step or (lambda step, total: None)
        self._on_state = on_state or (lambda s: None)
        self._run = threading.Event()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._state = self.IDLE

    @staticmethod
    def _default_click(x: int, y: int) -> None:
        ctr = mouse.Controller()
        ctr.position = (x, y)
        ctr.click(mouse.Button.left)

    @property
    def state(self) -> str:
        return self._state

    def _set_state(self, s: str) -> None:
        self._state = s
        self._on_state(s)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._run.set()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._set_state(self.RUNNING)
        self._thread.start()

    def pause(self) -> None:
        if self._state != self.RUNNING:
            return
        self._run.clear()
        self._set_state(self.PAUSED)

    def resume(self) -> None:
        if self._state != self.PAUSED:
            return
        self._run.set()
        self._set_state(self.RUNNING)

    def stop(self, join_timeout: float = 1.0) -> None:
        self._stop.set()
        self._run.set()  # unblock a paused wait
        t = self._thread
        if t and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=join_timeout)
        self._set_state(self.IDLE)

    def _loop(self) -> None:
        try:
            total = len(self._snapshot)
            if total == 0:
                return
            while not self._stop.is_set():
                for i, pos in enumerate(self._snapshot):
                    if self._stop.is_set():
                        return
                    if not self._run.is_set():
                        self._run.wait()
                        if self._stop.is_set():
                            return
                    self._click(pos.x, pos.y)
                    self._on_step(i + 1, total)
                    self._sleep(self._interval_s)
                    if pos.extra_delay:
                        self._sleep(pos.extra_delay)
                self._sleep(self._loop_delay_s)
        finally:
            self._set_state(self.IDLE)


# ---------------------------------------------------------------------------
# Annotation capture
# ---------------------------------------------------------------------------


class CaptureController:
    """Owns the 'add position' flow. Listener creation is injectable for tests."""

    MODE_APPEND = "append"
    MODE_REPLACE = "replace"

    def __init__(
        self,
        model: PositionModel,
        *,
        mouse_listener_factory: Optional[Callable[[Callable], object]] = None,
        keyboard_listener_factory: Optional[Callable[[Callable], object]] = None,
        on_state: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._model = model
        self._mk_mouse = mouse_listener_factory or (
            lambda on_click: mouse.Listener(on_click=on_click)
        )
        self._mk_keyboard = keyboard_listener_factory or (
            lambda on_press: keyboard.Listener(on_press=on_press)
        )
        self._on_state = on_state or (lambda s: None)
        self._mode: Optional[str] = None
        self._replace_index: Optional[int] = None
        self._mouse_listener = None
        self._keyboard_listener = None
        self._lock = threading.Lock()

    @property
    def active(self) -> bool:
        return self._mode is not None

    def start_append(self) -> None:
        with self._lock:
            if self._mode is not None:
                raise RuntimeError("capture already active")
            self._mode = self.MODE_APPEND
            self._replace_index = None
        self._start_listeners()
        self._on_state("capturing")

    def start_replace(self, index: int) -> None:
        if index < 0 or index >= len(self._model):
            raise IndexError(index)
        with self._lock:
            if self._mode is not None:
                raise RuntimeError("capture already active")
            self._mode = self.MODE_REPLACE
            self._replace_index = index
        self._start_listeners()
        self._on_state("capturing")

    def stop(self) -> None:
        with self._lock:
            if self._mode is None:
                return
            self._mode = None
            self._replace_index = None
            ml, kl = self._mouse_listener, self._keyboard_listener
            self._mouse_listener = None
            self._keyboard_listener = None
        for lis in (ml, kl):
            if lis is not None:
                try:
                    lis.stop()
                except Exception:
                    pass
        self._on_state("idle")

    def _start_listeners(self) -> None:
        self._mouse_listener = self._mk_mouse(self._on_click)
        self._keyboard_listener = self._mk_keyboard(self._on_key)
        for lis in (self._mouse_listener, self._keyboard_listener):
            start = getattr(lis, "start", None)
            if callable(start):
                start()

    def _on_click(self, x: int, y: int, button, pressed: bool) -> None:
        if not self.active or not pressed:
            return
        if _is_left_button(button):
            if self._mode == self.MODE_APPEND:
                self._model.add(x, y)
            elif self._mode == self.MODE_REPLACE:
                idx = self._replace_index
                if idx is not None:
                    self._model.replace(idx, x, y)
                self.stop()
        else:
            self.stop()

    def _on_key(self, key) -> None:
        if not self.active:
            return
        if _is_esc_key(key):
            self.stop()


def _is_left_button(button) -> bool:
    left = getattr(mouse.Button, "left", None)
    if left is not None and button == left:
        return True
    name = getattr(button, "name", None)
    return name == "left"


def _is_esc_key(key) -> bool:
    esc = getattr(keyboard.Key, "esc", None)
    if esc is not None and key == esc:
        return True
    name = getattr(key, "name", None)
    return name == "esc"


# ---------------------------------------------------------------------------
# Tk / pynput glue (not unit-tested; exercised by manual verification)
# ---------------------------------------------------------------------------


class HotkeyBinder:
    def __init__(self, bindings: dict) -> None:
        self._binder = keyboard.GlobalHotKeys(bindings)

    def start(self) -> None:
        self._binder.start()

    def stop(self) -> None:
        try:
            self._binder.stop()
        except Exception:
            pass


class OverlayWindow:
    """Transparent click-through full-screen layer that draws numbered circles."""

    BG_COLOR = "#ff00fe"
    CIRCLE_FILL = "#e53935"
    CIRCLE_OUTLINE = "white"
    TEXT_COLOR = "white"
    RADIUS = 18

    def __init__(self, root: tk.Tk, model: PositionModel) -> None:
        self._root = root
        self._model = model
        self._win = tk.Toplevel(root)
        self._win.overrideredirect(True)
        self._win.attributes("-topmost", True)
        w, h = root.winfo_screenwidth(), root.winfo_screenheight()
        self._win.geometry(f"{w}x{h}+0+0")
        try:
            self._win.attributes("-transparentcolor", self.BG_COLOR)
        except tk.TclError:
            pass
        self._canvas = tk.Canvas(
            self._win, bg=self.BG_COLOR, highlightthickness=0
        )
        self._canvas.pack(fill="both", expand=True)
        self._apply_clickthrough()
        self._win.withdraw()
        self._visible = False

    def _apply_clickthrough(self) -> None:
        try:
            import ctypes

            hwnd = ctypes.windll.user32.GetParent(self._win.winfo_id())
            ex = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(
                hwnd, GWL_EXSTYLE, _compute_ex_style(ex)
            )
        except Exception:
            pass

    def show(self) -> None:
        if not self._visible:
            self._win.deiconify()
            self._win.attributes("-topmost", True)
            self._visible = True
        self.redraw()

    def hide(self) -> None:
        if self._visible:
            self._win.withdraw()
            self._visible = False

    def is_visible(self) -> bool:
        return self._visible

    def redraw(self) -> None:
        if not self._visible:
            return
        self._canvas.delete("all")
        r = self.RADIUS
        for idx, pos in enumerate(self._model.snapshot()):
            x, y = pos.x, pos.y
            self._canvas.create_oval(
                x - r, y - r, x + r, y + r,
                fill=self.CIRCLE_FILL, outline=self.CIRCLE_OUTLINE, width=2,
            )
            self._canvas.create_text(
                x, y, text=str(idx + 1),
                fill=self.TEXT_COLOR, font=("Segoe UI", 12, "bold"),
            )

    def destroy(self) -> None:
        try:
            self._win.destroy()
        except Exception:
            pass


class App:
    HOTKEY_START = "<f7>"
    HOTKEY_PAUSE = "<f8>"
    HOTKEY_STOP = "<f9>"
    HOTKEY_ADD = "<f10>"

    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("MajsoulAdder")
        self.root.attributes("-topmost", True)
        self.root.minsize(480, 420)

        self.model = PositionModel()
        self._worker: Optional[ClickWorker] = None
        self._controller = mouse.Controller()

        self.capture = CaptureController(
            self.model,
            on_state=lambda s: self.root.after(0, self._on_capture_state, s),
        )

        self._build_ui()
        self.model.add_listener(lambda: self.root.after(0, self._refresh_tree))

        self.overlay: Optional[OverlayWindow] = None
        try:
            self.overlay = OverlayWindow(self.root, self.model)
            self.model.add_listener(
                lambda: self.root.after(0, self._refresh_overlay)
            )
        except Exception as e:
            self._set_status(f"overlay unavailable: {e}")

        self.hotkeys = HotkeyBinder(
            {
                self.HOTKEY_START: lambda: self.root.after(0, self._start),
                self.HOTKEY_PAUSE: lambda: self.root.after(0, self._toggle_pause),
                self.HOTKEY_STOP: lambda: self.root.after(0, self._stop),
                self.HOTKEY_ADD: lambda: self.root.after(0, self._add),
            }
        )
        try:
            self.hotkeys.start()
        except Exception as e:
            self._set_status(f"hotkeys unavailable: {e}")

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._refresh_tree()

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=8)
        outer.pack(fill="both", expand=True)

        list_frame = ttk.Frame(outer)
        list_frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(
            list_frame,
            columns=("idx", "x", "y", "delay"),
            show="headings",
            height=8,
            selectmode="browse",
        )
        for col, label, w in (
            ("idx", "#", 36),
            ("x", "X", 80),
            ("y", "Y", 80),
            ("delay", "Extra delay (s)", 120),
        ):
            self.tree.heading(col, text=label)
            self.tree.column(col, width=w, anchor="center")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<Double-1>", self._on_tree_double_click)
        vsb = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        vsb.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=vsb.set)

        actions = ttk.Frame(outer)
        actions.pack(fill="x", pady=(6, 0))
        ttk.Button(actions, text="Add position", command=self._add).pack(side="left")
        ttk.Button(actions, text="Re-record", command=self._re_record).pack(
            side="left", padx=2
        )
        ttk.Button(actions, text="Delete", command=self._delete).pack(
            side="left", padx=2
        )
        ttk.Button(actions, text="Move up", command=lambda: self._move(-1)).pack(
            side="left", padx=2
        )
        ttk.Button(actions, text="Move down", command=lambda: self._move(1)).pack(
            side="left", padx=2
        )
        ttk.Button(actions, text="Clear all", command=self.model.clear).pack(
            side="left", padx=2
        )

        play = ttk.Frame(outer)
        play.pack(fill="x", pady=(10, 0))
        self.btn_start = ttk.Button(play, text="Start", command=self._start)
        self.btn_start.pack(side="left")
        self.btn_pause = ttk.Button(play, text="Pause", command=self._toggle_pause)
        self.btn_pause.pack(side="left", padx=4)
        self.btn_stop = ttk.Button(play, text="Stop", command=self._stop)
        self.btn_stop.pack(side="left")

        settings = ttk.Frame(outer)
        settings.pack(fill="x", pady=(10, 0))
        ttk.Label(settings, text="Interval (ms)").pack(side="left")
        self.var_interval = tk.IntVar(value=20)
        ttk.Spinbox(
            settings, from_=1, to=5000, width=6, textvariable=self.var_interval
        ).pack(side="left", padx=(4, 12))
        ttk.Label(settings, text="Loop delay (ms)").pack(side="left")
        self.var_loop = tk.IntVar(value=100)
        ttk.Spinbox(
            settings, from_=0, to=60000, width=6, textvariable=self.var_loop
        ).pack(side="left", padx=4)
        self.var_overlay = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            settings,
            text="Show overlay",
            variable=self.var_overlay,
            command=self._on_overlay_toggle,
        ).pack(side="right")

        self.status_var = tk.StringVar(value="Idle")
        ttk.Label(outer, textvariable=self.status_var, anchor="w").pack(
            fill="x", pady=(10, 0)
        )
        ttk.Label(
            outer,
            text="F7 start  ·  F8 pause/resume  ·  F9 stop  ·  F10 add position  ·  Esc end capture",
            foreground="#666",
        ).pack(fill="x")

    def _refresh_tree(self) -> None:
        prev = self.tree.selection()
        prev_idx = int(prev[0]) if prev else None
        self.tree.delete(*self.tree.get_children())
        for i, pos in enumerate(self.model.snapshot()):
            self.tree.insert(
                "",
                "end",
                iid=str(i),
                values=(i + 1, pos.x, pos.y, f"{pos.extra_delay:g}"),
            )
        if prev_idx is not None and prev_idx < len(self.model):
            self.tree.selection_set(str(prev_idx))
        self._update_buttons()

    def _refresh_overlay(self) -> None:
        if self.overlay:
            self.overlay.redraw()

    def _update_buttons(self) -> None:
        worker = self._worker
        state = worker.state if worker else ClickWorker.IDLE
        has_rows = len(self.model) > 0
        self.btn_start.configure(
            state=("normal" if state == ClickWorker.IDLE and has_rows else "disabled")
        )
        if state == ClickWorker.PAUSED:
            self.btn_pause.configure(text="Resume", state="normal")
        elif state == ClickWorker.RUNNING:
            self.btn_pause.configure(text="Pause", state="normal")
        else:
            self.btn_pause.configure(text="Pause", state="disabled")
        self.btn_stop.configure(
            state=("normal" if state != ClickWorker.IDLE else "disabled")
        )

    def _set_status(self, text: str) -> None:
        self.status_var.set(text)

    def _selected_index(self) -> Optional[int]:
        sel = self.tree.selection()
        return int(sel[0]) if sel else None

    def _add(self) -> None:
        if self.capture.active:
            return
        self.var_overlay.set(True)
        if self.overlay:
            self.overlay.show()
        self.root.withdraw()
        try:
            self.capture.start_append()
            self._set_status(
                "Capturing: left-click to add, Esc or right-click to finish"
            )
        except RuntimeError:
            self.root.deiconify()

    def _re_record(self) -> None:
        i = self._selected_index()
        if i is None or self.capture.active:
            return
        if self.overlay:
            self.overlay.show()
            self.var_overlay.set(True)
        self.root.withdraw()
        try:
            self.capture.start_replace(i)
            self._set_status(f"Capturing: left-click to replace position {i + 1}")
        except (RuntimeError, IndexError):
            self.root.deiconify()

    def _delete(self) -> None:
        i = self._selected_index()
        if i is None:
            return
        self.model.delete(i)

    def _move(self, delta: int) -> None:
        i = self._selected_index()
        if i is None:
            return
        if delta < 0:
            self.model.move_up(i)
            new_i = max(0, i - 1)
        else:
            self.model.move_down(i)
            new_i = min(len(self.model) - 1, i + 1)
        if len(self.model) > 0:
            self.tree.selection_set(str(new_i))

    def _on_tree_double_click(self, event) -> None:
        if self.tree.identify_region(event.x, event.y) != "cell":
            return
        if self.tree.identify_column(event.x) != "#4":
            return
        item = self.tree.identify_row(event.y)
        if not item:
            return
        i = int(item)
        self._prompt_extra_delay(i)

    def _prompt_extra_delay(self, i: int) -> None:
        current = self.model[i].extra_delay
        dlg = tk.Toplevel(self.root)
        dlg.title("Extra delay")
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.resizable(False, False)
        ttk.Label(
            dlg, text=f"Extra delay after position {i + 1} (seconds):"
        ).pack(padx=12, pady=(12, 4))
        var = tk.StringVar(value=f"{current:g}")
        ent = ttk.Entry(dlg, textvariable=var, width=12)
        ent.pack(padx=12)
        ent.focus_set()
        ent.select_range(0, "end")
        err = tk.StringVar(value="")
        ttk.Label(dlg, textvariable=err, foreground="#c33").pack(padx=12)

        def ok(_event=None):
            try:
                val = float(var.get())
                self.model.set_extra_delay(i, val)
                dlg.destroy()
            except ValueError as e:
                err.set(str(e) if str(e) else "invalid value")

        ttk.Button(dlg, text="OK", command=ok).pack(pady=(6, 12))
        dlg.bind("<Return>", ok)
        dlg.bind("<Escape>", lambda e: dlg.destroy())

    def _on_overlay_toggle(self) -> None:
        if not self.overlay:
            self.var_overlay.set(False)
            return
        if self.var_overlay.get():
            self.overlay.show()
        else:
            self.overlay.hide()

    def _on_capture_state(self, s: str) -> None:
        if s == "idle":
            self.root.deiconify()
            if self.overlay and not self.var_overlay.get():
                self.overlay.hide()
            self._set_status("Idle")
        self._update_buttons()

    def _click_at(self, x: int, y: int) -> None:
        self._controller.position = (x, y)
        self._controller.click(mouse.Button.left)

    def _start(self) -> None:
        if self._worker and self._worker.state != ClickWorker.IDLE:
            return
        snapshot = self.model.snapshot()
        if not snapshot:
            return
        self._worker = ClickWorker(
            snapshot,
            interval_ms=max(1, int(self.var_interval.get() or 1)),
            loop_delay_ms=max(0, int(self.var_loop.get() or 0)),
            click_fn=self._click_at,
            on_step=lambda s, n: self.root.after(
                0, self._set_status, f"Running step {s}/{n}"
            ),
            on_state=lambda s: self.root.after(0, self._update_buttons),
        )
        self._worker.start()

    def _toggle_pause(self) -> None:
        if not self._worker:
            return
        if self._worker.state == ClickWorker.RUNNING:
            self._worker.pause()
            self._set_status("Paused")
        elif self._worker.state == ClickWorker.PAUSED:
            self._worker.resume()

    def _stop(self) -> None:
        if self._worker:
            self._worker.stop()
            self._worker = None
        self._set_status("Idle")
        self._update_buttons()

    def _on_close(self) -> None:
        try:
            if self._worker:
                self._worker.stop()
            self.capture.stop()
            self.hotkeys.stop()
            if self.overlay:
                self.overlay.destroy()
        finally:
            self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    App().run()
