from pathlib import Path

import pytest

from invest_research.schemas import RunRequest
from invest_research.storage import Store


def test_checkpoint_and_path_boundary(tmp_path: Path):
    store = Store(tmp_path)
    run_id = store.create(RunRequest(company_name="Apple Inc."))
    store.write(run_id, "00_company.json", {"cik": 320193})
    assert store.read(run_id, "00_company.json")["cik"] == 320193
    assert len(store.get(run_id)["stages"]) == 5
    assert store.get(run_id)["artifact_manifest"][0]["name"] == "00_company.json"
    with pytest.raises(ValueError):
        store.path(run_id, "../secrets")
    store.path(run_id, "00_company.json").write_text('{"cik": 2}', encoding="utf-8")
    with pytest.raises(ValueError, match="checksum"):
        store.read(run_id, "00_company.json")


def test_retry_key_is_idempotent(tmp_path: Path):
    store = Store(tmp_path)
    run_id = store.create(RunRequest(company_name="Apple Inc."))
    assert store.idempotent(run_id, "retry", "same-key")
    assert not store.idempotent(run_id, "retry", "same-key")
