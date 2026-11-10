"""External data connectors (official APIs / feeds only), each bounded in size and count.

Every connector returns a list of document dicts ready for Store.add_documents.
* gdelt  : GDELT DOC 2.0 ArtList (free, no key, ~3 month window, ~1 request / 5 s)
* rss    : RSS 2.0 / Atom feeds (titles, summaries, links)
* epo_ops: EPO Open Patent Services 3.2 (free up to 4 GB/week, registration: key + secret)
* jpo    : JPO 特許情報取得API (registration: id + password). Endpoints are configurable; experimental.
* uspto  : USPTO Open Data Portal (API key). Experimental.
"""
import base64
import ipaddress
import json
import logging
import re
import socket
import time
import urllib.parse
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

LOG = logging.getLogger("qnaplibrary.connectors")
MAX_BYTES = 8 * 1024 * 1024
UA = "QnapLibrary/0.1 (+https://github.com/souten-yd/QnapLibrary)"
_last_call = {}


class ConnectorError(RuntimeError):
    pass


def _public_host(url):
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ConnectorError("http(s) URL が必要です")
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80))
    except socket.gaierror:
        raise ConnectorError("ホスト名を解決できません: %s" % parts.hostname)
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise ConnectorError("内部アドレスへの取得は禁止されています")


def http_get(url, headers=None, timeout=30, data=None, method=None, check_public=True, pace=0.0):
    if check_public:
        _public_host(url)
    host = urllib.parse.urlsplit(url).hostname
    if pace:
        wait = pace - (time.time() - _last_call.get(host, 0))
        if wait > 0:
            time.sleep(min(wait, 10))
    _last_call[host] = time.time()
    h = {"User-Agent": UA, "Accept": "*/*"}
    h.update(headers or {})
    req = urllib.request.Request(url, headers=h, data=data, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as error:
        raise ConnectorError("HTTP %d: %s" % (error.code, error.read(300).decode("utf-8", "replace")))
    except (urllib.error.URLError, OSError) as error:
        raise ConnectorError("接続できません: %s" % getattr(error, "reason", error))
    if len(raw) > MAX_BYTES:
        raise ConnectorError("応答が大きすぎます")
    return raw


def _strip_html(text):
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text or "", flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    return re.sub(r"\s+", " ", text).strip()


# GDELT ---------------------------------------------------------------------
def gdelt(query, timespan="1w", max_records=75, lang=""):
    q = query + (" sourcelang:%s" % lang if lang else "")
    params = urllib.parse.urlencode({"query": q, "mode": "ArtList", "format": "json",
                                     "maxrecords": max(1, min(int(max_records), 250)), "timespan": timespan,
                                     "sort": "DateDesc"})
    raw = http_get("https://api.gdeltproject.org/api/v2/doc/doc?" + params, pace=5.5)
    try:
        data = json.loads(raw.decode("utf-8", "replace") or "{}")
    except ValueError:
        raise ConnectorError("GDELT: %s" % raw[:200].decode("utf-8", "replace"))
    docs = []
    for a in data.get("articles", []):
        docs.append({"id": a.get("url"), "title": a.get("title", ""), "url": a.get("url", ""),
                     "source": a.get("domain", ""), "date": _gdelt_date(a.get("seendate", "")),
                     "body": a.get("title", ""),
                     "meta": {"language": a.get("language"), "country": a.get("sourcecountry"), "query": query}})
    return docs


def _gdelt_date(s):
    m = re.match(r"(\d{4})(\d{2})(\d{2})", s or "")
    return "%s-%s-%s" % m.groups() if m else ""


# RSS / Atom ----------------------------------------------------------------
def rss(url, limit=100):
    raw = http_get(url)
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as error:
        raise ConnectorError("フィードを解析できません: %s" % error)
    docs = []
    ns = {"a": "http://www.w3.org/2005/Atom"}
    items = root.findall(".//item") or root.findall(".//a:entry", ns)
    for it in items[:limit]:
        def t(tag):
            el = it.find(tag) if ":" not in tag else it.find(tag, ns)
            return (el.text or "").strip() if el is not None and el.text else ""
        link = t("link")
        if not link:
            el = it.find("a:link", ns)
            link = el.get("href", "") if el is not None else ""
        title = t("title") or t("a:title")
        summary = _strip_html(t("description") or t("a:summary") or t("a:content"))
        date = t("pubDate") or t("a:updated") or t("a:published")
        docs.append({"id": link or title, "title": title, "url": link, "source": urllib.parse.urlsplit(url).hostname,
                     "date": date[:32], "body": summary, "meta": {"feed": url}})
    return docs


# EPO OPS -------------------------------------------------------------------
_epo_token = {"value": None, "exp": 0}


def _epo_auth(key, secret):
    if _epo_token["value"] and _epo_token["exp"] > time.time() + 30:
        return _epo_token["value"]
    basic = base64.b64encode(("%s:%s" % (key, secret)).encode()).decode()
    raw = http_get("https://ops.epo.org/3.2/auth/accesstoken", data=b"grant_type=client_credentials", method="POST",
                   headers={"Authorization": "Basic " + basic, "Content-Type": "application/x-www-form-urlencoded"})
    data = json.loads(raw.decode())
    _epo_token["value"] = data["access_token"]
    _epo_token["exp"] = time.time() + int(data.get("expires_in", 1200))
    return _epo_token["value"]


def epo_search(cql, key, secret, limit=25):
    """Search published-data with CQL (e.g. 'ta=battery and pd>=2020') and fetch biblio+abstract."""
    if not key or not secret:
        raise ConnectorError("EPO OPS の Consumer Key / Secret が未設定です")
    token = _epo_auth(key, secret)
    limit = max(1, min(int(limit), 100))
    url = "https://ops.epo.org/3.2/rest-services/published-data/search/biblio?" + urllib.parse.urlencode(
        {"q": cql, "Range": "1-%d" % limit})
    raw = http_get(url, headers={"Authorization": "Bearer " + token, "Accept": "application/json"}, pace=1.0)
    data = json.loads(raw.decode())
    return _epo_docs(data)


def _epo_docs(data):
    def as_list(x):
        return x if isinstance(x, list) else ([x] if x else [])

    def txt(x):
        if isinstance(x, dict):
            return x.get("$", "")
        if isinstance(x, list):
            return " ".join(txt(i) for i in x)
        return str(x or "")
    docs = []
    try:
        results = data["ops:world-patent-data"]["ops:biblio-search"]["ops:search-result"]["exchange-documents"]
    except (KeyError, TypeError):
        return docs
    for ed in as_list(results):
        d = ed.get("exchange-document", {})
        pn = "%s%s%s" % (d.get("@country", ""), d.get("@doc-number", ""), d.get("@kind", ""))
        bib = d.get("bibliographic-data", {})
        titles = as_list(bib.get("invention-title"))
        title = next((txt(t) for t in titles if t.get("@lang") == "ja"), None) or (txt(titles[0]) if titles else pn)
        abstract = " ".join(txt(a.get("p")) for a in as_list(d.get("abstract")))
        parties = bib.get("parties", {})
        applicants = [txt(a.get("applicant-name", {}).get("name")) for a in as_list(parties.get("applicants", {}).get("applicant"))
                      if a.get("@data-format") == "epodoc"]
        ipc = [txt(c.get("text")).strip() for c in as_list(bib.get("classifications-ipcr", {}).get("classification-ipcr"))]
        pub = as_list(bib.get("publication-reference", {}).get("document-id"))
        date = next((txt(p.get("date")) for p in pub if p.get("date")), "")
        docs.append({"id": pn, "title": title, "url": "https://worldwide.espacenet.com/patent/search?q=pn%3D" + pn,
                     "source": "EPO OPS", "date": ("%s-%s-%s" % (date[:4], date[4:6], date[6:8])) if len(date) == 8 else date,
                     "abstract": abstract, "body": abstract,
                     "meta": {"publication_number": pn, "applicants": applicants, "ipc": ipc, "office": d.get("@country", "")}})
    return docs


# JPO 特許情報取得API (experimental) -----------------------------------------
_jpo_token = {"value": None, "exp": 0}


def jpo_progress(application_number, username, password, base_url="https://ip-data.jpo.go.jp"):
    """Fetch application progress (経過情報) JSON. Endpoint paths follow the published spec and may change."""
    if not username or not password:
        raise ConnectorError("JPO 特許情報取得API の ID / パスワードが未設定です（特許庁へ利用登録が必要）")
    if not _jpo_token["value"] or _jpo_token["exp"] < time.time() + 30:
        body = urllib.parse.urlencode({"grant_type": "password", "username": username, "password": password}).encode()
        raw = http_get(base_url.rstrip("/") + "/auth/token", data=body, method="POST",
                       headers={"Content-Type": "application/x-www-form-urlencoded"})
        tok = json.loads(raw.decode())
        _jpo_token["value"] = tok.get("access_token")
        _jpo_token["exp"] = time.time() + int(tok.get("expires_in", 3000))
    appno = re.sub(r"\D", "", application_number)
    raw = http_get(base_url.rstrip("/") + "/api/patent/v1/app_progress/" + appno,
                   headers={"Authorization": "Bearer " + _jpo_token["value"]}, pace=1.0)
    data = json.loads(raw.decode())
    result = data.get("result", {}).get("data", data)
    title = result.get("inventionTitle") or "特願" + appno
    return [{"id": "JP" + appno, "title": title, "source": "JPO API",
             "url": "https://www.j-platpat.inpit.go.jp/", "body": json.dumps(result, ensure_ascii=False)[:200000],
             "meta": {"application_number": appno, "raw_kind": "app_progress"}}]


# USPTO ODP (experimental) --------------------------------------------------
def uspto_search(query, api_key, limit=25):
    if not api_key:
        raise ConnectorError("USPTO ODP の API キーが未設定です")
    url = "https://api.uspto.gov/api/v1/patent/applications/search?" + urllib.parse.urlencode(
        {"q": query, "limit": max(1, min(int(limit), 100))})
    raw = http_get(url, headers={"X-API-KEY": api_key, "Accept": "application/json"}, pace=1.0)
    data = json.loads(raw.decode())
    docs = []
    for item in data.get("patentFileWrapperDataBag", []):
        meta = item.get("applicationMetaData", {})
        appno = item.get("applicationNumberText", "")
        docs.append({"id": "US" + appno, "title": meta.get("inventionTitle", appno), "source": "USPTO ODP",
                     "url": "https://data.uspto.gov/patent-file-wrapper/search/details/%s" % appno,
                     "date": meta.get("filingDate", ""), "body": meta.get("inventionTitle", ""),
                     "meta": {"application_number": appno, "status": meta.get("applicationStatusDescriptionText"),
                              "patent_number": meta.get("patentNumber")}})
    return docs


# e-Stat (政府統計) ---------------------------------------------------------
def estat(query, app_id, limit=50):
    if not app_id:
        raise ConnectorError("e-Stat のアプリケーションIDが未設定です（e-stat.go.jp で無料登録）")
    url = "https://api.e-stat.go.jp/rest/3.0/app/json/getStatsList?" + urllib.parse.urlencode(
        {"appId": app_id, "searchWord": query, "limit": max(1, min(int(limit), 100)), "lang": "J"})
    data = json.loads(http_get(url, pace=1.0).decode("utf-8"))
    root = data.get("GET_STATS_LIST", {})
    err = root.get("RESULT", {})
    if str(err.get("STATUS", "0")) not in ("0", "1"):
        raise ConnectorError("e-Stat: %s" % err.get("ERROR_MSG"))
    tables = (root.get("DATALIST_INF") or {}).get("TABLE_INF") or []
    if isinstance(tables, dict):
        tables = [tables]

    def txt(v):
        return v.get("$", "") if isinstance(v, dict) else str(v or "")
    docs = []
    for t in tables:
        tid = t.get("@id", "")
        title = txt(t.get("TITLE")) or txt(t.get("STATISTICS_NAME"))
        stat = txt(t.get("STAT_NAME"))
        docs.append({"id": "estat:" + tid, "title": "%s %s" % (stat, title), "source": "e-Stat",
                     "url": "https://www.e-stat.go.jp/dbview?sid=%s" % tid, "date": _date8(str(t.get("OPEN_DATE", ""))),
                     "body": " / ".join(filter(None, [stat, title, txt(t.get("GOV_ORG")), txt(t.get("MAIN_CATEGORY")),
                                                     txt(t.get("SUB_CATEGORY")), "調査年月 " + str(t.get("SURVEY_DATE", ""))])),
                     "meta": {"stats_data_id": tid, "gov_org": txt(t.get("GOV_ORG")), "cycle": t.get("CYCLE"),
                              "survey_date": t.get("SURVEY_DATE"), "category": txt(t.get("MAIN_CATEGORY"))}})
    return docs


def _date8(s):
    s = s.replace("-", "")
    return "%s-%s-%s" % (s[:4], s[4:6], s[6:8]) if len(s) >= 8 and s[:8].isdigit() else ""


# EDINET (有価証券報告書等の提出書類一覧) -------------------------------------
def edinet(date, api_key, query=""):
    if not api_key:
        raise ConnectorError("EDINET API キーが未設定です（EDINET の API 利用登録で無料取得）")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date or ""):
        raise ConnectorError("date は YYYY-MM-DD")
    url = "https://api.edinet-fsa.go.jp/api/v2/documents.json?" + urllib.parse.urlencode(
        {"date": date, "type": 2, "Subscription-Key": api_key})
    data = json.loads(http_get(url, pace=1.0).decode("utf-8"))
    if data.get("metadata", {}).get("status") not in (None, "200", 200):
        raise ConnectorError("EDINET: %s" % data.get("metadata", {}).get("message"))
    docs = []
    for r in data.get("results") or []:
        name, desc = r.get("filerName") or "", r.get("docDescription") or ""
        if query and query not in name and query not in desc:
            continue
        docs.append({"id": "edinet:" + r.get("docID", ""), "title": "%s %s" % (name, desc), "source": "EDINET",
                     "url": "https://disclosure2.edinet-fsa.go.jp/WZEK0040.aspx?%s" % r.get("docID", ""),
                     "date": (r.get("submitDateTime") or "")[:10], "body": "%s %s" % (name, desc),
                     "meta": {"doc_id": r.get("docID"), "edinet_code": r.get("edinetCode"), "sec_code": r.get("secCode"),
                              "doc_type": r.get("docTypeCode"), "filer": name}})
    return docs


# SEC EDGAR (米国企業の提出書類) -------------------------------------------
def sec_filings(cik, user_agent, forms="10-K,10-Q,8-K", limit=40):
    if not user_agent or "@" not in user_agent:
        raise ConnectorError("SEC は連絡先付き User-Agent が必須です（設定 connectors.sec_user_agent に「名前 メール」）")
    cik = re.sub(r"\D", "", str(cik or ""))
    if not cik:
        raise ConnectorError("CIK（数字）が必要です")
    data = json.loads(http_get("https://data.sec.gov/submissions/CIK%010d.json" % int(cik),
                               headers={"User-Agent": user_agent}, pace=0.2).decode("utf-8"))
    name = data.get("name", "")
    recent = (data.get("filings") or {}).get("recent") or {}
    wanted = {f.strip().upper() for f in (forms or "").split(",") if f.strip()}
    docs = []
    for i, form in enumerate(recent.get("form", [])):
        if wanted and form.upper() not in wanted:
            continue
        acc = recent["accessionNumber"][i]
        prim = recent.get("primaryDocument", [""])[i]
        docs.append({"id": "sec:" + acc, "title": "%s %s %s" % (name, form, recent.get("primaryDocDescription", [""])[i] or ""),
                     "source": "SEC EDGAR", "date": recent.get("filingDate", [""])[i],
                     "url": "https://www.sec.gov/Archives/edgar/data/%d/%s/%s" % (int(cik), acc.replace("-", ""), prim),
                     "body": "%s %s %s" % (name, form, recent.get("primaryDocDescription", [""])[i] or ""),
                     "meta": {"cik": cik, "form": form, "company": name, "tickers": data.get("tickers")}})
        if len(docs) >= int(limit):
            break
    return docs


CATALOG = [
    {"id": "gdelt", "label": "GDELT 世界ニュース", "kind": "news", "key": None,
     "params": [{"name": "query", "label": "検索語（英語推奨, 例: semiconductor export）"},
                {"name": "timespan", "label": "期間 (1d/1w/1m/3m)", "default": "1w"},
                {"name": "max_records", "label": "最大件数", "default": 75}],
     "note": "無料・キー不要。直近3か月。見出しとURLを保存（本文は配信元で確認）。"},
    {"id": "rss", "label": "RSS / Atom フィード", "kind": "news", "key": None,
     "params": [{"name": "url", "label": "フィードURL"}], "note": "官公庁・企業・学会のお知らせ等。"},
    {"id": "epo_ops", "label": "EPO OPS（世界の特許書誌・要約）", "kind": "patent", "key": ["epo_ops_key", "epo_ops_secret"],
     "params": [{"name": "query", "label": "CQL（例: ta=\"solid electrolyte\" and pd>=2020）"},
                {"name": "limit", "label": "最大件数", "default": 25}],
     "note": "無料（4GB/週まで）。developers.epo.org で登録しキーを設定。"},
    {"id": "jpo", "label": "JPO 特許情報取得API（経過情報）", "kind": "patent", "key": ["jpo_username", "jpo_password"],
     "params": [{"name": "application_number", "label": "出願番号（例: 2023-123456）"}],
     "note": "特許庁への利用登録が必要（試行提供・回数上限あり）。実験的。"},
    {"id": "uspto", "label": "USPTO Open Data Portal", "kind": "patent", "key": ["uspto_api_key"],
     "params": [{"name": "query", "label": "検索語"}, {"name": "limit", "label": "最大件数", "default": 25}],
     "note": "data.uspto.gov で API キー取得。実験的。"},
    {"id": "estat", "label": "e-Stat（政府統計の表一覧）", "kind": "market", "key": ["estat_app_id"],
     "params": [{"name": "query", "label": "検索語（例: 半導体 生産）"}, {"name": "limit", "label": "最大件数", "default": 50}],
     "note": "e-stat.go.jp で無料のアプリケーションID登録が必要。表の名称・調査年月・URL を保存。"},
    {"id": "edinet", "label": "EDINET（有価証券報告書などの提出一覧）", "kind": "market", "key": ["edinet_api_key"],
     "params": [{"name": "date", "label": "提出日 YYYY-MM-DD"}, {"name": "query", "label": "会社名・書類名で絞り込み（任意）"}],
     "note": "EDINET の API 利用登録（無料）でキーを取得。"},
    {"id": "sec", "label": "SEC EDGAR（米国企業の提出書類）", "kind": "market", "key": None,
     "params": [{"name": "cik", "label": "CIK（例: 320193）"}, {"name": "forms", "label": "書類種別", "default": "10-K,10-Q,8-K"}],
     "note": "キー不要。設定 connectors.sec_user_agent に「名前 メールアドレス」が必要（SEC の規則）。"},
]


def run(connector_id, params, secrets, settings=None):
    p = params or {}
    settings = settings or {}
    if connector_id == "gdelt":
        if not p.get("query"):
            raise ConnectorError("query が必要です")
        return gdelt(p["query"], p.get("timespan") or "1w", p.get("max_records") or 75, p.get("lang") or "")
    if connector_id == "rss":
        return rss(p.get("url", ""))
    if connector_id == "epo_ops":
        return epo_search(p.get("query", ""), secrets("epo_ops_key"), secrets("epo_ops_secret"), p.get("limit") or 25)
    if connector_id == "jpo":
        return jpo_progress(p.get("application_number", ""), secrets("jpo_username"), secrets("jpo_password"),
                            p.get("base_url") or "https://ip-data.jpo.go.jp")
    if connector_id == "uspto":
        return uspto_search(p.get("query", ""), secrets("uspto_api_key"), p.get("limit") or 25)
    if connector_id == "estat":
        return estat(p.get("query", ""), secrets("estat_app_id"), p.get("limit") or 50)
    if connector_id == "edinet":
        return edinet(p.get("date", ""), secrets("edinet_api_key"), p.get("query") or "")
    if connector_id == "sec":
        return sec_filings(p.get("cik"), settings.get("sec_user_agent", ""), p.get("forms") or "10-K,10-Q,8-K")
    raise ConnectorError("unknown connector")
