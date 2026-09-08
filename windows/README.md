# Multi-Out for Windows

Same idea as the Linux build, different machinery underneath.

> **Untested.** This port was written on Linux and has never been run on
> Windows. The logic is unit-tested under mocks and the COM interfaces follow
> the documented shapes, but treat the first run as a trial. Start with
> `--selftest`, which changes nothing.

## Install

```powershell
python multiout.py --selftest        # look before you leap
powershell -ExecutionPolicy Bypass -File install.ps1
```

Needs Python 3, plus `comtypes`, `pycaw`, `PyQt6` and `PyAudioWPatch`, which the
installer pulls in. No admin rights required.

## How it differs from Linux

| | Linux | Windows |
|---|---|---|
| Combining outputs | PipeWire `combine-stream`, sample-accurate | WASAPI loopback mirror, extras trail by ~30-80 ms |
| Default switching | `pactl set-default-sink` | `IPolicyConfig::SetDefaultEndpoint` (undocumented, but what every audio switcher uses) |
| Change detection | `pactl subscribe`, event-driven | polls endpoints every 1.5 s |
| Background service | systemd user unit | Scheduled Task at logon |

The mirroring difference is the one that matters. The **first** ticked device is
the real default and plays with no added latency; every other ticked device is
fed a copy captured from it. That is fine for music filling a room, and wrong
for anything where lip-sync matters.

If you want sample-accurate combining, install
[VB-Audio Voicemeeter](https://vb-audio.com/Voicemeeter/) and make it the
default device — Multi-Out's auto-switch still works alongside it.

## Bluetooth detection

Windows has no single reliable "is this Bluetooth" flag on an audio endpoint, so
this checks, in order: the device's enumerator name (`BTHENUM`/`BTHLE`), the
endpoint form factor, then the device name. `--selftest` prints which clue fired
for each device — if something is misfiled, that output says why.
