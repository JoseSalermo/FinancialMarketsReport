from pathlib import Path

import pandas as pd

from financial_market_report.reporting.renderer import render_report_html


def test_report_can_render_chart_images_as_content_ids() -> None:
    html = render_report_html(
        title="Report",
        generated_at="now",
        interest_table=pd.DataFrame([{"symbol": "ABC"}]),
        chart_paths={"ABC": [Path("ABC_5m_1d.png")]},
        image_src_mode="cid",
    )

    assert 'src="cid:ABC_5m_1d.png"' in html
