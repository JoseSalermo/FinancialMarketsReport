from financial_market_report.storage.repository import create_report_run, finish_report_run, get_report_run, record_report
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
