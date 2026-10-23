"""Durable single-host event store: append-only, hash-chained, restartable. Non-authorizing.

The store persists opaque, schema-checked event records per workflow and returns them in
order. It does not interpret them: no state machine, no verdict, no grant, no pin, no
authority. It reads no clock (timestamps are caller-supplied opaque text), opens no network
connection and starts no subprocess. Standard library only.
"""
import errno
import json
import os
import re
import stat
from dataclasses import dataclass

from .canonical import (CANONICAL_PROFILE_NAME, MAX_SAFE_INT, jcs_bytes, loads_strict,
                        object_digest, sha256_digest)
from .refusal import StoreRefusal



PROFILE = 'ocs-workflow-event/0'
LOCK_PROFILE = 'ocs-workflow-lock/0'
SCHEMA_VERSION = 0

# Event members the store adds; the caller supplies exactly kind, timestamp and body.
EVENT_FIELDS = {'profile', 'schema_version', 'canonical_profile', 'workflow_id', 'sequence',
                'predecessor', 'kind', 'timestamp', 'body', 'digest'}
RECORD_FIELDS = {'kind', 'timestamp', 'body'}
# Refused by name, in an envelope and anywhere in a body: the store holds history, never authority.
FORBIDDEN_MEMBERS = frozenset({'verdict', 'pin', 'grant', 'authority'})

KIND_RE = re.compile(r'^[a-z][a-z0-9_.-]{0,63}\Z')
WORKFLOW_ID_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z')
OWNER_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z')
DIGEST_RE = re.compile(r'^sha256:[0-9a-f]{64}\Z')
EVENT_FILE_RE = re.compile(r'^([0-9]{6})\.json\Z')
RESERVED_KIND_PREFIX = 'store.'
KIND_LOCK_BROKEN = 'store.lock_broken'
KIND_QUARANTINED = 'store.torn_tail_quarantined'

LOCK_NAME = 'LOCK'
QUARANTINE_DIR = 'quarantine'
TMP_PREFIX = '.tmp.'

# Hard ceilings. The caller's Bounds may be lower, never higher.
CEILING_EVENTS = 999999
CEILING_EVENT_BYTES = 1 << 20
CEILING_WORKFLOWS = 100000
MAX_DEPTH = 16
MAX_TEXT = 4096

EVENT_MODE = 0o444
DIR_MODE = 0o700
LOCK_MODE = 0o600


@dataclass(frozen=True)
class Bounds:
    max_events: int = 10000
    max_event_bytes: int = 65536
    max_workflows: int = 1000

    def __post_init__(self):
        for name, ceiling in (('max_events', CEILING_EVENTS), ('max_event_bytes', CEILING_EVENT_BYTES),
                              ('max_workflows', CEILING_WORKFLOWS)):
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= ceiling:
                raise StoreRefusal('bounds_invalid', '%s must be an integer in 1..%d' % (name, ceiling))


DEFAULT_BOUNDS = Bounds()


@dataclass(frozen=True)
class LoadedWorkflow:
    workflow_id: str
    events: tuple
    head_sequence: int
    head_digest: object  # None when the workflow has no events


# --- small helpers ----------------------------------------------------------------------

def _text(value, limit=MAX_TEXT):
    return type(value) is str and bool(value.strip()) and len(value) <= limit


def _check_workflow_id(workflow_id):
    if type(workflow_id) is not str or not WORKFLOW_ID_RE.match(workflow_id):
        raise StoreRefusal('invalid_workflow_id', 'workflow id must match %s' % WORKFLOW_ID_RE.pattern)


def _check_owner(owner):
    if type(owner) is not str or not OWNER_RE.match(owner):
        raise StoreRefusal('invalid_owner', 'owner token must match %s' % OWNER_RE.pattern)


def _fsync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _io(exc, what):
    if exc.errno == errno.ELOOP:
        return StoreRefusal('path_escape', 'symbolic link at %s' % what)
    return StoreRefusal('io_failure', '%s: %s' % (what, exc.strerror or exc.errno))


def _check_workflow_dir(directory):
    """Return the workflow id of a real (non-symlink) directory."""
    path = os.path.normpath(os.fspath(directory))
    workflow_id = os.path.basename(path)
    _check_workflow_id(workflow_id)
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        raise StoreRefusal('workflow_not_found', workflow_id)
    except OSError as exc:
        raise _io(exc, workflow_id)
    if stat.S_ISLNK(st.st_mode):
        raise StoreRefusal('path_escape', 'workflow directory is a symbolic link')
    if not stat.S_ISDIR(st.st_mode):
        raise StoreRefusal('workflow_not_found', 'not a directory')
    return path, workflow_id


def _read_regular(path, limit):
    """Read at most limit bytes of a regular file, refusing symlinks and special files."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        raise StoreRefusal('io_failure', 'missing: %s' % os.path.basename(path), {'missing': True})
    except OSError as exc:
        raise _io(exc, os.path.basename(path))
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise StoreRefusal('unexpected_file', 'not a regular file: %s' % os.path.basename(path))
        if st.st_size > limit:
            raise StoreRefusal('event_too_large', os.path.basename(path), {'size': st.st_size})
        chunks = []
        remaining = st.st_size
        while remaining > 0:
            chunk = os.read(fd, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        return b''.join(chunks)
    finally:
        os.close(fd)


def _write_new_file(path, data, mode):
    """Write data to a new file (exclusive), flush, fsync, then set the final mode."""
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        raise
    try:
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            view = view[written:]
        os.fsync(fd)
        os.fchmod(fd, mode)
    finally:
        os.close(fd)


def _scan_forbidden(value, depth=0):
    if depth > MAX_DEPTH + 2:
        raise StoreRefusal('schema_invalid', 'nesting too deep')
    if type(value) is dict:
        for key, item in value.items():
            if key in FORBIDDEN_MEMBERS:
                raise StoreRefusal('forbidden_member', 'member %r is not accepted in an event' % key)
            _scan_forbidden(item, depth + 1)
    elif type(value) is list:
        for item in value:
            _scan_forbidden(item, depth + 1)


def _check_json_value(value, depth=0):
    if depth > MAX_DEPTH:
        raise StoreRefusal('schema_invalid', 'body nesting exceeds %d' % MAX_DEPTH)
    if value is None or type(value) in (bool, str):
        return
    if type(value) is int:
        if abs(value) > MAX_SAFE_INT:
            raise StoreRefusal('schema_invalid', 'integer outside the safe range')
        return
    if type(value) is list:
        for item in value:
            _check_json_value(item, depth + 1)
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise StoreRefusal('schema_invalid', 'object keys must be strings')
            _check_json_value(item, depth + 1)
        return
    raise StoreRefusal('schema_invalid', 'value type not representable (no floats)')


def check_record(record, *, allow_reserved=False):
    """Validate a caller-supplied record {kind, timestamp, body}; returns it unchanged."""
    _scan_forbidden(record)
    if type(record) is not dict or set(record) != RECORD_FIELDS:
        raise StoreRefusal('schema_invalid', 'exactly kind, timestamp and body are required')
    kind = record['kind']
    if type(kind) is not str or not KIND_RE.match(kind):
        raise StoreRefusal('schema_invalid', 'kind must match %s' % KIND_RE.pattern)
    if kind.startswith(RESERVED_KIND_PREFIX) and not allow_reserved:
        raise StoreRefusal('reserved_kind', 'kinds beginning "store." belong to the store')
    if not _text(record['timestamp'], 64):
        raise StoreRefusal('schema_invalid', 'timestamp must be non-empty opaque text (at most 64 characters)')
    if type(record['body']) is not dict:
        raise StoreRefusal('schema_invalid', 'body must be an object')
    _check_json_value(record['body'])
    try:
        jcs_bytes(record)
    except ValueError as exc:
        raise StoreRefusal('schema_invalid', str(exc))
    return record


def _check_stored_event(event, workflow_id):
    _scan_forbidden(event)
    if type(event) is not dict or set(event) != EVENT_FIELDS:
        raise StoreRefusal('schema_invalid', 'exact event members required')
    if event['profile'] != PROFILE or type(event['schema_version']) is not int \
            or event['schema_version'] != SCHEMA_VERSION or event['canonical_profile'] != CANONICAL_PROFILE_NAME:
        raise StoreRefusal('schema_invalid', 'unsupported profile or schema version')
    if event['workflow_id'] != workflow_id:
        raise StoreRefusal('workflow_id_mismatch', 'event names another workflow')
    seq = event['sequence']
    if type(seq) is not int or not 1 <= seq <= CEILING_EVENTS:
        raise StoreRefusal('schema_invalid', 'sequence form')
    pred = event['predecessor']
    if pred is not None and (type(pred) is not str or not DIGEST_RE.match(pred)):
        raise StoreRefusal('schema_invalid', 'predecessor form')
    if type(event['digest']) is not str or not DIGEST_RE.match(event['digest']):
        raise StoreRefusal('schema_invalid', 'digest form')
    check_record({k: event[k] for k in RECORD_FIELDS}, allow_reserved=True)


def _build_event(workflow_id, sequence, predecessor, record):
    body = loads_strict(jcs_bytes(record['body']))  # detach from the caller's object
    event = {'profile': PROFILE, 'schema_version': SCHEMA_VERSION, 'canonical_profile': CANONICAL_PROFILE_NAME,
             'workflow_id': workflow_id, 'sequence': sequence, 'predecessor': predecessor,
             'kind': record['kind'], 'timestamp': record['timestamp'], 'body': body}
    event['digest'] = object_digest(event)
    return event


def _deep_copy(value):
    return loads_strict(jcs_bytes(value))


# --- scanning and loading ---------------------------------------------------------------

@dataclass
class _Scan:
    path: str
    workflow_id: str
    events: list
    torn: list          # names of a torn final event file (at most one)
    temps: list         # leftover temporary files
    unrecorded: list    # quarantine directories no event records


def _scan(directory, bounds):
    path, workflow_id = _check_workflow_dir(directory)
    try:
        names = sorted(os.listdir(path))
    except OSError as exc:
        raise _io(exc, workflow_id)
    numbers, temps, has_quarantine = [], [], False
    for name in names:
        match = EVENT_FILE_RE.match(name)
        if match:
            numbers.append((int(match.group(1)), name))
        elif name.startswith(TMP_PREFIX):
            temps.append(name)
        elif name == LOCK_NAME:
            pass
        elif name == QUARANTINE_DIR:
            has_quarantine = True
        else:
            raise StoreRefusal('unexpected_file', 'unknown entry %r' % name[:80])
        try:
            st = os.lstat(os.path.join(path, name))
        except OSError as exc:
            raise _io(exc, name)
        if stat.S_ISLNK(st.st_mode):
            raise StoreRefusal('path_escape', 'symbolic link %r' % name[:80])
        want_dir = name == QUARANTINE_DIR
        if stat.S_ISDIR(st.st_mode) != want_dir or not (stat.S_ISDIR(st.st_mode) or stat.S_ISREG(st.st_mode)):
            raise StoreRefusal('unexpected_file', 'unexpected file type for %r' % name[:80])
    numbers.sort()
    for index, (number, name) in enumerate(numbers, start=1):
        if number != index:
            raise StoreRefusal('sequence_gap', 'expected event %06d, found %s' % (index, name),
                               {'expected': index, 'found': number})
    if len(numbers) > bounds.max_events + 1:
        raise StoreRefusal('workflow_full', 'more event files than the bound allows')

    events, torn, previous = [], [], None
    for index, (number, name) in enumerate(numbers, start=1):
        final = index == len(numbers)
        file_path = os.path.join(path, name)
        data = _read_regular(file_path, bounds.max_event_bytes)
        try:
            event = loads_strict(data.decode('utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError):
            if final:
                torn.append(name)
                break
            raise StoreRefusal('event_corrupt', 'event %06d is not valid JSON' % index, {'sequence': index})
        except ValueError as exc:
            raise StoreRefusal('noncanonical_event', 'event %06d: %s' % (index, exc), {'sequence': index})
        _check_stored_event(event, workflow_id)
        if jcs_bytes(event) != data:
            raise StoreRefusal('noncanonical_event', 'event %06d is not in canonical form' % index,
                               {'sequence': index})
        if event['digest'] != object_digest(event):
            raise StoreRefusal('digest_mismatch', 'event %06d' % index, {'sequence': index})
        if event['sequence'] != number:
            raise StoreRefusal('sequence_mismatch', 'file %s holds sequence %d' % (name, event['sequence']),
                               {'sequence': index})
        if event['predecessor'] != previous:
            raise StoreRefusal('chain_broken', 'event %06d predecessor does not match' % index,
                               {'sequence': index})
        previous = event['digest']
        events.append(event)
    if len(events) > bounds.max_events:
        raise StoreRefusal('workflow_full', 'more events than the bound allows')

    recorded = {e['body'].get('quarantine') for e in events if e['kind'] == KIND_QUARANTINED}
    unrecorded = []
    if has_quarantine:
        try:
            for name in sorted(os.listdir(os.path.join(path, QUARANTINE_DIR))):
                if name not in recorded:
                    unrecorded.append(name)
        except OSError as exc:
            raise _io(exc, QUARANTINE_DIR)
    return _Scan(path, workflow_id, events, torn, temps, unrecorded)


def _check_head(scan, expected_head):
    if expected_head is None:
        return
    if type(expected_head) is not tuple or len(expected_head) != 2 or type(expected_head[0]) is not int \
            or type(expected_head[1]) is not str:
        raise StoreRefusal('schema_invalid', 'expected_head is (sequence, digest)')
    seq, digest = expected_head
    if seq < 1:
        raise StoreRefusal('schema_invalid', 'expected_head sequence must be at least 1')
    if seq > len(scan.events):
        raise StoreRefusal('truncated', 'log ends at %d, caller-held head is %d' % (len(scan.events), seq),
                           {'have': len(scan.events), 'expected': seq})
    if scan.events[seq - 1]['digest'] != digest:
        raise StoreRefusal('chain_broken', 'event %06d differs from the caller-held head' % seq,
                           {'sequence': seq})


def _raise_conditions(scan):
    if scan.torn:
        raise StoreRefusal('torn_tail', 'final event %s is incomplete; run recover' % scan.torn[0],
                           {'files': list(scan.torn) + list(scan.temps)})
    if scan.temps:
        raise StoreRefusal('leftover_temp', 'leftover temporary file(s); run recover',
                           {'files': list(scan.temps)})
    if scan.unrecorded:
        raise StoreRefusal('unrecorded_quarantine', 'quarantine not recorded in the log; run recover',
                           {'files': list(scan.unrecorded)})


def _loaded(scan):
    events = tuple(_deep_copy(e) for e in scan.events)
    return LoadedWorkflow(scan.workflow_id, events, len(events), events[-1]['digest'] if events else None)


def load(directory, *, bounds=DEFAULT_BOUNDS, expected_head=None):
    """Re-validate the whole chain of one workflow directory and return its events in order.

    Raises StoreRefusal with a typed code for gaps, reordering, tampering, truncation (against
    the caller-held `expected_head` = (sequence, digest)), a torn final write (`torn_tail`), a
    leftover temporary file (`leftover_temp`) or an unrecorded quarantine. Nothing is repaired.
    """
    scan = _scan(directory, bounds)
    _check_head(scan, expected_head)
    _raise_conditions(scan)
    return _loaded(scan)


def inspect(directory, *, bounds=DEFAULT_BOUNDS):
    """Report torn-write conditions as a list of {code, files}; hard corruption still raises."""
    scan = _scan(directory, bounds)
    out = []
    if scan.torn:
        out.append({'code': 'torn_tail', 'files': list(scan.torn)})
    if scan.temps:
        out.append({'code': 'leftover_temp', 'files': list(scan.temps)})
    if scan.unrecorded:
        out.append({'code': 'unrecorded_quarantine', 'files': list(scan.unrecorded)})
    return out


# --- locking ----------------------------------------------------------------------------

def _lock_bytes(owner, timestamp):
    return jcs_bytes({'profile': LOCK_PROFILE, 'owner': owner, 'timestamp': timestamp})


def read_lock(directory):
    """Return {owner, timestamp} of the current lock, or None. Staleness is the caller's judgment."""
    path, _ = _check_workflow_dir(directory)
    lock = os.path.join(path, LOCK_NAME)
    try:
        data = _read_regular(lock, 4096)
    except StoreRefusal as exc:
        if exc.code == 'io_failure' and exc.detail.get('missing'):
            return None
        raise
    try:
        obj = loads_strict(data.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        raise StoreRefusal('lock_corrupt', 'lock file is not valid')
    if type(obj) is not dict or set(obj) != {'profile', 'owner', 'timestamp'} or obj['profile'] != LOCK_PROFILE \
            or type(obj['owner']) is not str or not OWNER_RE.match(obj['owner']) or not _text(obj['timestamp'], 64):
        raise StoreRefusal('lock_corrupt', 'lock file members')
    return {'owner': obj['owner'], 'timestamp': obj['timestamp']}


def _create_lock(path, owner, timestamp, tmp_name):
    """Atomic exclusive creation of LOCK with its content: temp file, then hard link."""
    tmp = os.path.join(path, tmp_name)
    try:
        _write_new_file(tmp, _lock_bytes(owner, timestamp), LOCK_MODE)
    except FileExistsError:
        raise StoreRefusal('leftover_temp', 'temporary lock file exists for this owner token',
                           {'files': [tmp_name]})
    try:
        try:
            os.link(tmp, os.path.join(path, LOCK_NAME))
        except FileExistsError:
            holder = None
            try:
                holder = read_lock(path)
            except StoreRefusal:
                pass
            raise StoreRefusal('lock_held', 'workflow is locked', {'holder': holder})
    finally:
        os.unlink(tmp)
    _fsync_dir(path)


def acquire(directory, *, owner, timestamp):
    """Take the single-writer lock. Never waits, never steals: a held lock is refused."""
    _check_owner(owner)
    if not _text(timestamp, 64):
        raise StoreRefusal('schema_invalid', 'timestamp must be non-empty opaque text')
    path, _ = _check_workflow_dir(directory)
    _create_lock(path, owner, timestamp, TMP_PREFIX + 'lock.' + owner)


def release(directory, *, owner):
    _check_owner(owner)
    path, _ = _check_workflow_dir(directory)
    _require_holder(path, owner)
    os.unlink(os.path.join(path, LOCK_NAME))
    _fsync_dir(path)


def _require_holder(path, owner):
    lock = read_lock(path)
    if lock is None:
        raise StoreRefusal('lock_not_held', 'no lock is held')
    if lock['owner'] != owner:
        raise StoreRefusal('lock_owner_mismatch', 'lock is held by another owner')


# --- append -----------------------------------------------------------------------------

def _append_locked(path, workflow_id, record, bounds, scan, *, allow_reserved=False):
    check_record(record, allow_reserved=allow_reserved)
    if len(scan.events) >= bounds.max_events:
        raise StoreRefusal('workflow_full', 'maximum events per workflow reached')
    sequence = len(scan.events) + 1
    predecessor = scan.events[-1]['digest'] if scan.events else None
    event = _build_event(workflow_id, sequence, predecessor, record)
    data = jcs_bytes(event)
    if len(data) > bounds.max_event_bytes:
        raise StoreRefusal('event_too_large', 'event is %d bytes' % len(data), {'size': len(data)})
    name = '%06d.json' % sequence
    tmp = os.path.join(path, TMP_PREFIX + name)
    final = os.path.join(path, name)
    try:
        _write_new_file(tmp, data, EVENT_MODE)
    except FileExistsError:
        raise StoreRefusal('leftover_temp', 'temporary file already exists', {'files': [TMP_PREFIX + name]})
    try:
        os.link(tmp, final)  # exclusive: never replaces an existing event
    except FileExistsError:
        os.unlink(tmp)
        raise StoreRefusal('sequence_conflict', 'event %s already exists' % name)
    _fsync_dir(path)
    os.unlink(tmp)
    _fsync_dir(path)
    return event


def append(directory, record, *, owner, bounds=DEFAULT_BOUNDS):
    """Append one event under the caller's lock; returns the stored event (retain its digest as a head)."""
    _check_owner(owner)
    check_record(record)
    path, workflow_id = _check_workflow_dir(directory)
    _require_holder(path, owner)
    scan = _scan(path, bounds)
    _raise_conditions(scan)
    return _deep_copy(_append_locked(path, workflow_id, record, bounds, scan))


# --- recover and break ------------------------------------------------------------------

def _file_facts(directory, names):
    facts = []
    for name in names:
        data = _read_regular(os.path.join(directory, name), CEILING_EVENT_BYTES)
        facts.append({'name': name, 'size': len(data), 'sha256': sha256_digest(data)})
    return facts


def _recover_locked(path, workflow_id, timestamp, bounds):
    scan = _scan(path, bounds)
    moved = list(scan.torn) + list(scan.temps)
    if not moved and not scan.unrecorded:
        raise StoreRefusal('nothing_to_recover', 'no torn tail, leftover temporary file or unrecorded quarantine')
    qroot = os.path.join(path, QUARANTINE_DIR)
    if moved:
        last = len(scan.events)
        if not os.path.isdir(qroot):
            os.mkdir(qroot, DIR_MODE)
            os.chmod(qroot, DIR_MODE)
        existing = set(os.listdir(qroot))
        k = 1
        while 'torn-write-after-%06d-%d' % (last, k) in existing:
            k += 1
        qname = 'torn-write-after-%06d-%d' % (last, k)
        qdir = os.path.join(qroot, qname)
        os.mkdir(qdir, DIR_MODE)
        os.chmod(qdir, DIR_MODE)
        for name in moved:
            os.rename(os.path.join(path, name), os.path.join(qdir, name))
        _fsync_dir(qdir)
        _fsync_dir(qroot)
        _fsync_dir(path)
    recorded = []
    scan = _scan(path, bounds)
    for qname in list(scan.unrecorded):
        qdir = os.path.join(qroot, qname)
        names = sorted(os.listdir(qdir))
        record = {'kind': KIND_QUARANTINED, 'timestamp': timestamp,
                  'body': {'quarantine': qname, 'last_good_sequence': len(scan.events),
                           'files': _file_facts(qdir, names)}}
        event = _append_locked(path, workflow_id, record, bounds, scan, allow_reserved=True)
        recorded.append(_deep_copy(event))
        scan = _scan(path, bounds)
    return recorded


def recover(directory, *, owner, timestamp, bounds=DEFAULT_BOUNDS):
    """Explicitly quarantine a torn tail and leftover temporary files, then record that in the log.

    Files move (never delete) into quarantine/torn-write-after-<last good sequence>-<n>/. The
    caller must hold the lock. Returns the recorded `store.torn_tail_quarantined` events.
    """
    _check_owner(owner)
    if not _text(timestamp, 64):
        raise StoreRefusal('schema_invalid', 'timestamp must be non-empty opaque text')
    path, workflow_id = _check_workflow_dir(directory)
    _require_holder(path, owner)
    return _recover_locked(path, workflow_id, timestamp, bounds)


def break_lock(directory, *, expected_owner, breaker, reason, timestamp, recover_torn=False,
               bounds=DEFAULT_BOUNDS):
    """Explicitly break a lock the caller judges stale, record it, and hand the lock to `breaker`.

    `expected_owner` must be the owner token currently in the lock file; the store does not
    judge staleness and has no clock. A `store.lock_broken` event is appended. If the log has
    a torn tail or leftover temporary file, the call is refused unless `recover_torn` is True,
    in which case recovery is performed (and recorded) first. Returns the recorded event.
    """
    _check_owner(expected_owner)
    _check_owner(breaker)
    if not _text(reason, 256) or not _text(timestamp, 64):
        raise StoreRefusal('schema_invalid', 'reason and timestamp must be non-empty text')
    path, workflow_id = _check_workflow_dir(directory)
    current = read_lock(path)
    if current is None:
        raise StoreRefusal('lock_not_held', 'no lock to break')
    if current['owner'] != expected_owner:
        raise StoreRefusal('lock_owner_mismatch', 'lock is held by another owner')
    scan = _scan(path, bounds)
    if (scan.torn or scan.temps or scan.unrecorded) and not recover_torn:
        _raise_conditions(scan)
    if len(scan.events) + 2 > bounds.max_events:
        raise StoreRefusal('workflow_full', 'no room to record the break')
    original = _lock_bytes(current['owner'], current['timestamp'])
    aside = os.path.join(path, TMP_PREFIX + 'lock-aside.' + breaker)
    lock = os.path.join(path, LOCK_NAME)
    try:
        os.rename(lock, aside)
    except FileNotFoundError:
        raise StoreRefusal('lock_not_held', 'lock vanished')
    except FileExistsError:
        raise StoreRefusal('leftover_temp', 'a lock-break is already in flight for this breaker')
    if _read_regular(aside, 4096) != original:
        try:
            os.link(aside, lock)
        finally:
            os.unlink(aside)
        raise StoreRefusal('lock_owner_mismatch', 'lock changed while breaking')
    os.unlink(aside)
    _create_lock(path, breaker, timestamp, TMP_PREFIX + 'lock.' + breaker)
    if recover_torn and (scan.torn or scan.temps or scan.unrecorded):
        _recover_locked(path, workflow_id, timestamp, bounds)
    scan = _scan(path, bounds)
    record = {'kind': KIND_LOCK_BROKEN, 'timestamp': timestamp,
              'body': {'broken_owner': current['owner'], 'broken_lock_timestamp': current['timestamp'],
                       'breaker': breaker, 'reason': reason}}
    return _deep_copy(_append_locked(path, workflow_id, record, bounds, scan, allow_reserved=True))


# --- the store --------------------------------------------------------------------------

class Store:
    """A directory of workflow directories, with explicit bounds. Not a service: no clock, no network."""

    def __init__(self, root, bounds=DEFAULT_BOUNDS):
        if not isinstance(bounds, Bounds):
            raise StoreRefusal('bounds_invalid', 'bounds must be a Bounds')
        path = os.path.abspath(os.fspath(root))
        try:
            st = os.lstat(path)
        except OSError as exc:
            raise _io(exc, 'store root')
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
            raise StoreRefusal('path_escape', 'store root must be a real directory')
        self.root = path
        self.bounds = bounds

    def workflow_dir(self, workflow_id):
        _check_workflow_id(workflow_id)
        return os.path.join(self.root, workflow_id)

    def workflows(self):
        out = []
        for name in sorted(os.listdir(self.root)):
            if WORKFLOW_ID_RE.match(name) and os.path.isdir(os.path.join(self.root, name)) \
                    and not os.path.islink(os.path.join(self.root, name)):
                out.append(name)
        return out

    def create_workflow(self, workflow_id):
        path = self.workflow_dir(workflow_id)
        if len(self.workflows()) >= self.bounds.max_workflows:
            raise StoreRefusal('store_full', 'maximum workflows per store reached')
        try:
            os.mkdir(path, DIR_MODE)
        except FileExistsError:
            raise StoreRefusal('workflow_exists', workflow_id)
        os.chmod(path, DIR_MODE)
        _fsync_dir(path)
        _fsync_dir(self.root)
        return path

    def _existing(self, workflow_id):
        path = self.workflow_dir(workflow_id)
        _check_workflow_dir(path)
        return path

    def acquire(self, workflow_id, *, owner, timestamp):
        acquire(self._existing(workflow_id), owner=owner, timestamp=timestamp)

    def release(self, workflow_id, *, owner):
        release(self._existing(workflow_id), owner=owner)

    def read_lock(self, workflow_id):
        return read_lock(self._existing(workflow_id))

    def append(self, workflow_id, record, *, owner):
        return append(self._existing(workflow_id), record, owner=owner, bounds=self.bounds)

    def load(self, workflow_id, *, expected_head=None):
        return load(self._existing(workflow_id), bounds=self.bounds, expected_head=expected_head)

    def inspect(self, workflow_id):
        return inspect(self._existing(workflow_id), bounds=self.bounds)

    def recover(self, workflow_id, *, owner, timestamp):
        return recover(self._existing(workflow_id), owner=owner, timestamp=timestamp, bounds=self.bounds)

    def break_lock(self, workflow_id, *, expected_owner, breaker, reason, timestamp, recover_torn=False):
        return break_lock(self._existing(workflow_id), expected_owner=expected_owner, breaker=breaker,
                          reason=reason, timestamp=timestamp, recover_torn=recover_torn, bounds=self.bounds)
