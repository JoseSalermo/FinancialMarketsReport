import json

from financial_market_report.storage.repository import (
    create_report_run,
    finish_report_run,
    get_report_run,
    get_settings,
    list_report_runs,
    record_report,
)
from financial_market_report.web.app import create_app


def test_report_asset_route_serves_chart_sibling(tmp_path) -> None:
    db_path = tmp_path / "app.sqlite3"
    report_dir = tmp_path / "reports" / "2026-05-01"
    report_dir.mkdir(parents=True)
    report_path = report_dir / "Market_2026-05-01.html"
    chart_path = report_dir / "ABC_5m_1d.png"
    report_path.write_text('<img src="ABC_5m_1d.png">', encoding="utf-8")
    chart_path.write_bytes(b"png")

    run_id = create_report_run(db_path, started_at="2026-05-01 00:00:00 EDT-0400", params={})
    record_report(
        db_path,
        run_id=run_id,
        report_date="2026-05-01",
        html_path=report_path,
        email_status="sent",
    )

    client = create_app(db_path=db_path).test_client()

    response = client.get(f"/reports/{run_id}/ABC_5m_1d.png")

    assert response.status_code == 200
    assert response.data == b"png"


def test_report_asset_route_rejects_nested_paths(tmp_path) -> None:
    db_path = tmp_path / "app.sqlite3"
    report_dir = tmp_path / "reports" / "2026-05-01"
    report_dir.mkdir(parents=True)
    report_path = report_dir / "Market_2026-05-01.html"
    report_path.write_text("<html></html>", encoding="utf-8")

    run_id = create_report_run(db_path, started_at="2026-05-01 00:00:00 EDT-0400", params={})
    record_report(
        db_path,
        run_id=run_id,
        report_date="2026-05-01",
        html_path=report_path,
        email_status="sent",
    )

    client = create_app(db_path=db_path).test_client()

    response = client.get(f"/reports/{run_id}/nested/ABC_5m_1d.png")

    assert response.status_code == 404


def test_delete_run_removes_completed_run_history(tmp_path) -> None:
    db_path = tmp_path / "app.sqlite3"
    run_id = create_report_run(db_path, started_at="2026-05-01 00:00:00 EDT-0400", params={})
    finish_report_run(
        db_path,
        run_id=run_id,
        status="failed",
        finished_at="2026-05-01 00:01:00 EDT-0400",
    )
    client = create_app(db_path=db_path).test_client()

    response = client.post(f"/runs/{run_id}/delete")

    assert response.status_code == 302
    assert get_report_run(db_path, run_id) is None


def test_delete_run_keeps_running_run(tmp_path) -> None:
    db_path = tmp_path / "app.sqlite3"
    run_id = create_report_run(db_path, started_at="2026-05-01 00:00:00 EDT-0400", params={})
    client = create_app(db_path=db_path).test_client()

    response = client.post(f"/runs/{run_id}/delete")

    assert response.status_code == 302
    assert get_report_run(db_path, run_id) is not None


def test_settings_page_does_not_show_smtp_ssl_checkbox(tmp_path) -> None:
    client = create_app(db_path=tmp_path / "app.sqlite3").test_client()

    response = client.get("/settings")

    assert response.status_code == 200
    assert b"SMTP SSL" not in response.data
    assert b'email.use_ssl' not in response.data


def test_settings_page_saves_schedule_run_days(tmp_path) -> None:
    db_path = tmp_path / "app.sqlite3"
    client = create_app(db_path=db_path).test_client()

    response = client.post("/settings", data={"schedule.run_days": ["mon", "wed", "fri"]})

    settings = get_settings(db_path)
    assert response.status_code == 302
    assert json.loads(settings["schedule.run_days"]) == ["mon", "wed", "fri"]


def test_clear_runs_removes_completed_runs_and_keeps_running_run(tmp_path) -> None:
    db_path = tmp_path / "app.sqlite3"
    completed_id = create_report_run(db_path, started_at="2026-05-01 00:00:00 EDT-0400", params={})
    finish_report_run(
        db_path,
        run_id=completed_id,
        status="succeeded",
        finished_at="2026-05-01 00:01:00 EDT-0400",
    )
    running_id = create_report_run(db_path, started_at="2026-05-01 00:02:00 EDT-0400", params={})
    client = create_app(db_path=db_path).test_client()

    response = client.post("/runs/clear")

    rows = list_report_runs(db_path, limit=10)
    assert response.status_code == 302
    assert [row["id"] for row in rows] == [running_id]


def test_clear_runs_resets_scheduler_marker(tmp_path) -> None:
    class FakeScheduler:
        def __init__(self) -> None:
            self.cleared = False

        def clear_last_run_date(self) -> None:
            self.cleared = True

    app = create_app(db_path=tmp_path / "app.sqlite3")
    scheduler = FakeScheduler()
    app.config["SCHEDULER"] = scheduler

    response = app.test_client().post("/runs/clear")

    assert response.status_code == 302
    assert scheduler.cleared is True
