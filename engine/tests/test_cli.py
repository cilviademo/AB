import json

from ab_engine.cli import main


def test_doctor_json(capsys, tmp_path):
    rc = main(["--workspace", str(tmp_path / "w"), "doctor"])
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True and "rows" in out["data"]
    assert rc in (0, 1)


def test_doctor_text(capsys, tmp_path):
    main(["--workspace", str(tmp_path / "w"), "--text", "doctor"])
    assert "AB doctor" in capsys.readouterr().out


def test_methods_lists_ping(capsys, tmp_path):
    main(["--workspace", str(tmp_path / "w"), "methods"])
    assert "ping" in json.loads(capsys.readouterr().out)["data"]["methods"]
