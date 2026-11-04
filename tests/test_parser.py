import json
from pathlib import Path

from app.parser import extract_sections, parse_loaded_documents


def test_extracts_headings_paragraphs_and_tables():
    html = """
    <html><head><title>Example Fund</title></head>
    <body>
      <nav>Navigation should disappear</nav>
      <main>
        <h1>Example Fund</h1>
        <h2>Scheme Details</h2>
        <p>This is a scheme detail.</p>
        <table><tr><th>Expense ratio</th><td>0.50%</td></tr></table>
        <script>Ignore this script</script>
        <footer>Footer should disappear</footer>
      </main>
    </body></html>
    """
    title, sections = extract_sections(html)
    assert title == "Example Fund"
    assert len(sections) == 1
    text = " ".join(sections[0]["blocks"])
    assert "This is a scheme detail." in text
    assert "Expense ratio | 0.50%" in text
    assert "Navigation" not in text
    assert "Footer" not in text
    assert "Ignore this script" not in text


def test_sections_remain_separated_by_headings():
    html = """
    <html><body><main>
      <h2>Fund Overview</h2><p>Overview text.</p>
      <h2>Riskometer</h2><p>Risk text.</p>
    </main></body></html>
    """
    _, sections = extract_sections(html)
    assert [s["section_title"] for s in sections] == ["Fund Overview", "Riskometer"]
    assert sections[0]["blocks"] == ["Overview text."]
    assert sections[1]["blocks"] == ["Risk text."]


def test_parser_reads_jsonl_and_writes_parsed_output(tmp_path):
    loaded = tmp_path / "data/loaded"
    loaded.mkdir(parents=True)
    doc = {
        "page_content": "<html><body><main><h2>Details</h2><p>Minimum SIP is Rs 100.</p></main></body></html>",
        "metadata": {
            "source_id": "hdfc_large_cap",
            "source_title": "HDFC Large Cap Fund",
            "source_url": "https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth",
            "fetched_at": "2026-11-02T10:00:00+00:00",
        },
    }
    (loaded / "loaded_documents.jsonl").write_text(json.dumps(doc) + "\n", encoding="utf-8")
    parsed, report = parse_loaded_documents(tmp_path)
    assert len(parsed) == 1
    assert report["parsed_count"] == 1
    output = tmp_path / "data/parsed/parsed_documents.jsonl"
    saved = json.loads(output.read_text(encoding="utf-8").strip())
    assert saved["sections"][0]["section_title"] == "Details"
