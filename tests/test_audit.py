from drc.audit import audit_retrospective


def test_released_retrospective_result_recomputes():
    result = audit_retrospective()
    assert result["prediction_rows"] == 85
    assert result["pass"]
    assert all(value["matches"] for value in result["metrics"].values())
