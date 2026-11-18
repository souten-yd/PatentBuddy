"""Front-page classification mentions for manual comparison with the PDF and WIPO list."""
import re
import unicodedata

from .official_ipc import EDITION

CODE = re.compile(r'(?<![A-Za-z0-9])([A-H])([0-9O]{2})([A-Z])[ \t]*([0-9]{1,4}/[0-9]{1,6})(?![A-Za-z0-9/])')


def candidates(store, pages):
    page = pages[0] if pages else {}
    results = []
    seen = set()
    for field, source in [('native_text', 'pdf_text'), ('ocr_text', 'ocr')]:
        text = page.get(field)
        if not isinstance(text, str):
            continue
        for match in CODE.finditer(unicodedata.normalize('NFKC', text)):
            section, digits, subclass, group = match.groups()
            if 'O' in digits and source != 'ocr':
                continue
            raw = match.group()
            if (source, raw) in seen:
                continue
            seen.add((source, raw))
            symbol = section + digits.replace('O', '0') + subclass + group
            results.append(dict(page=1, raw=raw, symbol=symbol, source=source))
            if len(results) == 40:
                break
        if len(results) == 40:
            break
    if results:
        symbols = sorted({row['symbol'] for row in results})
        slots = ','.join('?' for _ in symbols)
        valid = {row[0] for row in store.q(
            f'SELECT symbol FROM official_ipc_symbols WHERE edition=? AND symbol IN ({slots})',
            (EDITION, *symbols))}
        sections = {row[0] for row in store.q(
            'SELECT section FROM official_ipc_catalogs WHERE edition=?', (EDITION,))}
        for row in results:
            symbol = row['symbol']
            row['dictionary'] = ('match' if symbol in valid else
                                 'absent' if symbol[0] in sections else 'unavailable')
            row['edition'] = EDITION
    return results
