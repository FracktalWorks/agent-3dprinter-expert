#!/usr/bin/env python3
"""Tiny client for Klipper's API socket, used by the deploy scripts on the printer.

    klipper_api.py <home> wait-ready [seconds]   wait for state "ready"; if an MCU reports it is
                                                 shut down (left over from a failed connect), send
                                                 FIRMWARE_RESTART once. Exit 0 when ready.
    klipper_api.py <home> endstops [seconds]     print X endstop changes (stepper_x = toolhead0,
                                                 dual_carriage = toolhead1) while someone presses them
"""
import json
import socket
import sys
import time


def call(home, method, params=None):
    s = socket.socket(socket.AF_UNIX)
    s.connect(home + "/printer_data/comms/klippy.sock")
    s.settimeout(10)
    s.sendall(json.dumps({"id": 1, "method": method, "params": params or {}}).encode() + b"\x03")
    buf = b""
    while b"\x03" not in buf:
        buf += s.recv(65536)
    s.close()
    return json.loads(buf.split(b"\x03")[0])


def wait_ready(home, seconds):
    restarted = False
    end = time.time() + seconds
    state = msg = "?"
    while time.time() < end:
        try:
            r = call(home, "info")["result"]
            state, msg = r["state"], (r.get("state_message") or "").splitlines()[0]
        except Exception as e:  # socket not up yet while Klipper starts
            state, msg = "starting", str(e)
        if state == "ready":
            print("klipper: ready |", r.get("config_file", ""))
            return 0
        if state == "error" and "shutdown" in msg and not restarted:
            print("klipper: MCU left in shutdown -> FIRMWARE_RESTART")
            call(home, "gcode/firmware_restart")
            restarted = True
        time.sleep(3)
    print("klipper: NOT ready:", state, "|", msg)
    return 1


def endstops(home, seconds):
    last, end = None, time.time() + seconds
    print("press the LEFT carriage's X endstop, then the RIGHT one (%d s)" % seconds, flush=True)
    while time.time() < end:
        e = call(home, "query_endstops/status")["result"]
        cur = (e.get("stepper_x"), e.get("dual_carriage"))
        if cur != last:
            print(time.strftime("%H:%M:%S"), "stepper_x(toolhead0)=%-9s dual_carriage(toolhead1)=%s" % cur, flush=True)
            last = cur
        time.sleep(0.3)
    return 0


if __name__ == "__main__":
    home, cmd = sys.argv[1], sys.argv[2]
    secs = int(sys.argv[3]) if len(sys.argv) > 3 else 60
    sys.exit({"wait-ready": wait_ready, "endstops": endstops}[cmd](home, secs))
