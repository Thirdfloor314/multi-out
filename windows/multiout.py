#!/usr/bin/env python3
"""
Multi-Out for Windows — route audio to several outputs at once, and hand audio
to a Bluetooth device automatically the moment it connects.

Windows has no equivalent of PipeWire's combine sink, so "several outputs at
once" is done by loopback-capturing whatever the primary output is playing and
re-rendering it to the extra devices. The primary plays natively with no added
latency; the mirrored outputs trail it by roughly 30-80 ms.

  multiout.py              open the window
  multiout.py --daemon     headless auto-switch, no window
  multiout.py --selftest   report what it detects, change nothing
"""
from __future__ import annotations

import ctypes
import json
import os
import platform
import sys
import threading
import time
from dataclasses import dataclass, field

APPDIR = os.path.join(os.environ.get("LOCALAPPDATA",
                                     os.path.expanduser("~")), "multiout")
STATE = os.path.join(APPDIR, "state.json")

# How often the daemon re-enumerates endpoints. Windows exposes a COM callback
# for this (IMMNotificationClient), but a poll is far less machinery to get
# wrong and enumerating endpoints is cheap.
POLL = 1.5


# ---------------------------------------------------------------- state file

def load_state() -> dict:
    try:
        with open(STATE, encoding="utf-8") as fh:
            d = json.load(fh)
        if isinstance(d, dict):
            return d
    except (OSError, ValueError):
        pass
    return {}


def save_state(**changes) -> None:
    """Merge keys into the state file. The window and the daemon both write
    here, so this must never rewrite the whole document from one side's view."""
    d = load_state()
    d.update(changes)
    try:
        os.makedirs(APPDIR, exist_ok=True)
        tmp = f"{STATE}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(d, fh)
        os.replace(tmp, STATE)
    except OSError:
        pass


# ---------------------------------------------------------------- COM plumbing

_CO_INITIALISED = threading.local()


def com_init() -> None:
    """CoInitialize this thread once. Every thread touching COM needs it."""
    if getattr(_CO_INITIALISED, "done", False):
        return
    try:
        import comtypes
        comtypes.CoInitialize()
    except Exception:
        pass
    _CO_INITIALISED.done = True


def _policy_config():
    """The undocumented interface Windows itself uses to set the default
    endpoint. There is no public API for this; every tool that switches audio
    devices from userspace goes through here."""
    from ctypes import HRESULT
    from ctypes.wintypes import DWORD, LPCWSTR

    import comtypes
    from comtypes import COMMETHOD, GUID, IUnknown

    class IPolicyConfig(IUnknown):
        _iid_ = GUID("{f8679f50-850a-410c-9c3e-360c4b7ea9d5}")
        # Only SetDefaultEndpoint is called, but every earlier method must be
        # declared so it lands in the right vtable slot.
        _methods_ = [
            COMMETHOD([], HRESULT, "GetMixFormat"),
            COMMETHOD([], HRESULT, "GetDeviceFormat"),
            COMMETHOD([], HRESULT, "ResetDeviceFormat"),
            COMMETHOD([], HRESULT, "SetDeviceFormat"),
            COMMETHOD([], HRESULT, "GetProcessingPeriod"),
            COMMETHOD([], HRESULT, "SetProcessingPeriod"),
            COMMETHOD([], HRESULT, "GetShareMode"),
            COMMETHOD([], HRESULT, "SetShareMode"),
            COMMETHOD([], HRESULT, "GetPropertyValue"),
            COMMETHOD([], HRESULT, "SetPropertyValue"),
            COMMETHOD([], HRESULT, "SetDefaultEndpoint",
                      (["in"], LPCWSTR, "device_id"),
                      (["in"], DWORD, "role")),
            COMMETHOD([], HRESULT, "SetEndpointVisibility"),
        ]

    return comtypes.CoCreateInstance(
        GUID("{870af99c-171d-4f9e-af0d-e63df40c2bc9}"),
        IPolicyConfig, comtypes.CLSCTX_ALL)


def set_default(device_id: str) -> bool:
    """Make `device_id` the default output for every role."""
    com_init()
    try:
        cfg = _policy_config()
    except Exception:
        return False
    ok = False
    for role in (0, 1, 2):        # eConsole, eMultimedia, eCommunications
        try:
            cfg.SetDefaultEndpoint(device_id, role)
            ok = True
        except Exception:
            pass
    return ok


# ---------------------------------------------------------------- data model

@dataclass
class Device:
    id: str
    name: str
    kind: str            # bluetooth | hdmi | speakers | headphones | other
    signal: str = ""     # how `kind` was decided, for --selftest


@dataclass
class Inventory:
    devices: list[Device] = field(default_factory=list)
    default_id: str = ""


BT_HINTS = ("bluetooth", "hands-free", "handsfree", "stereo", "airpods",
            "wh-", "wf-", "buds", "jbl", "soundcore", "headset")


def _enumerator_name(dev) -> str:
    """PKEY_Device_EnumeratorName — "BTHENUM"/"BTHLE" for Bluetooth endpoints.
    Wrapped defensively: pycaw's property plumbing differs between versions."""
    try:
        from pycaw.api.mmdeviceapi.depend import PROPERTYKEY
        from comtypes import GUID
        store = dev.OpenPropertyStore(0)          # STGM_READ
        key = PROPERTYKEY()
        key.fmtid = GUID("{a45c254e-df1c-4efd-8020-67d146a850e0}")
        key.pid = 24
        val = store.GetValue(ctypes.byref(key))
        return str(val.GetValue() or "")
    except Exception:
        return ""


def classify(name: str, enumerator: str, form_factor: int | None) -> tuple[str, str]:
    """Return (kind, signal) — signal records which clue decided it, so
    --selftest can show why a device was or was not called Bluetooth."""
    enum_up = (enumerator or "").upper()
    if enum_up.startswith("BTH"):
        return "bluetooth", f"enumerator={enumerator}"

    low = name.lower()
    if form_factor == 9 or "hdmi" in low or "displayport" in low:
        return "hdmi", "form-factor/name"
    if any(h in low for h in BT_HINTS):
        return "bluetooth", "name-hint"
    if form_factor in (3, 5):
        return "headphones", "form-factor"
    if form_factor == 1:
        return "speakers", "form-factor"
    return "other", "default"


def scan() -> Inventory:
    """Enumerate active render endpoints."""
    com_init()
    inv = Inventory()
    try:
        from pycaw.utils import AudioUtilities
    except Exception:
        return inv

    try:
        default = AudioUtilities.GetSpeakers()
        inv.default_id = default.GetId()
    except Exception:
        pass

    try:
        raw = AudioUtilities.GetAllDevices()
    except Exception:
        return inv

    for d in raw:
        try:
            if getattr(d, "state", None) is not None and str(d.state) != "AudioDeviceState.Active":
                continue
            dev_id = d.id
            name = d.FriendlyName or dev_id
        except Exception:
            continue
        if not dev_id:
            continue

        enumerator, form = "", None
        try:
            enumerator = _enumerator_name(d._dev)
        except Exception:
            pass
        try:
            props = getattr(d, "properties", {}) or {}
            for k, v in props.items():
                if "1da5d803" in str(k).lower():      # PKEY_AudioEndpoint_FormFactor
                    form = int(v)
                    break
        except Exception:
            pass

        kind, signal = classify(name, enumerator, form)
        inv.devices.append(Device(dev_id, name, kind, signal))

    order = {"bluetooth": 0, "headphones": 1, "speakers": 2, "hdmi": 3, "other": 4}
    inv.devices.sort(key=lambda d: (order.get(d.kind, 9), d.name.lower()))
    return inv


# ---------------------------------------------------------------- mirroring

class Mirror(threading.Thread):
    """Loopback-capture the primary output and re-render it to the extras.

    This is what stands in for PipeWire's combine sink. The primary device is
    untouched and plays natively; the extras are fed a copy, so they trail it
    slightly. Stopping the thread leaves the primary playing.
    """

    def __init__(self, primary: str, extras: list[str]) -> None:
        super().__init__(daemon=True)
        self.primary = primary
        self.extras = list(extras)
        self.error = ""
        self.live: list[str] = []
        self._stop = threading.Event()
        self._ready = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    # -- device matching ----------------------------------------------------
    @staticmethod
    def _match(pa, name: str, want_input: bool):
        """PortAudio indexes devices by name, Core Audio by id, so the two
        halves are joined on the friendly name."""
        best, best_len = None, -1
        for i in range(pa.get_device_count()):
            try:
                info = pa.get_device_info_by_index(i)
            except Exception:
                continue
            if want_input and not info.get("maxInputChannels"):
                continue
            if not want_input and not info.get("maxOutputChannels"):
                continue
            if want_input and not info.get("isLoopbackDevice"):
                continue
            dev_name = str(info.get("name", ""))
            # Windows truncates endpoint names differently between the two
            # APIs, so match on the longest common prefix rather than equality.
            trimmed = name[:30]
            if trimmed and trimmed.lower() in dev_name.lower():
                if len(dev_name) > best_len:
                    best, best_len = info, len(dev_name)
        return best

    def run(self) -> None:
        com_init()
        try:
            import pyaudiowpatch as pyaudio
        except ImportError:
            self.error = ("PyAudioWPatch is not installed — "
                          "pip install PyAudioWPatch")
            self._ready.set()
            return

        pa = None
        try:
            pa = pyaudio.PyAudio()
            src_info = self._match(pa, self.primary, want_input=True)
            if src_info is None:
                self.error = f"no loopback capture device for {self.primary!r}"
                self._ready.set()
                return

            rate = int(src_info.get("defaultSampleRate") or 48000)
            channels = min(2, int(src_info.get("maxInputChannels") or 2)) or 2
            chunk = 512

            fmt = None
            src = None
            for candidate in (pyaudio.paInt16, pyaudio.paFloat32):
                try:
                    src = pa.open(format=candidate, channels=channels, rate=rate,
                                  input=True, frames_per_buffer=chunk,
                                  input_device_index=int(src_info["index"]))
                    fmt = candidate
                    break
                except Exception as exc:
                    self.error = f"loopback open failed: {exc}"
            if src is None:
                self._ready.set()
                return

            outs = []
            for name in self.extras:
                info = self._match(pa, name, want_input=False)
                if info is None:
                    continue
                try:
                    outs.append(pa.open(
                        format=fmt, channels=channels, rate=rate, output=True,
                        frames_per_buffer=chunk,
                        output_device_index=int(info["index"])))
                    self.live.append(name)
                except Exception as exc:
                    self.error = f"{name}: {exc}"

            if not outs:
                self.error = self.error or "no usable mirror outputs"
                self._ready.set()
                return

            self.error = ""
            self._ready.set()
            while not self._stop.is_set():
                try:
                    data = src.read(chunk, exception_on_overflow=False)
                except Exception:
                    break
                for out in outs:
                    try:
                        out.write(data, exception_on_underflow=False)
                    except Exception:
                        pass        # one bad output must not stop the rest
        except Exception as exc:
            self.error = str(exc)
        finally:
            self._ready.set()
            if pa is not None:
                try:
                    pa.terminate()
                except Exception:
                    pass

    def wait_ready(self, timeout: float = 6.0) -> bool:
        self._ready.wait(timeout)
        return not self.error


class Router:
    """Owns the default device and the mirror thread as one unit, so callers
    say what should be playing and this works out the rest."""

    def __init__(self) -> None:
        self.mirror: Mirror | None = None

    def stop_mirror(self) -> None:
        if self.mirror is not None:
            self.mirror.stop()
            self.mirror.join(timeout=2.0)
            self.mirror = None

    @property
    def mirroring(self) -> bool:
        return self.mirror is not None and self.mirror.is_alive()

    def activate(self, targets: list[Device]) -> str:
        """Play on `targets`. The first becomes the real default; any others
        are fed by the mirror. Returns "" on success, else a message."""
        if not targets:
            return "nothing to route to"
        self.stop_mirror()

        primary = targets[0]
        if not set_default(primary.id):
            return f"could not make {primary.name} the default device"

        save_state(selected=[d.id for d in targets])
        extras = [d.name for d in targets[1:]]
        if not extras:
            return ""

        # Give Windows a moment to settle the new default before capturing it.
        time.sleep(0.4)
        self.mirror = Mirror(primary.name, extras)
        self.mirror.start()
        if not self.mirror.wait_ready():
            msg = self.mirror.error or "mirroring failed"
            self.stop_mirror()
            return msg
        return ""


# ---------------------------------------------------------------- auto-switch

class AutoSwitch:
    """Follows Bluetooth endpoints appearing and disappearing.

    Edge-triggered on purpose: it acts on a device *arriving* or *leaving*, not
    on it merely being present, so it never fights a choice made by hand.
    """

    def __init__(self, router: Router) -> None:
        self.router = router
        self.known: set[str] = set()
        self.primed = False

    @staticmethod
    def _bt(inv: Inventory) -> set[str]:
        return {d.id for d in inv.devices if d.kind == "bluetooth"}

    def prime(self, inv: Inventory) -> None:
        self.known = self._bt(inv)
        self.primed = True

    def reconcile(self, inv: Inventory) -> str:
        current = self._bt(inv)
        if not self.primed:
            self.prime(inv)
            return ""
        arrived = sorted(current - self.known)
        departed = self.known - current
        self.known = current

        if arrived:
            return self._on_connect(arrived, inv)
        if departed:
            return self._on_disconnect(departed, inv)
        return ""

    def _on_connect(self, arrived: list[str], inv: Inventory) -> str:
        by_id = {d.id: d for d in inv.devices}
        new = by_id.get(arrived[0])
        if new is None:
            return ""

        if self.router.mirroring:
            # A multi-output group is running: the new device joins it rather
            # than silently replacing routing that was set up deliberately.
            keep = [by_id[i] for i in load_state().get("selected", [])
                    if i in by_id]
            targets = [new] + [d for d in keep if d.id != new.id]
            verb = "added to the group"
        else:
            targets = [new]
            verb = "now playing here"

        err = self.router.activate(targets)
        if err:
            return f"auto-switch: {err}"
        return f"{new.name} connected — {verb}."

    def _on_disconnect(self, departed: set[str], inv: Inventory) -> str:
        by_id = {d.id: d for d in inv.devices}
        keep = [by_id[i] for i in load_state().get("selected", []) if i in by_id]
        if not keep:
            fallback = next((d for d in inv.devices
                             if d.kind in ("speakers", "headphones", "other")),
                            None)
            if fallback is None:
                return ""
            keep = [fallback]
        elif inv.default_id not in departed and inv.default_id in by_id \
                and not self.router.mirroring:
            # Windows already moved the default somewhere valid and there is no
            # group to rebuild; just forget the device that left.
            save_state(selected=[d.id for d in keep])
            return ""

        err = self.router.activate(keep)
        if err:
            return ""
        back = keep[0].name if len(keep) == 1 else f"the {len(keep)} remaining outputs"
        return f"Bluetooth disconnected — audio moved back to {back}."


# ---------------------------------------------------------------- daemon

def daemon() -> int:
    """Headless auto-switch: no window. Polls the endpoint list and hands audio
    to a Bluetooth device as soon as one shows up."""
    com_init()
    router = Router()
    auto = AutoSwitch(router)
    auto.prime(scan())
    print("multiout: auto-switch daemon watching for Bluetooth outputs",
          flush=True)
    try:
        while True:
            time.sleep(POLL)
            st = load_state()
            inv = scan()
            if not inv.devices:
                continue
            if st.get("autoswitch", True):
                msg = auto.reconcile(inv)
                if msg:
                    print(f"multiout: {msg}", flush=True)
            else:
                auto.prime(inv)
    except KeyboardInterrupt:
        pass
    finally:
        router.stop_mirror()
    return 0


# ---------------------------------------------------------------- self-test

def selftest() -> int:
    """Report what this machine looks like without changing anything."""
    print("Multi-Out self-test — nothing below changes your audio settings.\n")
    print(f"Python   : {sys.version.split()[0]} ({platform.architecture()[0]})")
    print(f"Windows  : {platform.platform()}")
    print(f"State    : {STATE}")

    print("\nDependencies")
    ok = True
    for mod, hint in (("comtypes", "pip install comtypes"),
                      ("pycaw", "pip install pycaw"),
                      ("pyaudiowpatch", "pip install PyAudioWPatch"),
                      ("PyQt6", "pip install PyQt6")):
        try:
            __import__(mod)
            print(f"  [ok]      {mod}")
        except ImportError:
            print(f"  [MISSING] {mod:<14} {hint}")
            ok = ok and mod in ("pyaudiowpatch", "PyQt6")

    print("\nDefault-device switching")
    try:
        com_init()
        _policy_config()
        print("  [ok]      IPolicyConfig available")
    except Exception as exc:
        ok = False
        print(f"  [FAILED]  IPolicyConfig: {exc}")

    print("\nOutput devices")
    inv = scan()
    if not inv.devices:
        ok = False
        print("  none found — endpoint enumeration failed")
    for d in inv.devices:
        mark = "*" if d.id == inv.default_id else " "
        print(f" {mark} {d.kind:<10} {d.name}")
        print(f"     detected by: {d.signal}")
    print("\n  (* = current default. If a Bluetooth device is connected and is")
    print("   not listed as 'bluetooth' above, tell me what it shows instead.)")

    print("\nLoopback capture (needed for playing to several outputs at once)")
    try:
        import pyaudiowpatch as pyaudio
        pa = pyaudio.PyAudio()
        found = 0
        for i in range(pa.get_device_count()):
            info = pa.get_device_info_by_index(i)
            if info.get("isLoopbackDevice"):
                found += 1
                print(f"  [ok]      {info['name']}")
        if not found:
            print("  [none]    no loopback devices exposed")
        pa.terminate()
    except ImportError:
        print("  [skipped] PyAudioWPatch not installed")
    except Exception as exc:
        print(f"  [FAILED]  {exc}")

    print("\nVerdict:", "looks usable" if ok else "something above needs fixing")
    return 0 if ok else 1


# ---------------------------------------------------------------- UI

STYLE = """
QMainWindow, QWidget { background: palette(window); }
#head { background: palette(base); border-bottom: 1px solid palette(mid); }
#foot { background: palette(base); border-top: 1px solid palette(mid); }
#row  { background: palette(base); border: 1px solid palette(mid);
        border-radius: 9px; }
#row:hover { border-color: palette(highlight); }
#dim  { color: palette(placeholder-text); }
#badge { color: palette(placeholder-text); border: 1px solid palette(mid);
         border-radius: 7px; padding: 1px 7px; font-size: 10px; }
QPushButton { padding: 6px 15px; border-radius: 7px; }
#primary { background: palette(highlight); color: palette(highlighted-text);
           border: none; font-weight: 600; }
#primary:disabled { background: palette(mid); color: palette(placeholder-text); }
#ghost { background: transparent; border: 1px solid palette(mid); }
#ghost:hover { border-color: palette(highlight); }
"""

BADGE = {"bluetooth": "Bluetooth", "hdmi": "HDMI", "speakers": "Speakers",
         "headphones": "Headphones", "other": "Output"}


def run_gui() -> int:
    from PyQt6.QtCore import Qt, QTimer
    from PyQt6.QtGui import QFont
    from PyQt6.QtWidgets import (
        QApplication, QCheckBox, QFrame, QHBoxLayout, QLabel, QMainWindow,
        QMessageBox, QPushButton, QScrollArea, QVBoxLayout, QWidget,
    )

    class DeviceRow(QFrame):
        def __init__(self, dev: Device, checked: bool, is_default: bool) -> None:
            super().__init__()
            self.dev = dev
            self.setObjectName("row")
            lay = QHBoxLayout(self)
            lay.setContentsMargins(12, 9, 12, 9)
            lay.setSpacing(10)

            self.check = QCheckBox()
            self.check.setChecked(checked)
            lay.addWidget(self.check)

            title = QLabel(dev.name)
            f = title.font()
            f.setPointSizeF(f.pointSizeF() + 0.5)
            f.setWeight(QFont.Weight.DemiBold)
            title.setFont(f)
            lay.addWidget(title)

            badge = QLabel(BADGE.get(dev.kind, dev.kind))
            badge.setObjectName("badge")
            lay.addWidget(badge)

            if is_default:
                now = QLabel("playing")
                now.setObjectName("dim")
                lay.addWidget(now)
            lay.addStretch(1)

    class MainWindow(QMainWindow):
        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle("Multi-Out")
            self.resize(560, 560)
            self.router = Router()
            self.auto_engine = AutoSwitch(self.router)
            d = load_state()
            self.selected: list[str] = list(d.get("selected", []))
            self.autoswitch = bool(d.get("autoswitch", True))
            self.inv = Inventory()
            self._busy = False

            root = QWidget()
            self.setCentralWidget(root)
            outer = QVBoxLayout(root)
            outer.setContentsMargins(0, 0, 0, 0)
            outer.setSpacing(0)

            head = QWidget()
            head.setObjectName("head")
            hl = QVBoxLayout(head)
            hl.setContentsMargins(18, 16, 18, 14)
            hl.setSpacing(3)
            t = QLabel("Multi-Out")
            tf = t.font()
            tf.setPointSizeF(tf.pointSizeF() + 5)
            tf.setWeight(QFont.Weight.Bold)
            t.setFont(tf)
            hl.addWidget(t)
            sub = QLabel("Tick every output that should play. The first ticked "
                         "device plays directly; the rest are mirrored to and "
                         "trail it slightly.")
            sub.setObjectName("dim")
            sub.setWordWrap(True)
            hl.addWidget(sub)
            outer.addWidget(head)

            self.scroll = QScrollArea()
            self.scroll.setWidgetResizable(True)
            self.scroll.setFrameShape(QFrame.Shape.NoFrame)
            self.host = QWidget()
            self.list = QVBoxLayout(self.host)
            self.list.setContentsMargins(14, 12, 14, 12)
            self.list.setSpacing(8)
            self.list.addStretch(1)
            self.scroll.setWidget(self.host)
            outer.addWidget(self.scroll, 1)

            foot = QWidget()
            foot.setObjectName("foot")
            fl = QVBoxLayout(foot)
            fl.setContentsMargins(18, 12, 18, 14)
            fl.setSpacing(10)

            self.auto = QCheckBox("Switch to Bluetooth automatically when a "
                                  "device connects")
            self.auto.setChecked(self.autoswitch)
            self.auto.stateChanged.connect(self._on_auto)
            fl.addWidget(self.auto)

            self.status = QLabel("")
            self.status.setObjectName("dim")
            self.status.setWordWrap(True)
            fl.addWidget(self.status)

            btns = QHBoxLayout()
            btns.addStretch(1)
            self.btn_stop = QPushButton("Stop mirroring")
            self.btn_stop.setObjectName("ghost")
            self.btn_stop.clicked.connect(self._stop)
            btns.addWidget(self.btn_stop)
            self.btn_apply = QPushButton("Apply")
            self.btn_apply.setObjectName("primary")
            self.btn_apply.setDefault(True)
            self.btn_apply.clicked.connect(self.apply)
            btns.addWidget(self.btn_apply)
            fl.addLayout(btns)
            outer.addWidget(foot)

            self.setStyleSheet(STYLE)

            self.timer = QTimer(self)
            self.timer.setInterval(int(POLL * 1000))
            self.timer.timeout.connect(self.refresh)
            self.timer.start()
            self.refresh()

        def refresh(self) -> None:
            if self._busy:
                return
            self.inv = scan()
            while self.list.count() > 1:
                item = self.list.takeAt(0)
                w = item.widget()
                if w:
                    w.deleteLater()
            for dev in self.inv.devices:
                row = DeviceRow(dev, dev.id in self.selected,
                                dev.id == self.inv.default_id)
                self.list.insertWidget(self.list.count() - 1, row)

            live = {d.id for d in self.inv.devices}
            self.selected = [i for i in self.selected if i in live]

            if self.autoswitch:
                self._busy = True
                try:
                    msg = self.auto_engine.reconcile(self.inv)
                finally:
                    self._busy = False
                if msg:
                    self.selected = list(load_state().get("selected", []))
                    self.status.setText(msg)
                    return
            self._status()

        def _status(self) -> None:
            n = len(self.selected)
            if n == 0:
                msg = "No outputs ticked."
            elif n == 1:
                msg = "1 output ticked — audio plays there directly."
            else:
                msg = (f"{n} outputs ticked — the first plays directly, "
                       f"{n - 1} mirrored.")
            if self.router.mirroring:
                msg += "  Mirroring is active."
            if self.autoswitch:
                msg += "  Auto-switch on (only while this window is open)."
            self.status.setText(msg)
            self.btn_stop.setEnabled(self.router.mirroring)

        def _ticked(self) -> list[Device]:
            by_id = {d.id: d for d in self.inv.devices}
            ticked = [r.dev for r in self.host.findChildren(DeviceRow)
                      if r.check.isChecked()]
            return [by_id[d.id] for d in ticked if d.id in by_id]

        def apply(self) -> None:
            targets = self._ticked()
            if not targets:
                QMessageBox.information(self, "Nothing selected",
                                        "Tick at least one output first.")
                return
            self._busy = True
            self.btn_apply.setEnabled(False)
            self.status.setText("Applying…")
            QApplication.processEvents()
            try:
                err = self.router.activate(targets)
            finally:
                self._busy = False
                self.btn_apply.setEnabled(True)
            self.selected = [d.id for d in targets]
            save_state(selected=self.selected, autoswitch=self.autoswitch)
            self.auto_engine.prime(self.inv)
            if err:
                QMessageBox.warning(self, "Could not route audio", err)
            self._status()

        def _stop(self) -> None:
            self.router.stop_mirror()
            self._status()

        def _on_auto(self) -> None:
            self.autoswitch = self.auto.isChecked()
            save_state(autoswitch=self.autoswitch)
            if self.autoswitch:
                self.auto_engine.prime(self.inv)
            self._status()

        def closeEvent(self, event):    # noqa: N802 (Qt naming)
            self.router.stop_mirror()
            event.accept()

    com_init()
    app = QApplication(sys.argv)
    app.setApplicationName("Multi-Out")
    win = MainWindow()
    win.show()
    return app.exec()


def main() -> int:
    if os.name != "nt":
        print("multiout: this is the Windows build; on Linux use "
              "linux/multiout", file=sys.stderr)
        return 1
    args = sys.argv[1:]
    if "--selftest" in args:
        return selftest()
    if "--daemon" in args:
        return daemon()
    return run_gui()


if __name__ == "__main__":
    sys.exit(main())
