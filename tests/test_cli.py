"""tests/test_cli.py — Unit tests for SwarmCurator CLI commands."""

import json
from pathlib import Path
from swarmcurator.cli import main


def test_cli_admit_and_pop(tmp_path: Path, capsys) -> None:
    store_path = tmp_path / "cli_queue.json"

    # 1. Admit
    ret_admit = main([
        "--store", str(store_path),
        "admit",
        "--id", "GRO-900",
        "--title", "Refactor queue",
        "--provider", "linear",
        "--priority", "1",
        "--lane", "prismatic-core",
    ])
    assert ret_admit == 0
    admit_data = json.loads(capsys.readouterr().out)
    assert admit_data["ok"] is True
    assert admit_data["task"]["lane_id"] == "prismatic-core"

    # 2. Lanes
    ret_lanes_pre = main(["--store", str(store_path), "lanes"])
    assert ret_lanes_pre == 0
    assert json.loads(capsys.readouterr().out) == {}

    # 3. Pop
    ret_pop = main([
        "--store", str(store_path),
        "pop",
        "--agent", "agy",
    ])
    assert ret_pop == 0
    pop_data = json.loads(capsys.readouterr().out)
    assert pop_data["ok"] is True
    assert pop_data["task"]["external_id"] == "GRO-900"

    # 4. Release
    ret_release = main([
        "--store", str(store_path),
        "release",
        "--lane", "prismatic-core",
        "--status", "completed",
    ])
    assert ret_release == 0
    rel_data = json.loads(capsys.readouterr().out)
    assert rel_data["ok"] is True
