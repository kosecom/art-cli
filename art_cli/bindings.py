"""Explicit data bindings for native handles returned by prior batch steps."""
import json


def reference(value):
    if not isinstance(value,dict) or '$art_ref' not in value:return None
    if set(value)!={'$art_ref'} or not isinstance(value['$art_ref'],str):raise ValueError('Invalid $art_ref object')
    index,sep,pointer=value['$art_ref'].partition(':')
    if sep!=':' or not index.isascii() or not index.isdigit() or (pointer and not pointer.startswith('/')):raise ValueError('$art_ref must be step-index:JSON-pointer')
    return int(index),pointer


def preflight(value,before):
    ref=reference(value)
    if ref:
        if ref[0]>=before:raise ValueError('$art_ref may reference only a previous batch step')
    elif isinstance(value,dict):
        for item in value.values():preflight(item,before)
    elif isinstance(value,list):
        for item in value:preflight(item,before)


def payload(native):
    if not isinstance(native,dict):return native
    if 'structuredContent' in native:return native['structuredContent']
    texts=[c.get('text') for c in native.get('content',[]) if c.get('type')=='text']
    if len(texts)==1:
        try:return json.loads(texts[0])
        except (TypeError,ValueError):pass
    return native


def resolve(value,steps):
    ref=reference(value)
    if ref:
        index,pointer=ref
        if index>=len(steps):raise ValueError('$art_ref step has not completed')
        current=payload(steps[index]['result'])
        if pointer:
            for part in pointer[1:].split('/'):
                part=part.replace('~1','/').replace('~0','~')
                try:current=current[int(part)] if isinstance(current,list) else current[part]
                except (ValueError,KeyError,IndexError,TypeError):raise ValueError('$art_ref JSON pointer does not exist') from None
        return current
    if isinstance(value,dict):return {k:resolve(v,steps) for k,v in value.items()}
    if isinstance(value,list):return [resolve(v,steps) for v in value]
    return value
