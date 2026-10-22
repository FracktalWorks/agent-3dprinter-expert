"""Smoke tests for deploy/deploy_printer.py that need no printer (fake SSH client)."""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("deploy_printer", ROOT / "deploy" / "deploy_printer.py")
dp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dp)


class FakeSftp:
    def __init__(self): self.files = {}
    def stat(self, p): raise IOError
    def mkdir(self, p): pass
    def chmod(self, p, m): pass
    def put(self, a, b): self.files[b] = Path(a).read_bytes()
    def open(self, path, mode):
        files = self.files
        class F:
            def __enter__(s): s.buf = []; return s
            def __exit__(s, *a): files[path] = b"".join(s.buf) if s.buf and isinstance(s.buf[0], bytes) else "".join(s.buf).encode()
            def write(s, d): s.buf.append(d)
        return F()


def fake_printer(apply):
    p = dp.Printer.__new__(dp.Printer)
    p.apply, p.host, p.user, p.sftp, p.cmds = apply, "h", "pi", FakeSftp(), []
    p.run = lambda cmd, mutating=False, **k: (p.cmds.append((cmd, mutating)), (0, ""))[1]
    return p


def args(**kw):
    ns = dict(apply=False, yes=False, user="pi", host="h", workspace=None, full_base=False, restart=False,
              op_version=None, cc_ref=None, cc_source=None, logo=None, model=None, serial=None)
    ns.update(kw)
    return type("A", (), ns)()


def test_uploads_never_ship_crlf():
    p = fake_printer(False)
    dp.Printer.put_dir(p, ROOT / "base-image" / "touchui", "/home/pi/fw-deploy/touchui")
    for path, data in p.sftp.files.items():
        assert b"\r\n" not in data, path


def test_commission_requires_known_model_and_serial():
    with pytest.raises(SystemExit):
        dp.step_commission(args(model="nope", serial="FW-1"), fake_printer(False))
    with pytest.raises(SystemExit):
        dp.step_commission(args(model="dragon-400"), fake_printer(False))


def test_commission_dry_run_does_not_mutate():
    p = fake_printer(False)
    dp.step_commission(args(model="dragon-400", serial="FW-0421"), p)
    assert all(m for _, m in p.cmds), "every commission command must be marked mutating"


def test_base_dry_run_marks_apply_as_mutating_and_octoprint_is_dry_by_default(tmp_path):
    p = fake_printer(False)
    dp.step_base(args(), p)
    assert any("apply.sh" in c and m for c, m in p.cmds)
    ws = tmp_path / "Fracktal_OctoPrint_NextGen" / "fracktal"
    ws.mkdir(parents=True)
    (ws / "install-octoprint.sh").write_text("#!/bin/bash\n")
    p2 = fake_printer(False)
    dp.step_octoprint(args(workspace=str(tmp_path)), p2)
    cmds = [c for c, _ in p2.cmds if "install-octoprint.sh" in c]
    assert len(cmds) == 1 and "--yes" not in cmds[0]
    p3 = fake_printer(True)
    dp.step_octoprint(args(workspace=str(tmp_path), apply=True), p3)
    assert sum("--yes" in c for c, _ in p3.cmds) == 1
