#!/usr/bin/env python3
"""
PS-3208 Wireless CO₂ Sensor — Dual Transport (BLE + USB)
==========================================================
Supports the PASCO PS-3208 via BLE (official pasco library) or USB serial.

Channels: CO₂ (ppm), Temperature (°C), Humidity (%), Pressure (kPa)

Lifecycle:  Detect → Connect → Stream → Disconnect

Usage:
  python ps3208.py                              # auto-detect transport
  python ps3208.py --ble                         # force BLE
  python ps3208.py --port COM3                   # force USB on COM3
  python ps3208.py --ble --id 123-456            # BLE by sensor ID
  python ps3208.py --duration 60 --csv           # 60s to CSV
  python ps3208.py --json                        # JSON output
  python ps3208.py --list                        # scan for sensors + ports

Requirements (on Raspberry Pi):
  BLE:  pip install pasco        (official library)
  USB:  pip install pyserial     (already in requirements.txt)
"""

import argparse
import csv
import json
import signal
import sys
import time
from datetime import datetime
from typing import Optional, Union

# ---------------------------------------------------------------------------
# Optional imports — one or both must be available
# ---------------------------------------------------------------------------
_pasco_available = False
_pyserial_available = False

try:
    from pasco.pasco_ble_device import PASCOBLEDevice
    _pasco_available = True
except ImportError:
    pass

try:
    import serial
    import serial.tools.list_ports
    _pyserial_available = True
except ImportError:
    pass

if not _pasco_available and not _pyserial_available:
    sys.exit(
        "ERROR: Neither 'pasco' nor 'pyserial' is installed.\n"
        "Install at least one:\n"
        "  pip install pasco     # for BLE\n"
        "  pip install pyserial  # for USB"
    )

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SENSOR_NAME = "PS-3208 Wireless CO₂ Sensor"
CHANNELS = ["co2_ppm", "temperature_c", "humidity_pct", "pressure_kpa"]
BAUD_RATE = 115200

# ---------------------------------------------------------------------------
# Globals
# ---------------------------------------------------------------------------
device: Union["PASCOBLEDevice", "serial.Serial", None] = None
transport: str = ""  # "ble" or "usb"
running = True


def handle_shutdown(signum: int, frame) -> None:
    global running
    running = False
    print("\n[SHUTDOWN] Signal received, stopping...", file=sys.stderr)


signal.signal(signal.SIGINT, handle_shutdown)
signal.signal(signal.SIGTERM, handle_shutdown)


# ===========================================================================
#  BLE Transport (official pasco library)
# ===========================================================================

def connect_ble(sensor_id: Optional[str] = None) -> PASCOBLEDevice:
    """Discover and connect to PS-3208 via BLE."""
    if not _pasco_available:
        raise ConnectionError("BLE not available — install 'pasco' library.")

    print(f"[BLE] Scanning for {SENSOR_NAME}...", file=sys.stderr)
    sensor = PASCOBLEDevice()

    try:
        if sensor_id:
            print(f"[BLE] Connecting by ID: {sensor_id}", file=sys.stderr)
            sensor.connect_by_id(sensor_id)
        else:
            found = sensor.scan("CO2")
            if not found:
                # Try broader scan
                found = sensor.scan()
                found = [d for d in found if hasattr(d, "name") and
                         any(kw in (d.name or "") for kw in ("CO2", "PS-3208", "PS3208"))]
            if not found:
                raise ConnectionError("No PS-3208 found via BLE. Is it powered on (blinking red)?")
            print(f"[BLE] Found: {found[0].name}", file=sys.stderr)
            sensor.connect(found[0])
    except Exception as e:
        raise ConnectionError(f"BLE connection failed: {e}") from e

    time.sleep(1.0)
    measurements = sensor.get_measurement_list()
    print(f"[BLE] Connected — {len(measurements)} channel(s): {measurements}",
          file=sys.stderr)
    return sensor


def read_ble(sensor: PASCOBLEDevice) -> Optional[dict]:
    """Read one sample from BLE sensor. Returns dict or None."""
    try:
        if not sensor.is_connected():
            return None
        return sensor.read_data_list(sensor.get_measurement_list())
    except Exception as e:
        print(f"[BLE] Read error: {e}", file=sys.stderr)
        return None


def disconnect_ble(sensor: PASCOBLEDevice) -> None:
    """Disconnect BLE sensor."""
    try:
        sensor.disconnect()
    except Exception:
        pass


# ===========================================================================
#  USB Transport (pyserial)
# ===========================================================================

def list_usb_ports() -> list[dict]:
    """Return available serial ports."""
    ports = []
    for p in serial.tools.list_ports.comports():
        ports.append({
            "device": p.device,
            "description": p.description,
            "hwid": p.hwid,
            "vid": f"0x{p.vid:04X}" if p.vid else None,
            "pid": f"0x{p.pid:04X}" if p.pid else None,
        })
    return ports


def find_usb_co2_port() -> str:
    """Auto-detect PS-3208 USB serial port."""
    all_ports = list_usb_ports()
    if not all_ports:
        raise ConnectionError("No USB serial ports found.")

    candidates = []

    # Match by PASCO VID or description
    for p in all_ports:
        desc = (p["description"] + (p.get("hwid") or "")).upper()
        if any(kw in desc for kw in ("PASCO", "PS-3208", "PS3208", "CO2")):
            candidates.append(p)

    # Single /dev/ttyACM* or /dev/ttyUSB*
    if not candidates:
        acm = [p for p in all_ports if "ttyACM" in p["device"] or "ttyUSB" in p["device"]]
        if len(acm) == 1:
            candidates = acm

    if not candidates:
        print("[USB] Available ports:", file=sys.stderr)
        for p in all_ports:
            print(f"       {p['device']} — {p['description']}", file=sys.stderr)
        raise ConnectionError("PS-3208 not auto-detected on USB. Use --port <DEVICE>.")

    if len(candidates) > 1:
        print(f"[USB] Multiple candidates, using {candidates[0]['device']}", file=sys.stderr)

    return candidates[0]["device"]


def connect_usb(port: Optional[str] = None) -> serial.Serial:
    """Open USB serial connection to PS-3208."""
    if not _pyserial_available:
        raise ConnectionError("USB not available — install 'pyserial'.")

    if port is None:
        port = find_usb_co2_port()

    print(f"[USB] Opening {port} @ {BAUD_RATE} baud...", file=sys.stderr)

    try:
        ser = serial.Serial(
            port=port, baudrate=BAUD_RATE, timeout=2.0,
            bytesize=serial.EIGHTBITS, parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
        )
    except Exception as e:
        raise ConnectionError(f"Cannot open {port}: {e}") from e

    ser.reset_input_buffer()
    time.sleep(0.3)
    print(f"[USB] Connected to {SENSOR_NAME} on {port}", file=sys.stderr)
    return ser


def parse_usb_line(line: str) -> Optional[dict]:
    """Parse one line of PS-3208 USB serial output."""
    line = line.strip()
    if not line:
        return None

    # Try CSV: co2,temp,hum,pressure
    parts = line.split(",")
    if len(parts) == 4:
        try:
            return dict(zip(CHANNELS, [float(p) for p in parts]))
        except ValueError:
            pass

    # Try key=value pairs
    data = {}
    for token in line.replace("\t", " ").split():
        if "=" in token:
            k, v = token.split("=", 1)
            try:
                data[k.strip().lower()] = float(v.strip())
            except ValueError:
                data[k.strip().lower()] = v.strip()

    if data:
        key_map = {
            "co2": "co2_ppm", "co2_ppm": "co2_ppm",
            "temp": "temperature_c", "temperature": "temperature_c",
            "humidity": "humidity_pct", "rh": "humidity_pct",
            "pressure": "pressure_kpa", "kpa": "pressure_kpa",
        }
        return {key_map.get(k, k): v for k, v in data.items()}

    return None


def disconnect_usb(ser: serial.Serial) -> None:
    """Close USB serial port."""
    try:
        if ser.is_open:
            ser.close()
    except Exception:
        pass


# ===========================================================================
#  Normalize raw data → consistent {channel: value} dict
# ===========================================================================

def normalize_data(raw) -> Optional[dict]:
    """
    Normalize readings from either transport into {channel_name: float}.

    BLE returns a dict keyed by measurement name (e.g. 'CO2', 'Temperature').
    USB returns a dict keyed by our CHANNELS names.
    """
    if raw is None:
        return None

    # Already in our format from USB parser
    if any(ch in raw for ch in CHANNELS):
        return raw

    # Map BLE measurement names → our channel names
    ble_map = {
        "co2": "co2_ppm", "co2ppm": "co2_ppm",
        "temperature": "temperature_c", "temp": "temperature_c",
        "relativehumidity": "humidity_pct", "humidity": "humidity_pct",
        "barometricpressure": "pressure_kpa", "pressure": "pressure_kpa",
        "absolutehumidity": None, "dewpoint": None, "windchill": None,
        "humidex": None,
    }
    result = {}
    for k, v in raw.items():
        key = k.replace(" ", "").replace("_", "").lower()
        mapped = ble_map.get(key)
        if mapped:
            try:
                result[mapped] = float(v) if not isinstance(v, (int, float)) else v
            except (ValueError, TypeError):
                result[mapped] = v
    return result if result else None


# ===========================================================================
#  Unified streaming
# ===========================================================================

def stream(
    duration: float = 0.0,
    output_format: str = "terminal",
    csv_path: Optional[str] = None,
) -> None:
    """Read PS-3208 data until duration expires or SIGINT."""
    global running, device, transport
    start_time = time.time()
    sample_count = 0

    # --- CSV setup ---
    csv_file = None
    csv_writer = None
    if output_format == "csv":
        if csv_path is None:
            csv_path = f"ps3208_{transport}_{datetime.now():%Y%m%d_%H%M%S}.csv"
        csv_file = open(csv_path, "w", newline="")
        csv_writer = csv.writer(csv_file)
        csv_writer.writerow(["timestamp_sec"] + CHANNELS)
        print(f"[CSV] Writing to {csv_path}", file=sys.stderr)

    # --- Header ---
    header = " │ ".join(["  time (s)"] + CHANNELS)
    print(f"\n{'─'*70}\n{header}\n{'─'*70}")

    # USB line buffer
    line_buf = ""

    try:
        while running:
            elapsed = time.time() - start_time
            if duration > 0 and elapsed >= duration:
                print(f"\n[DONE] Reached {duration}s.", file=sys.stderr)
                break

            raw = None

            if transport == "ble":
                raw = read_ble(device)
                time.sleep(0.05)

            elif transport == "usb":
                try:
                    chunk = device.read(device.in_waiting or 1).decode("utf-8", errors="replace")
                except serial.SerialException as e:
                    print(f"\n[USB] Read error: {e}", file=sys.stderr)
                    break
                line_buf += chunk
                while "\n" in line_buf:
                    line, line_buf = line_buf.split("\n", 1)
                    raw = parse_usb_line(line)
                    if raw:
                        break

            data = normalize_data(raw)
            if data is None:
                continue

            sample_count += 1
            timestamp = round(elapsed, 3)

            # --- Output ---
            if output_format == "json":
                record = {"timestamp_sec": timestamp, "transport": transport}
                record.update(data)
                print(json.dumps(record))

            elif output_format == "csv":
                csv_writer.writerow([timestamp] + [data.get(c, "") for c in CHANNELS])
                if sample_count % 10 == 0:
                    print(f"{timestamp:>10.3f} │ {_fmt_row(data)}")

            else:
                print(f"{timestamp:>10.3f} │ {_fmt_row(data)}")

    except KeyboardInterrupt:
        print("\n[STOP] User interrupted.", file=sys.stderr)
    except Exception as e:
        print(f"\n[ERROR] {e}", file=sys.stderr)
    finally:
        if csv_file:
            csv_file.close()
        print(f"\n[SUMMARY] {sample_count} samples | {elapsed:.1f}s | transport={transport}",
              file=sys.stderr)


def _fmt_row(data: dict) -> str:
    """Format data columns for terminal display."""
    fmt = {
        "co2_ppm":       ">8.1f",
        "temperature_c": ">7.2f",
        "humidity_pct":  ">7.1f",
        "pressure_kpa":  ">7.2f",
    }
    parts = []
    for ch in CHANNELS:
        v = data.get(ch, "?")
        if isinstance(v, float) and ch in fmt:
            parts.append(f"{v:{fmt[ch]}}")
        else:
            parts.append(f"{str(v):>8}")
    return " │ ".join(parts)


# ===========================================================================
#  Main
# ===========================================================================

def main() -> None:
    global device, transport

    parser = argparse.ArgumentParser(
        description=f"{SENSOR_NAME} — Dual Transport (BLE + USB)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                            Auto-detect best transport
  %(prog)s --ble                      Force BLE
  %(prog)s --ble --id 123-456        BLE by 6-digit sensor ID
  %(prog)s --port COM3                Force USB on COM3
  %(prog)s --port /dev/ttyACM0        Force USB on Linux
  %(prog)s --duration 60 --csv       60s to CSV
  %(prog)s --json --duration 30      JSON for 30s
  %(prog)s --list                     Show available BLE + USB
        """,
    )
    parser.add_argument("--list", action="store_true",
                        help="Scan BLE + USB, then exit.")
    parser.add_argument("--ble", action="store_true",
                        help="Use BLE transport (official pasco library).")
    parser.add_argument("--port", type=str, default=None,
                        help="Use USB transport on this serial port.")
    parser.add_argument("--id", type=str, default=None,
                        help="BLE: 6-digit sensor ID (e.g. '123-456').")
    parser.add_argument("--duration", type=float, default=0.0,
                        help="Seconds to stream (0 = until Ctrl+C).")
    parser.add_argument("--csv", dest="csv_path", nargs="?", const=None, default=None,
                        help="Output CSV.")
    parser.add_argument("--json", action="store_true",
                        help="Output JSON lines.")
    args = parser.parse_args()

    # --list
    if args.list:
        if _pasco_available:
            print("\n[BLE] Scanning...", file=sys.stderr)
            try:
                s = PASCOBLEDevice()
                devs = s.scan()
                if devs:
                    print(f"  Found {len(devs)} BLE device(s):")
                    for d in devs:
                        print(f"    {d.name}" if hasattr(d, "name") else f"    {d}")
                else:
                    print("  No BLE devices found.")
            except Exception as e:
                print(f"  BLE scan failed: {e}")
        else:
            print("\n[BLE] pasco library not installed.")

        if _pyserial_available:
            print("\n[USB] Serial ports:")
            ports = list_usb_ports()
            if ports:
                for p in ports:
                    print(f"  {p['device']:<20} {p['description']}")
            else:
                print("  No serial ports.")
        else:
            print("\n[USB] pyserial not installed.")
        return

    # Determine transport
    if args.ble:
        transport = "ble"
        if not _pasco_available:
            sys.exit("ERROR: --ble requires 'pasco' library:  pip install pasco")
    elif args.port:
        transport = "usb"
        if not _pyserial_available:
            sys.exit("ERROR: --port requires 'pyserial':  pip install pyserial")
    else:
        # Auto-detect: prefer BLE if available, fall back to USB
        if _pasco_available:
            transport = "ble"
            print("[AUTO] Trying BLE first (--ble/--port to override)...", file=sys.stderr)
        elif _pyserial_available:
            transport = "usb"
            print("[AUTO] BLE library not installed, using USB...", file=sys.stderr)

    # Output format
    if args.json:
        output_format = "json"
    elif args.csv_path is not None or args.csv:
        output_format = "csv"
    else:
        output_format = "terminal"

    # Connect
    try:
        if transport == "ble":
            device = connect_ble(args.id)
        else:
            device = connect_usb(args.port)

        stream(duration=args.duration, output_format=output_format,
               csv_path=args.csv_path if args.csv_path else None)

    except ConnectionError as e:
        # Auto-detect fallback: if BLE failed and USB is available, try USB
        if transport == "ble" and _pyserial_available and not args.ble:
            print(f"[AUTO] BLE failed ({e}), falling back to USB...", file=sys.stderr)
            transport = "usb"
            try:
                device = connect_usb(args.port)
                stream(duration=args.duration, output_format=output_format,
                       csv_path=args.csv_path if args.csv_path else None)
            except ConnectionError as e2:
                print(f"\n[FATAL] Both transports failed.\n  BLE: {e}\n  USB: {e2}",
                      file=sys.stderr)
                sys.exit(1)
        else:
            print(f"\n[FATAL] {e}", file=sys.stderr)
            sys.exit(1)
    except Exception as e:
        print(f"\n[FATAL] Unexpected: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        if device is not None:
            if transport == "ble":
                disconnect_ble(device)
            else:
                disconnect_usb(device)
            print(f"[DISCONNECT] {transport.upper()} closed.", file=sys.stderr)


if __name__ == "__main__":
    main()