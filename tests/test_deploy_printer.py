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
    p.out = ""
    p.run = lambda cmd, mutating=False, **k: (p.cmds.append((cmd, mutating)), (0, p.out))[1]
    p.units = []
    p.run_unit = lambda unit, cmd, **k: (p.units.append((unit, cmd)), 0)[1]
    return p


def args(**kw):
    ns = dict(apply=False, yes=False, user="pi", host="h", workspace=None, full_base=False, restart=False,
              op_version=None, cc_ref=None, cc_source=None, logo=None, op_plugins=None, model=None, serial=None,
              online=False, retire_legacy=False, set=None, endstops=False, stop_klipper=False)
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
    dp.step_octoprint(args(workspace=str(tmp_path), apply=True, online=True), p3)
    assert not any("--yes" in c for c, _ in p3.cmds), "the install itself must run as a detached unit"
    assert len(p3.units) == 1 and p3.units[0][1].endswith("--yes") and "octoprint-install.sh" in p3.units[0][1]
    assert "production.zip" not in p3.units[0][1] and "--source" not in p3.units[0][1]


INSTALLER = """#!/usr/bin/env bash
CC_REPO="FracktalWorks/ControlCenter"
CC_SOURCE="https://github.com/${CC_REPO}/archive/refs/tags/1.1.8.zip"
DEFAULT_PLUGINS="https://github.com/FracktalWorks/TwinDragonPrintRestore/archive/refs/tags/1.0.6.zip https://github.com/FracktalWorks/OctoprintKlipperPlugin/archive/refs/tags/0.4.2.zip"
"""


def test_installer_pins_and_cache_names(tmp_path):
    f = tmp_path / "install-octoprint.sh"
    f.write_text(INSTALLER)
    cc, plugins = dp.installer_pins(f)
    assert cc == "https://github.com/FracktalWorks/ControlCenter/archive/refs/tags/1.1.8.zip"
    assert [dp.cache_name(u) for u in plugins] == ["TwinDragonPrintRestore-1.0.6.zip", "OctoprintKlipperPlugin-0.4.2.zip"]
    whl = "https://github.com/FracktalWorks/Fracktal_OctoPrint_NextGen/releases/download/1.11.8.post3/octoprint-1.11.8.post3-py3-none-any.whl"
    assert dp.cache_name(whl) == "octoprint-1.11.8.post3-py3-none-any.whl"


def test_real_installer_pins_parse():
    real = ROOT.parent / "Fracktal_OctoPrint_NextGen" / "fracktal" / "install-octoprint.sh"
    if not real.exists():
        pytest.skip("NextGen checkout not next to this repo")
    cc, plugins = dp.installer_pins(real)
    assert cc.startswith("https://github.com/FracktalWorks/ControlCenter/archive/refs/tags/")
    assert any("TwinDragonPrintRestore" in u for u in plugins) and any("OctoprintKlipperPlugin" in u for u in plugins)


def test_configs_and_can_dry_runs_change_nothing():
    p = fake_printer(False)
    dp.step_configs(args(), p)
    assert not p.units and all("--yes" not in c for c, _ in p.cmds)
    p = fake_printer(False)
    dp.step_can(args(stop_klipper=True), p)
    assert all("--stop-klipper" not in c for c, _ in p.cmds), "stopping Klipper needs --yes"
    p = fake_printer(False)
    dp.step_can(args(set=["8e73c0160b99", "7cb976b83a03", "3ec1b8773dd7"]), p)
    assert any(" set 8e73c0160b99 7cb976b83a03 3ec1b8773dd7" in c and "--yes" not in c for c, _ in p.cmds)
    with pytest.raises(SystemExit):
        dp.step_can(args(set=["8e73c0160b99"]), fake_printer(False))


def test_configs_apply_runs_as_unit():
    p = fake_printer(True)
    dp.step_configs(args(apply=True), p)
    assert p.units and p.units[0][1].endswith("--yes")


def test_touchui_retire_legacy_is_passed_through():
    p = fake_printer(True)
    dp.step_touchui(args(apply=True, retire_legacy=True), p)
    assert any("--retire-legacy" in c and "--yes" in c for c, _ in p.cmds)


def test_verify_reports_problem_lines():
    p = fake_printer(False)
    p.out = "## OctoPrint\nok\n!! octoprint.service does not run the NextGen venv\n!! SAFE MODE\n"
    assert dp.step_verify(args(), p) == ["!! octoprint.service does not run the NextGen venv", "!! SAFE MODE"]


def test_run_unit_dry_run_does_nothing(capsys):
    p = dp.Printer.__new__(dp.Printer)
    p.apply = False
    assert dp.Printer.run_unit(p, "fw-x", "/bin/true") == 0
    assert "[dry-run]" in capsys.readouterr().out


def test_remote_scripts_are_lf_and_executable_in_upload():
    p = fake_printer(False)
    dp.Printer.put_dir(p, ROOT / "deploy" / "remote", "/home/pi/fw-deploy/remote")
    assert any(k.endswith("octoprint-install.sh") for k in p.sftp.files)
    for path, data in p.sftp.files.items():
        assert b"\r\n" not in data, path
