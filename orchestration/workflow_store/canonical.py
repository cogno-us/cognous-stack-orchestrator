"""RFC 8785 subset canonical JSON and strict loading for the workflow store.

Same profile as hub step 2.1 (`tools/registry_records.py`: `jcs_dumps`, `loads_strict`,
`record_digest`). The Orchestrator may not import hub tools, so the small pattern is
restated here; tests pin it to fixed vectors. No floats: a float has more than one
textual form. Standard library only. Non-authorizing.
"""
import hashlib
import json

MAX_SAFE_INT = 2 ** 53 - 1
CANONICAL_PROFILE_NAME = 'rfc8785-jcs'

_ESCAPES = {'"': '\\"', '\\': '\\\\', '\b': '\\b', '\f': '\\f', '\n': '\\n', '\r': '\\r', '\t': '\\t'}


def _jcs_string(value):
    out = []
    for ch in value:
        if ch in _ESCAPES:
            out.append(_ESCAPES[ch])
        elif ord(ch) < 0x20:
            out.append('\\u%04x' % ord(ch))
        else:
            out.append(ch)
    text = '"' + ''.join(out) + '"'
    text.encode('utf-8')  # a lone surrogate is not well-formed JSON text
    return text


def _jcs(value):
    """Canonical text for dict, list, str, bool, None and safe integers; ValueError otherwise."""
    if value is None:
        return 'null'
    if value is True:
        return 'true'
    if value is False:
        return 'false'
    if type(value) is int:
        if abs(value) > MAX_SAFE_INT:
            raise ValueError('integer outside the safe range')
        return str(value)
    if type(value) is str:
        return _jcs_string(value)
    if type(value) is list:
        return '[' + ','.join(_jcs(v) for v in value) + ']'
    if type(value) is dict:
        if any(type(k) is not str for k in value):
            raise ValueError('object keys must be strings')
        keys = sorted(value, key=lambda k: k.encode('utf-16-be', 'surrogatepass'))
        return '{' + ','.join(_jcs_string(k) + ':' + _jcs(value[k]) for k in keys) + '}'
    raise ValueError('type not representable in the profile')


def jcs_dumps(value):
    """Canonical text for dict, list, str, bool, None and safe integers; ValueError otherwise."""
    try:
        return _jcs(value)
    except RecursionError:
        raise ValueError('nesting too deep')


def jcs_bytes(value):
    return jcs_dumps(value).encode('utf-8')


def _decoder():
    def pairs(items):
        keys = [k for k, _ in items]
        if len(set(keys)) != len(keys):
            raise ValueError('duplicate object key')
        return dict(items)

    def no_float(text):
        raise ValueError('floating point numbers are not part of the profile')

    def no_constant(text):
        raise ValueError('non-finite constant')

    return json.JSONDecoder(object_pairs_hook=pairs, parse_float=no_float, parse_constant=no_constant)


def loads_strict(data):
    """Parse JSON refusing duplicate keys, floats and non-finite constants.

    Malformed JSON raises json.JSONDecodeError; a profile violation (duplicate key, float,
    constant, nesting beyond the interpreter's recursion limit) raises a plain ValueError, so
    callers can tell a torn write from a violation.
    """
    if isinstance(data, (bytes, bytearray)):
        data = bytes(data).decode('utf-8')
    try:
        start = json.decoder.WHITESPACE.match(data, 0).end()
        obj, end = _decoder().raw_decode(data, start)
        if data[end:].strip(' \t\r\n'):
            raise json.JSONDecodeError('Extra data', data, end)
        return obj
    except RecursionError:
        raise ValueError('nesting too deep')


def raw_decode_strict(text):
    """Decode one JSON value at the start of text; return (value, end index). Same refusals as loads_strict."""
    try:
        return _decoder().raw_decode(text)
    except RecursionError:
        raise ValueError('nesting too deep')


def sha256_digest(data):
    return 'sha256:' + hashlib.sha256(data).hexdigest()


def object_digest(obj):
    """sha256 over the canonical form of the object without its own `digest` member."""
    body = {k: v for k, v in obj.items() if k != 'digest'}
    return sha256_digest(jcs_bytes(body))
