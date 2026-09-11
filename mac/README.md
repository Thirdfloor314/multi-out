# Multi-Out — macOS port

The same window and the same auto-switch behaviour as the Linux build, on
CoreAudio. Tick the outputs that should play and Multi-Out builds a **Multi-Output
device** (a non-stacked aggregate) over them and makes it the system default;
tick a single output and it becomes the default directly, with no aggregate.

> **Untested on hardware.** Written on Linux, never yet run against real
> CoreAudio. It compiles cleanly and the plist is well-formed, but treat the
> first launch as a smoke test — see *Known limits* below.

## Install

```sh
./mac/install.sh
```

Requires Python 3, PyQt6 and PyObjC:

```sh
pip3 install PyQt6 pyobjc-core pyobjc-framework-Cocoa
```

The installer is user-local: it symlinks `multiout` into `~/.local/bin`, writes
the LaunchAgent to `~/Library/LaunchAgents`, and loads it with `launchctl
bootstrap`. The `--daemon` agent needs neither PyQt6 nor a display.

Remove with `./mac/uninstall.sh`.

## Use

`~/.local/bin/multiout` opens the window; tick outputs and press **Apply**.
*Test tone* plays a short chirp through the current routing; *Stop routing* tears
the Multi-Output device down and hands the default back to a physical output.

Auto-switch runs as a launchd agent, so it works whether or not the window is
open:

```sh
launchctl print gui/$(id -u)/com.user.multiout-autoswitch   # status
tail -f ~/Library/Logs/multiout-autoswitch.log              # what it's doing
```

Untick **Switch to Bluetooth automatically** in the window to turn it off; the
agent reads that setting live, no reload needed.

## How it differs from Linux

| Linux | macOS |
|-------|-------|
| PipeWire `combine-stream` sink | CoreAudio Multi-Output device (`AudioHardwareCreateAggregateDevice`) |
| `pactl` / `bluetoothctl` | `AudioObject*` properties via `ctypes` |
| `pactl subscribe` event stream | polls the device list every 2 s |
| moves sink-inputs between sinks | sets the system default output; apps follow |
| systemd user service | launchd LaunchAgent |
| `~/.local/share/multiout/state.json` | `~/Library/Application Support/Multi-Out/state.json` |
| per-sink volume 0–150 % | per-device volume 0–100 %, where the device allows it |

CoreAudio is reached two ways on purpose: `ctypes` for every property get/set
(deterministic across OS and PyObjC versions), and PyObjC (Foundation) only to
assemble the aggregate-device description dictionary, where a hand-rolled
CFDictionary would be needlessly fragile.

Dropped on macOS: the paired-but-offline **Connect** rows and Bluetooth battery
readout — both came from `bluetoothctl`, which has no macOS equivalent here.

## Known limits

- **`MULTI_OUTPUT_STACKED`** (top of `multiout`) is `False`, the mirrored
  multi-output arrangement. If a combined setup instead *stacks* channels (one
  device gets L/R, the next gets the following pair), flip it to `True`.
- **Volume sliders** appear only for devices that expose a settable
  `VolumeScalar`. Many aggregate and HDMI devices don't — expected, not a bug.
- **Apps that pin a specific output** won't follow the default-device change;
  most apps use the system default and do follow it.
