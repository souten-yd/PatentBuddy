"""Validate explicit EPO OPS publication scope without user-provided CQL.

The user confirms official IPC candidates, publication office, publication-year
window, and one 25-record page. The title/invention text remains local.
"""
from datetime import date

from .source_planner import accepted_ipc

OFFICES = ("ALL", "JP", "US", "EP", "WO", "CN", "KR", "DE", "FR", "GB")
MAX_EPO_RESULT_INDEX = 2000
MAX_YEAR_SPAN = 10


def build_scope(*, ipc, publication_country="ALL", year_from=None, year_to=None, first=1, limit=25):
    """Create deterministic CQL for EPO published-data search, never Register.

    EPO OPS Reference Guide v1.3.20 (2024), Appendix 4.2:
    'ic' is IPC, 'pn=EP' publication country, 'pd within "yyyyMMdd yyyyMMdd"'.
    """
    expression = accepted_ipc(ipc)
    if type(publication_country) is not str or publication_country not in OFFICES:
        raise ValueError("公開国は選択肢から指定してください")
    if (year_from is None) != (year_to is None):
        raise ValueError("公開年の開始と終了を両方指定してください")
    if year_from is not None:
        current = date.today().year
        if (type(year_from) is not int or type(year_to) is not int
                or not 1900 <= year_from <= year_to <= current
                or year_to - year_from >= MAX_YEAR_SPAN):
            raise ValueError("公開年は1900年以降、最大10暦年で指定してください")
    if type(first) is not int or not 1 <= first <= MAX_EPO_RESULT_INDEX:
        raise ValueError("取得開始位置は1〜2000です")
    if type(limit) is not int or not 1 <= limit <= 25 or first + limit - 1 > MAX_EPO_RESULT_INDEX:
        raise ValueError("1回25件かつEPO最大2000結果の範囲で指定してください")
    if publication_country != "ALL":
        expression += " and pn=" + publication_country
    if year_from is not None:
        expression += ' and pd within "%04d0101 %04d1231"' % (year_from, year_to)
    return {
        "ipc": ipc, "publication_country": publication_country,
        "publication_year_from": year_from, "publication_year_to": year_to,
        "first_result": first, "limit": limit, "last_result": first + limit - 1,
        "cql": expression, "date_basis": "publication_date",
        "search_kind": "EPO_OPS_published_data_bibliographic",
        "query_sends_topic_text": False, "manual_only": True,
    }
