from drc.audit import audit_model_cohort


def test_existing_glm_calls_are_censored_not_failed():
    result = audit_model_cohort("data/exports/drc.sqlite.gz", "z-ai/glm-5")
    assert result["claim_status"] == "Censored"
    assert result["counts"] == {
        "calls": 14,
        "instances": 13,
        "correct_completed": 9,
        "silently_wrong_completed": 5,
        "loud_failure": 0,
    }
    assert len(result["providers"]) == 3
    assert not result["eligibility"]["pass"]
    assert result["new_spend_usd"] == 0
