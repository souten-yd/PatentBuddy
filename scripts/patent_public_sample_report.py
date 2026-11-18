"""Reproducible one-shot PUBLIC patent sample research; no AI or production import.

The explicitly pinned 12 URLs are illustrative, not a patent census.
--fetch is opt-in. Respect robots.txt, request rate and 3 MiB response cap.
Output only short structured public metadata and SHA256, NOT source HTML.
No credentials, non-public search terms, bulk file fetch or background jobs.
"""
import argparse
from collections import Counter
from datetime import date
from html import escape
from html.parser import HTMLParser
import hashlib
import json
from pathlib import Path
import re
import time
import urllib.error
import urllib.request
import urllib.robotparser

PUBLIC_IDS = (
    "US11996769B2", "US12308814B2", "US20240413777A1",
    "US20230326646A1", "WO2021163358A1", "US8115444B2",
    "WO2018208057A1", "JP2020103029A", "US11018572B2",
    "US9172296B2", "US20250233514A1", "US20230326646A1",
)
# Deduplicate the manually curated targets; the source family may still overlap.
PUBLIC_IDS = tuple(dict.fromkeys(PUBLIC_IDS))
BASE = "https://patents.google.com/patent/"
MAX_HTML = 3 * 1024 * 1024
MAX_RECORDS = 12
PACING_SEC = 2.5
USER_AGENT = "PatentBuddy-public-sample/0.1"
ALLOWED_ID = re.compile(r"^(?:US|JP|WO)[0-9]{5,12}(?:A1|A2|B1|B2|A)$")
CLASSIFICATION = re.compile(r"^[A-H][0-9]{2}[A-Z][0-9]{0,4}(?:/[0-9]{1,6})?$")

TOPICS = {
    "共通モード": ("common mode", "common-mode"),
    "差動モード": ("differential mode", "differential-mode"),
    "チョーク・リアクトル": ("choke", "reactor", "inductor"),
    "コンデンサ": ("capacitor", "capacitive"),
    "モータ駆動": ("motor", "drive"),
    "インバータ": ("inverter", "power conversion"),
    "アクティブ抑制": ("active damping", "active filter", "cancell", "feedback"),
    "EMI・ノイズ": ("noise", "emi", "interference", "harmonic"),
    "直流側": ("dc-side", "dc side", "dc link"),
    "交流出力": ("output filter", "inverter output", "three-phase"),
}

class PublicMetadata(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta = {}
        self.props = Counter()
        self.codes = []
        self._code_level = 0
        self._code_parts = []
        self._code_tag = None
        self._abstract_level = 0
        self._abstract_parts = []
        self._abstract_tag = None
        self._all_tags = []

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if tag == "meta":
            name = d.get("name") or d.get("property")
            if name in ("DC.title", "DC.date", "DC.contributor",
                        "DC.relation", "citation_patent_number"):
                self.meta.setdefault(name, []).append(d.get("content", ""))
        item = d.get("itemprop")
        if item:
            self.props[item] += 1
        if self._code_level:
            self._code_level += 1
        elif item == "Code":
            self._code_level = 1
            self._code_parts = []
        if self._abstract_level:
            self._abstract_level += 1
        elif item == "abstract":
            self._abstract_level = 1
            self._abstract_parts = []
        if tag in ("meta", "link", "img", "input", "br", "hr", "source", "wbr", "area"):
            if self._code_level:
                self._code_level -= 1
            if self._abstract_level:
                self._abstract_level -= 1

    def handle_endtag(self, tag):
        if self._code_level:
            self._code_level -= 1
            if self._code_level == 0:
                value = re.sub(r"\s+", "", "".join(self._code_parts)).upper()
                if CLASSIFICATION.fullmatch(value):
                    self.codes.append(value)
        if self._abstract_level:
            self._abstract_level -= 1
        if self._abstract_level == 0 and self._abstract_parts:
            self.abstract = " ".join(self._abstract_parts)[:2500]
            self._abstract_parts = []

    def handle_data(self, data):
        if self._code_level and sum(map(len, self._code_parts)) < 80:
            self._code_parts.append(data)
        if self._abstract_level and sum(map(len, self._abstract_parts)) < 2500:
            self._abstract_parts.append(data)


def parse_one(identifier, html):
    if not ALLOWED_ID.fullmatch(identifier):
        raise ValueError("unapproved public patent number")
    if not isinstance(html, bytes) or len(html) > MAX_HTML:
        raise ValueError("public patent page exceeds cap")
    parser = PublicMetadata()
    parser.feed(html.decode("utf-8", "replace"))
    title = (parser.meta.get("DC.title") or [""])[0]
    if not title.strip() or len(title) > 1000:
        raise ValueError("title missing or invalid")
    dates = parser.meta.get("DC.date", [])
    published = dates[-1] if dates else ""
    contributors = list(dict.fromkeys(c.strip() for c in parser.meta.get("DC.contributor", []) if c.strip()))
    codes = list(dict.fromkeys(parser.codes))
    # "DC.relation" mixes patent family citations; no legal inference is made.
    references = [r for r in parser.meta.get("DC.relation", []) if re.match(r"^[A-Z]{2,3}:",r)]
    related_countries = set(x.split(":",1)[0] for x in references)
    # Rule-based indicators, NOT verified patent claim scope or technical effect.
    searchable = (title + " " + getattr(parser, "abstract", "")).lower()
    topics = [topic for topic, patterns in TOPICS.items() if any(p in searchable for p in patterns)]
    return {
        "publication": identifier,
        "url": BASE + identifier + "/en",
        "title": title[:320],
        "publication_date": published[:10],
        "first_dc_date": dates[0][:10] if dates else "",
        "country": identifier[:2],
        "kind": re.search(r"(A1|A2|B1|B2|A)$", identifier).group(1),
        "dc_contributors_sample_unverified": contributors[:3],
        "classifications": codes[:40],
        "subclass_codes": list(dict.fromkeys(x[:4] for x in codes))[:20],
        "classification_count_capped": len(codes),
        "references_metadata_count": len(references),
        "related_reference_countries": sorted(related_countries),
        "forward_reference_rows": parser.props["forwardReferencesFamily"],
        "backward_reference_rows": parser.props["backwardReferencesOrig"],
        "figure_thumbnail_rows": parser.props["thumbnail"],
        "family_country_rows": parser.props["countryStatus"],
        "topic_indicators": topics,
        "source_sha256": hashlib.sha256(html).hexdigest(),
        "html_bytes": len(html),
        "limitations": "DC.contributor may mix people and organizations; DC.relation and figure/family counts are UI-derived proxies; not patent claims or legal citations",
    }


def download_once(identifier, robots):
    if not ALLOWED_ID.fullmatch(identifier):
        raise ValueError("identifier not on allowlist")
    url = BASE + identifier + "/en"
    if not robots.can_fetch(USER_AGENT, url):
        raise ValueError("robots disallows patent URL")
    request = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT, "Accept-Encoding": "identity",
    })
    with urllib.request.urlopen(request, timeout=35) as response:
        if response.status != 200 or response.url != url:
            raise ValueError("public page status or redirect not allowed")
        if response.headers.get("Content-Type", "").split(";")[0].strip() != "text/html":
            raise ValueError("public patent page is not HTML")
        html = response.read(MAX_HTML + 1)
    return parse_one(identifier, html)


def collect():
    robots = urllib.robotparser.RobotFileParser("https://patents.google.com/robots.txt")
    robots.read()
    records = []
    errors = []
    for i, identifier in enumerate(PUBLIC_IDS[:MAX_RECORDS]):
        if i:
            time.sleep(PACING_SEC)
        try:
            row = download_once(identifier, robots)
            records.append(row)
            print("SAMPLE_RESULT=" + json.dumps(row, ensure_ascii=False, separators=(",", ":")), flush=True)
        except (ValueError, urllib.error.URLError, TimeoutError, OSError) as err:
            errors.append({"publication": identifier, "error_type": type(err).__name__})
            print("SAMPLE_SKIP=" + identifier + " " + type(err).__name__, flush=True)
    return {"sample_type": "manual_pinned_public_patents", "retrieved_on": str(date.today()),
            "source": "Google Patents public individual document view (not bulk data)",
            "records": records, "errors": errors,
            "limitations": "purposive sample, not representative; no LLM; no claims or private data",
            "automatic_refresh": False}


def chart_report(records):
    """Render the ten pilot metrics from either live or archived metadata."""
    if not records:
        raise ValueError("no publications to chart")
    sections = []
    def section(title, rows):
        rows = list(rows)
        maximum = max([1] + [value for label, value in rows])
        bars = ''.join(
            f'<li>{escape(str(label))} <meter min="0" max="{maximum}" '
            f'value="{value}"></meter> {value}</li>' for label, value in rows)
        sections.append(f'<section><h2>{escape(title)}</h2><ul>{bars}</ul></section>')

    for title, field in [('公開年', 'publication_date'), ('公開国・機関', 'country'),
                         ('公報種別', 'kind'), ('サブクラス別公報数', 'subclass_codes')]:
        counts = Counter()
        for row in records:
            value = row[field]
            if field == 'publication_date':
                value = value[:4] or '不明'
            counts.update(set(value) if isinstance(value, list) else [value])
        section(title, sorted(counts.items()) if field == 'publication_date' else counts.most_common())

    for title, field, alias in [
            ('ページ表示分類コード数', 'classification_count', 'classification_count_capped'),
            ('関連文献メタデータ数', 'dc_relation_count', 'references_metadata_count'),
            ('後続参照の表示行数', 'forward_reference_rows', None),
            ('図面サムネイル表示数', 'figure_thumbnail_rows', None),
            ('ファミリー関連国の表示行数', 'family_country_rows', None)]:
        values = [(row['publication'], row[field] if field in row else row[alias]) for row in records]
        section(title, sorted(values, key=lambda item: (-item[1], item[0])))
    topics = Counter(topic for row in records for topic in dict.fromkeys(row['topic_indicators']))
    section('タイトル・要約のキーワード一致公報数', topics.most_common())
    return ('<!doctype html><html lang="ja"><meta charset="utf-8"><title>公開公報の集計</title>'
            '<h1>公開公報の集計</h1>'
            f'<p>対象 {len(records)} 公報。選定標本のページ表示値とキーワード一致数。'
            '方式の普及率、正式な引用数、有効国数、減衰性能は評価対象外。</p>'
            + ''.join(sections) + '</html>')


def main():
    cli = argparse.ArgumentParser()
    cli.add_argument("--fetch", action="store_true", help="explicit single-run public download")
    cli.add_argument("--input", type=Path, help="offline metadata JSON for reproducible charts")
    cli.add_argument("--output", type=Path, required=True)
    cli.add_argument("--chart-report", type=Path, help="also write ten offline HTML charts")
    opts = cli.parse_args()
    paths = [p.resolve() for p in (opts.input, opts.output, opts.chart_report) if p]
    if opts.chart_report and opts.chart_report.resolve() in paths[:-1]:
        raise SystemExit("use a separate chart report path")
    if opts.fetch == bool(opts.input):
        raise SystemExit("choose exactly one of --fetch or --input")
    result = collect() if opts.fetch else json.loads(opts.input.read_text("utf-8"))
    if not isinstance(result, dict) or not isinstance(result.get("records"), list):
        raise SystemExit("invalid source sample")
    opts.output.parent.mkdir(parents=True, exist_ok=True)
    opts.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if opts.chart_report:
        opts.chart_report.parent.mkdir(parents=True, exist_ok=True)
        opts.chart_report.write_text(chart_report(result["records"]), encoding="utf-8")
    print("SAMPLE_TOTAL=" + str(len(result["records"])), flush=True)


if __name__ == "__main__":
    main()
