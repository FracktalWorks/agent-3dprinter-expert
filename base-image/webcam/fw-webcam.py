#!/usr/bin/env python3
"""Fracktal webcam: Raspberry Pi CSI camera (libcamera/picamera2) -> MJPEG over HTTP.

Serves the same URLs as mjpg-streamer/ustreamer, so OctoPrint and ControlCenter need no changes:
    http://<printer>:8080/?action=stream     multipart MJPEG stream
    http://<printer>:8080/?action=snapshot   one JPEG
JPEG encoding is done by the Pi's hardware encoder (picamera2 MJPEGEncoder). ustreamer cannot be
used for CSI cameras: they deliver raw Bayer frames that need the libcamera ISP.
Installed by base-image/webcam/install-webcam.sh as /usr/local/bin/fw-webcam (fw-webcam.service).
"""
import argparse
import io
import logging
import socketserver
import threading
from http import server

from libcamera import Transform
from picamera2 import Picamera2
from picamera2.encoders import MJPEGEncoder, Quality
from picamera2.outputs import FileOutput

BOUNDARY = "FRAME"


class Frames(io.BufferedIOBase):
    """Latest JPEG frame, with a condition so clients wait for the next one."""

    def __init__(self):
        self.frame = None
        self.cond = threading.Condition()

    def write(self, buf):
        with self.cond:
            self.frame = bytes(buf)
            self.cond.notify_all()
        return len(buf)

    def next(self, timeout=5):
        with self.cond:
            if not self.cond.wait(timeout):
                return None
            return self.frame


class Handler(server.BaseHTTPRequestHandler):
    frames = None

    def do_GET(self):
        if "action=snapshot" in self.path:
            frame = self.frames.next()
            if frame is None:
                self.send_error(503, "no frame from the camera")
                return
            self.send_response(200)
            self._no_cache()
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(frame)))
            self.end_headers()
            self.wfile.write(frame)
        elif "action=stream" in self.path or self.path in ("/", "/stream"):
            self.send_response(200)
            self._no_cache()
            self.send_header("Content-Type", f"multipart/x-mixed-replace; boundary={BOUNDARY}")
            self.end_headers()
            try:
                while True:
                    frame = self.frames.next()
                    if frame is None:
                        continue
                    self.wfile.write(f"--{BOUNDARY}\r\nContent-Type: image/jpeg\r\n"
                                     f"Content-Length: {len(frame)}\r\n\r\n".encode())
                    self.wfile.write(frame)
                    self.wfile.write(b"\r\n")
            except (BrokenPipeError, ConnectionResetError):
                pass  # client went away
        else:
            self.send_error(404)

    def _no_cache(self):
        self.send_header("Cache-Control", "no-cache, private")
        self.send_header("Pragma", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")

    def log_message(self, fmt, *args):
        pass


class Server(socketserver.ThreadingMixIn, server.HTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--width", type=int, default=1296)
    ap.add_argument("--height", type=int, default=972)
    ap.add_argument("--fps", type=int, default=15)
    ap.add_argument("--rotate", type=int, choices=(0, 180), default=0)
    ap.add_argument("--hflip", action="store_true")
    ap.add_argument("--vflip", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    hflip = a.hflip != (a.rotate == 180)
    vflip = a.vflip != (a.rotate == 180)
    cam = Picamera2()
    cfg = cam.create_video_configuration(main={"size": (a.width, a.height)},
                                         transform=Transform(hflip=hflip, vflip=vflip),
                                         controls={"FrameRate": a.fps})
    cam.configure(cfg)
    Handler.frames = Frames()
    cam.start_recording(MJPEGEncoder(), FileOutput(Handler.frames), quality=Quality.MEDIUM)
    logging.info("fw-webcam: %s %dx%d @ %d fps on :%d", cam.camera_properties.get("Model"),
                 a.width, a.height, a.fps, a.port)
    try:
        Server(("", a.port), Handler).serve_forever()
    finally:
        cam.stop_recording()


if __name__ == "__main__":
    main()
