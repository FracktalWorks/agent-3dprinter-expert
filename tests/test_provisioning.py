"""Tests for base-image/provision.py and the pure logic of overlay/usr/local/sbin/fw-commission."""
import importlib.machinery
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "base-image"


def _load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    loader.exec_module(mod)
    return mod


provision = _load("fw_provision", BASE / "provision.py")
commission = _load("fw_commission", BASE / "overlay/usr/local/sbin/fw-commission")


def _args(**kw):
    base = dict(serial="FW-0421", model="twindragon-600-v2", hostname=None, wifi_ssid=None,
                wifi_pass=None, timezone="Asia/Kolkata")
    base.update(kw)
    return type("A", (), base)()


def test_models_reference_real_templates():
    models = provision.load_models()
    templates = ROOT.parent / "klipper_IDEX" / "fracktal_config" / "templates"
    if not templates.exists():
        pytest.skip("klipper_IDEX checkout not next to this repo")
    for key, m in models.items():
        assert (templates / m["include"]).exists(), f"{key}: {m['include']} missing from templates"


def test_build_merges_existing_user_data_and_sets_identity():
    existing = {"users": [{"name": "pi", "passwd": "HASH"}], "runcmd": [["echo", "keep"]]}
    files = provision.build(_args(), provision.load_models(), existing)
    ud = yaml.safe_load(files["user-data"])
    assert ud["users"] == existing["users"], "fleet password must survive"
    assert ud["hostname"] == "fw-fw-0421" or ud["hostname"] == "fw-fw-0421".lower()
    assert ["echo", "keep"] in ud["runcmd"] and ["/usr/local/sbin/fw-commission"] in ud["runcmd"]
    assert files["user-data"].startswith("#cloud-config\n")
    assert "instance-id: fw-FW-0421" in files["meta-data"]
    rec = json.loads(files["fw-commission.json"])
    assert rec["printer_cfg_include"] == "PRINTER_TWINDRAGON_600_V2.cfg" and rec["toolheads"] == 2


def test_build_is_idempotent_for_runcmd():
    first = provision.build(_args(), provision.load_models(), {})
    again = provision.build(_args(), provision.load_models(), yaml.safe_load(first["user-data"]))
    assert yaml.safe_load(again["user-data"])["runcmd"].count(["/usr/local/sbin/fw-commission"]) == 1


def test_wifi_goes_into_network_config():
    files = provision.build(_args(wifi_ssid="Workshop", wifi_pass="longenough"), provision.load_models())
    net = yaml.safe_load(files["network-config"])["network"]
    assert net["wifis"]["wlan0"]["access-points"]["Workshop"]["password"] == "longenough"
    assert net["ethernets"]["eth0"]["dhcp4"] is True


@pytest.mark.parametrize("kw", [dict(serial="x"), dict(serial="bad serial!"), dict(model="nope"),
                                dict(hostname="Bad_Host"), dict(wifi_pass="short", wifi_ssid="a"),
                                dict(wifi_pass="longenough")])
def test_bad_input_rejected(kw):
    with pytest.raises(ValueError):
        provision.build(_args(**kw), provision.load_models())


def test_cli_refuses_non_boot_directory(tmp_path):
    assert provision.main(["--boot", str(tmp_path), "--serial", "FW-1", "--model", "dragon-400"]) == 2


def test_cli_writes_files_on_boot_partition(tmp_path):
    (tmp_path / "cmdline.txt").write_text("console=tty1 root=PARTUUID=abcd-02")
    assert provision.main(["--boot", str(tmp_path), "--serial", "FW-0421", "--model", "dragon-400"]) == 0
    for n in ("meta-data", "user-data", "network-config", "fw-commission.json"):
        assert (tmp_path / n).exists()


CFG = """[include mainsail.cfg]
#[include PRINTER_TWINDRAGON_600x300.cfg]
[include PRINTER_DRAGON_400.cfg]
#[include PRINTER_DRAGON_500.cfg]
[mcu]
serial: /dev/x
"""


def test_select_include_activates_exactly_one():
    out = commission.select_include(CFG, "PRINTER_DRAGON_500.cfg")
    active = re.findall(r"^\[include (PRINTER_\S+)\]$", out, re.M)
    assert active == ["PRINTER_DRAGON_500.cfg"]
    assert "[include mainsail.cfg]" in out and "serial: /dev/x" in out


def test_select_include_missing_model_errors():
    with pytest.raises(ValueError):
        commission.select_include(CFG, "PRINTER_NOPE.cfg")


def test_rewrite_octoprint_secrets_changes_only_keys(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("api:\n  allowCrossOrigin: true\n  key: OLDKEY\nserver:\n  firstRun: false\n  secretKey: oldsecret\n"
                 "serial:\n  port: /tmp/printer\n")
    key = commission.rewrite_octoprint_secrets(p)
    d = yaml.safe_load(p.read_text())
    assert d["api"]["key"] == key != "OLDKEY" and len(key) == 32
    assert d["server"]["secretKey"] != "oldsecret"
    assert d["api"]["allowCrossOrigin"] is True and d["server"]["firstRun"] is False
    assert d["serial"]["port"] == "/tmp/printer"


def test_rewrite_octoprint_secrets_adds_missing_sections(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("serial:\n  port: /tmp/printer\n")
    commission.rewrite_octoprint_secrets(p)
    d = yaml.safe_load(p.read_text())
    assert d["api"]["key"] and d["server"]["secretKey"]
