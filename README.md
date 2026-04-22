# MajsoulAdder

A tiny mouse-click looper with a transparent on-screen overlay. Record a sequence of screen positions, then replay the clicks on a loop with configurable timing. Windows only (uses Win32 APIs for the click-through overlay).

## Requirements

- Windows
- Python 3.12+
- [uv](https://docs.astral.sh/uv/)

## Run

```
uv run python MajsoulAdder.py
```

## Tests

```
uv run pytest
```

## Usage

1. Click **Add position** (or press `F10`), then left-click anywhere on screen to capture a position. Press `Esc` or right-click to end the capture.
2. Repeat to build a sequence. Select a row and use **Re-record**, **Delete**, **Move up/down**, or **Clear all** to edit.
3. Double-click the *Extra delay (s)* cell to add a per-step pause.
4. Tick **Show overlay** to draw numbered circles at each position.
5. Press **Start** (`F7`) to loop. **Pause/Resume** is `F8`, **Stop** is `F9`.

### Settings

- **Interval (ms)** — delay between clicks within one pass of the sequence.
- **Loop delay (ms)** — delay between passes.
- **Extra delay (s)** — per-position delay added after a click.

### Hotkeys

| Key | Action |
| --- | --- |
| F7 | Start |
| F8 | Pause / Resume |
| F9 | Stop |
| F10 | Add position |
| Esc | End capture |
