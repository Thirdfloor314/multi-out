# Multi-Out

Play audio on several outputs at once — Bluetooth, wired and HDMI together — and
hand audio to a Bluetooth device automatically the moment it connects.

Built on PipeWire's `combine-stream` module. Switching outputs never disconnects
a Bluetooth device and never stops playback: the new sink is built and linked
first, live streams are moved onto it, and only then is the old one torn down.

## Features

- **Combine any set of outputs.** Tick the ones that should play; they share one
  virtual sink. Optional latency compensation for devices that drift apart.
- **Automatic Bluetooth switching.** Connect headphones and audio follows them,
  with no window to open. If a multi-output group is already running, the new
  device joins it rather than replacing routing you set up deliberately.
- **Per-output volume**, and battery level for Bluetooth devices that report it.
- **Connect paired devices** that aren't currently online, from the same window.
- **Gapless.** Closing the window leaves routing running; reopening it adopts
  whatever is already playing instead of rebuilding it.

## Install

```sh
git clone git@github.com:Thirdfloor314/multiout.git
cd multiout
./linux/install.sh
```

Requires PipeWire, `pactl`, `bluetoothctl`, Python 3 and PyQt6. The installer is
user-local — it needs no root and writes only to `~/.local` and
`~/.config/systemd/user`.

## Use

`multiout` opens the window. Tick outputs, press **Apply**.

Auto-switch runs as a systemd user service, so it works whether or not the
window is open:

```sh
systemctl --user status multiout-autoswitch
journalctl --user -u multiout-autoswitch -f
```

Untick **Switch to Bluetooth automatically** in the window to turn it off; the
service reads that setting live, no restart needed.

## How it works

`multiout --daemon` watches `pactl subscribe` for topology changes, debounced by
0.8 s so a headset registering its card, sink and ports in quick succession is
handled once rather than three times. The watcher is *edge-triggered*: it reacts
to a device arriving or leaving, never to it merely being present, so picking an
output by hand is not undone while the device stays connected.

Combining is done by a standalone `pipewire -c` process hosting a
`combine-stream` module, one per routing configuration. The daemon and the GUI
share the same routing code path, and only one of them ever owns switching — the
window defers to the service whenever the service is running.

State lives in `~/.local/share/multiout/state.json`.

## Windows

There is a Windows port in [`windows/`](windows/), with the same window and the
same auto-switch behaviour. It is **untested** — written on Linux, never yet run
on Windows — so start with `python multiout.py --selftest`, which reports what it
detects without changing anything.

It differs in one way that matters: Windows has no combine sink, so playing to
several outputs at once is done by loopback-capturing the primary and mirroring
it to the extras, which trail by roughly 30-80 ms. See
[windows/README.md](windows/README.md).

## macOS

There is a macOS port in [`mac/`](mac/), with the same window and the same
auto-switch behaviour. It builds a native CoreAudio **Multi-Output device** over
the ticked outputs and makes it the system default, so — unlike Windows — there
is no mirroring lag. Install with `./mac/install.sh` (needs Python 3, PyQt6 and
PyObjC); the auto-switch agent runs under launchd.

It too is **untested** — written on Linux, never yet run against real CoreAudio.
See [mac/README.md](mac/README.md).

## Layout

```
linux/multiout          the Linux application (GUI + --daemon)
linux/install.sh        user-local installer
packaging/              .desktop entry, systemd user unit, launchd agent
windows/multiout.py     the Windows port (GUI + --daemon + --selftest)
windows/install.ps1     Start Menu shortcut and logon task
mac/multiout            the macOS port (GUI + --daemon)
mac/install.sh          user-local installer (launchd agent)
```

## Licence

MIT
