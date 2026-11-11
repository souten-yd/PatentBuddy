"""Pure, bounded candidate snapshots and reversible selection. No network or writes."""
import hashlib
import json
import re
from .store import StoreError


def _text(value, limit):
    if not isinstance(value, str) or not value.strip() or len(value)>limit:
        raise StoreError('invalid candidate text')
    return value


def snapshot(records):
    if not isinstance(records, list) or len(records)>2000:
        raise StoreError('candidate snapshot limit is 2000 records')
    merged = {}
    for row in records:
        if not isinstance(row, dict) or set(row) != {'publication','language','family','title','sources','cells'}:
            raise StoreError('invalid candidate fields')
        number=_text(row['publication'],32).upper()
        if not re.fullmatch('[A-Z]{2}[0-9]{4,16}[A-Z][0-9]?',number):
            raise StoreError('invalid publication number')
        language=_text(row['language'],16).lower()
        if not re.fullmatch('[a-z]{2,3}(?:-[a-z]{2,4})?',language):
            raise StoreError('invalid candidate language')
        family=row['family']
        if family is not None:_text(family,128)
        title=_text(row['title'],500)
        sources=row['sources'];cells=row['cells']
        if not isinstance(sources,list) or not 1<=len(sources)<=10 or not isinstance(cells,list) or len(cells)>16:
            raise StoreError('invalid candidate source or cell count')
        # Source identifiers are provenance, not arbitrary executable download URLs.
        sources=sorted(set(_text(s,200) for s in sources))
        cells=sorted(set(_text(c,120) for c in cells)) or ['unclassified']
        key=number+':'+language
        old=merged.get(key)
        if old:
            if old['family'] is not None and family is not None and old['family']!=family:
                raise StoreError('conflicting family identifiers require resolution')
            old['family']=old['family'] or family
            old['titles']=sorted(set(old['titles']+[title]))
            old['sources']=sorted(set(old['sources']+sources))
            old['cells']=sorted(set(old['cells']+cells))
            if len(old['sources'])>10 or len(old['cells'])>16 or len(old['titles'])>10:
                raise StoreError('merged candidate exceeds limits')
        else:
            merged[key]=dict(id=key,publication=number,language=language,family=family,titles=[title],sources=sources,cells=cells)
    items=[merged[k] for k in sorted(merged)]
    digest=hashlib.sha256(json.dumps(items,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
    return {'revision':digest,'items':items,'input_count':len(records),'unique_publications':len(items)}


def select(state, revision, masked_cells, pinned, selected, limit=10):
    """Return a preview; over-budget plans stay blocked, never silently trimmed."""
    if revision!=state['revision']:
        raise StoreError('candidate snapshot changed; review selection again')
    if type(limit) is not int or not 1<=limit<=100:
        raise StoreError('download count limit must be 1..100')
    for values in (masked_cells,pinned,selected):
        if not isinstance(values,list) or len(values)>2000 or any(not isinstance(v,str) for v in values) or len(set(values))!=len(values):
            raise StoreError('invalid selection list')
    by_id={r['id']:r for r in state['items']}
    known_cells={c for r in state['items'] for c in r['cells']}
    if set(masked_cells)-known_cells or (set(pinned)|set(selected))-by_id.keys():
        raise StoreError('selection references unknown candidates or cells')
    masks=set(masked_cells);pins=set(pinned)
    # A cross-classified item survives while any of its cells remains visible.
    hidden={r['id'] for r in state['items'] if set(r['cells'])<=masks}
    chosen=set(selected)|pins
    conflict=sorted(chosen & hidden)
    reasons=[]
    if conflict:reasons.append('selected_or_pinned_is_masked')
    if len(chosen)>limit:reasons.append('count_limit_exceeded')
    if not chosen:reasons.append('empty_selection')
    counts={c:sum(c in r['cells'] for r in state['items']) for c in sorted(known_cells)}
    families={('known',by_id[k]['family']) if by_id[k]['family'] is not None else ('unknown',k) for k in chosen}
    return dict(revision=revision,selected=sorted(chosen),hidden=sorted(hidden),conflicts=conflict,
                selected_count=len(chosen),selected_families=len(families),visible_count=len(by_id)-len(hidden),
                cells=counts,limit=limit,count_budget_ok=not reasons,blocking_reasons=reasons,
                download_ready=False)  # byte budget, provider and queue approval are separate gates
