"""
Tests for Phase 4 CLI Entry Point.
"""
import json
from pathlib import Path
import pytest
from phase4.explain import main


def test_cli_execution_with_temp_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Prepare dummy job description
    jd_file = tmp_path / "backend-eng.txt"
    jd_file.write_text(
        "Backend Engineer\n\nRequired skills:\n- Python microservices\n- Docker containerization\n",
        encoding="utf-8",
    )

    # Prepare dummy Phase 3 reranked JSON
    p3_file = tmp_path / "backend-eng-reranked.json"
    p3_data = {
        "job_id": "backend-eng",
        "candidates": [
            {
                "candidate_id": "cand_01",
                "rerank_rank": 1,
                "rerank_score": 0.88,
                "phase2": {
                    "matched_chunks": [{"chunk_id": "c1", "section": "skills"}]
                },
            }
        ],
    }
    p3_file.write_text(json.dumps(p3_data), encoding="utf-8")

    out_dir = tmp_path / "outputs"

    monkeypatch.setattr("phase4.config.MONGODB_URI", "")
    monkeypatch.setattr(
        "sys.argv",
        [
            "phase4.explain",
            "--job", str(jd_file),
            "--input", str(p3_file),
            "--output-dir", str(out_dir),
        ],
    )

    main()

    explained_file = out_dir / "backend-eng-explained.json"
    assert explained_file.exists()

    result = json.loads(explained_file.read_text(encoding="utf-8"))
    assert result["job_id"] == "backend-eng"
    assert result["candidate_count"] == 1
    assert result["candidates"][0]["rerank_rank"] == 1
    assert result["candidates"][0]["candidate_id"] == "cand_01"
