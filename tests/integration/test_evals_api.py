import shutil
import time
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.config import Settings
from core.enums import Role
from evals.benchmark import reports_dir_for
from tests.conftest import headers

ROOT = Path(__file__).resolve().parents[2]


def wait_idle(client: TestClient, timeout_s: float = 120.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        status: dict[str, Any] = client.get("/evals/status", headers=headers(Role.VIEWER)).json()
        if status["state"] != "running":
            return status
        time.sleep(0.1)
    raise AssertionError("benchmark did not finish")


def test_latest_is_404_before_any_run(client: TestClient) -> None:
    response = client.get("/evals/latest", headers=headers(Role.VIEWER))
    assert response.status_code == 404


def test_run_and_fetch_latest(client: TestClient) -> None:
    viewer = client.post("/evals/run", json={"limit": 2}, headers=headers(Role.VIEWER))
    assert viewer.status_code == 403

    started = client.post("/evals/run", json={"limit": 2}, headers=headers(Role.OPERATOR))
    assert started.status_code == 202
    assert started.json()["state"] == "running"

    again = client.post("/evals/run", json={"limit": 2}, headers=headers(Role.OPERATOR))
    assert again.status_code == 409

    assert wait_idle(client)["state"] == "idle"
    latest = client.get("/evals/latest", headers=headers(Role.VIEWER))
    assert latest.status_code == 200
    body = latest.json()
    assert body["setup"]["incident_cases"] == 2
    assert body["setup"]["llm_mode"] == "heuristic"


def test_llm_benchmark_needs_admin(client: TestClient) -> None:
    response = client.post(
        "/evals/run", json={"provider": "anthropic", "limit": 1}, headers=headers(Role.OPERATOR)
    )
    assert response.status_code == 403
    assert "only admins" in response.json()["error"]["message"]


def test_claude_report_is_served_separately(client: TestClient, settings: Settings) -> None:
    claude_dir = settings.eval_reports_dir / "claude"
    claude_dir.mkdir(parents=True)
    shutil.copy(ROOT / "evals" / "reports" / "claude" / "latest.json", claude_dir / "latest.json")

    claude = client.get("/evals/latest?provider=anthropic", headers=headers(Role.VIEWER))
    assert claude.status_code == 200
    assert claude.json()["setup"]["llm_mode"] == "anthropic"
    # The heuristic baseline lives in its own folder and is not replaced by Claude runs.
    assert client.get("/evals/latest", headers=headers(Role.VIEWER)).status_code == 404


def test_claude_runs_write_to_their_own_folder(tmp_path: Path) -> None:
    assert reports_dir_for(tmp_path, "anthropic") == tmp_path / "claude"
    assert reports_dir_for(tmp_path, "heuristic") == tmp_path
