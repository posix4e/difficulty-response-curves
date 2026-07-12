import pytest

from drc.cli import main


def test_registered_v1_collection_is_locked():
    with pytest.raises(SystemExit, match="finish v1 with its original collector"):
        main(["run"])


def test_plan_needs_no_api_key(capsys):
    assert main(["plan"]) == 0
    assert '"planned_calls": 600' in capsys.readouterr().out
