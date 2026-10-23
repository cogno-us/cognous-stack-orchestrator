"""Durable single-host event store: append-only, hash-chained, restartable. Non-authorizing.

The store persists opaque, schema-checked event records per workflow and returns them in
order. It does not interpret them: no state machine, no verdict, no grant, no pin, no
authority. It reads no clock (timestamps are caller-supplied opaque text), opens no network
connection and starts no subprocess. Standard library only.
"""
import contextlib
import errno
import fcntl
import hashlib
import itertools
import json
import os
import re
import stat
from dataclasses import dataclass

from .canonical import (CANONICAL_PROFILE_NAME, MAX_SAFE_INT, NestingError, jcs_bytes, loads_strict,
                        object_digest, raw_decode_strict)
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
LOCK_ID_RE = re.compile(r'^[0-9a-f]{32}\Z')
EVENT_FILE_RE = re.compile(r'^([0-9]{6})\.json\Z')
RESERVED_KIND_PREFIX = 'store.'
KIND_LOCK_BROKEN = 'store.lock_broken'
KIND_QUARANTINED = 'store.torn_tail_quarantined'

LOCK_NAME = 'LOCK'
QUARANTINE_DIR = 'quarantine'
LOCKS_DIR = '.locks'  # lock temporaries and the internal mutex; never scanned as events or temps
MAX_FACTS = 32
RECOVERY_RESERVE = 64  # store.* events may exceed max_events by this many (recovery must stay possible)
_COUNTER = itertools.count()
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
        for name, value, ceiling in (('max_events', self.max_events, CEILING_EVENTS),
                                     ('max_event_bytes', self.max_event_bytes, CEILING_EVENT_BYTES),
                                     ('max_workflows', self.max_workflows, CEILING_WORKFLOWS)):
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


def _open_regular(path):
    """Open a regular file read-only without following symlinks or blocking on special files."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        raise StoreRefusal('io_failure', 'missing: %s' % os.path.basename(path), {'missing': True})
    except OSError as exc:
        raise _io(exc, os.path.basename(path))
    try:
        st = os.fstat(fd)
    except OSError:
        os.close(fd)
        raise
    if not stat.S_ISREG(st.st_mode):
        os.close(fd)
        raise StoreRefusal('unexpected_file', 'not a regular file: %s' % os.path.basename(path))
    return fd, st


def _read_regular(path, limit):
    """Read a regular file of at most `limit` bytes; larger files raise event_too_large."""
    fd, st = _open_regular(path)
    try:
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


def _stream_facts(path, name):
    """Size and sha256 of a file, read in chunks with no size cap; non-regular entries are described, not read."""
    st = os.lstat(path)
    if not stat.S_ISREG(st.st_mode):
        return {'name': name, 'size': None, 'sha256': None}
    fd, _ = _open_regular(path)
    try:
        digest, size = hashlib.sha256(), 0
        while True:
            chunk = os.read(fd, 1 << 16)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
    finally:
        os.close(fd)
    return {'name': name, 'size': size, 'sha256': 'sha256:' + digest.hexdigest()}


def _read_prefix(path, limit):
    """First `limit` bytes of a regular file (for inspecting a torn tail)."""
    fd, _ = _open_regular(path)
    try:
        return os.read(fd, limit)
    finally:
        os.close(fd)


def _write_new_file(path, data, mode):
    """Write data to a new file (exclusive), set the final mode, then flush and fsync it."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        os.fchmod(fd, mode)  # a read-only mode does not stop the already open descriptor
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            view = view[written:]
        os.fsync(fd)
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


def _check_json_value(value, budget, depth=0):
    """Shape check with a cheap running lower bound of the encoded size (budget is a one-item list)."""
    if depth > MAX_DEPTH:
        raise StoreRefusal('schema_invalid', 'body nesting exceeds %d' % MAX_DEPTH)
    budget[0] -= 1
    if budget[0] < 0:
        raise StoreRefusal('event_too_large', 'record exceeds the event size bound')
    if value is None or type(value) is bool:
        return
    if type(value) is str:
        budget[0] -= len(value)
        if budget[0] < 0:
            raise StoreRefusal('event_too_large', 'record exceeds the event size bound')
        return
    if type(value) is int:
        if abs(value) > MAX_SAFE_INT:
            raise StoreRefusal('schema_invalid', 'integer outside the safe range')
        return
    if type(value) is list:
        for item in value:
            _check_json_value(item, budget, depth + 1)
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise StoreRefusal('schema_invalid', 'object keys must be strings')
            budget[0] -= len(key)
            _check_json_value(item, budget, depth + 1)
        return
    raise StoreRefusal('schema_invalid', 'value type not representable (no floats)')


def check_record(record, *, allow_reserved=False, limit=CEILING_EVENT_BYTES):
    """Validate a caller-supplied record {kind, timestamp, body}; returns it unchanged.

    The size bound is checked cheaply while walking the body, before anything is canonicalized.
    """
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
    _check_json_value(record['body'], [limit])
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


def _is_store_kind(event):
    return event['kind'].startswith(RESERVED_KIND_PREFIX)


def _scan(directory, bounds):
    path, workflow_id = _check_workflow_dir(directory)
    try:
        names = sorted(os.listdir(path))
    except OSError as exc:
        raise _io(exc, workflow_id)
    numbers, temps, has_quarantine = [], [], False
    for name in names:
        match = EVENT_FILE_RE.match(name)
        is_temp = name.startswith(TMP_PREFIX)
        if match:
            numbers.append((int(match.group(1)), name))
        elif is_temp:
            pass
        elif name == LOCK_NAME:
            continue  # classified by _lock_state (a non-regular LOCK is a breakable corrupt lock)
        elif name == LOCKS_DIR:
            pass
        elif name == QUARANTINE_DIR:
            has_quarantine = True
        else:
            raise StoreRefusal('unexpected_file', 'unknown entry %r' % name[:80])
        try:
            st = os.lstat(os.path.join(path, name))
        except FileNotFoundError:
            if is_temp:  # a concurrent writer finished
                continue
            raise StoreRefusal('io_failure', 'entry vanished: %s' % name[:80])
        except OSError as exc:
            raise _io(exc, name)
        if is_temp:
            temps.append(name)
        if stat.S_ISLNK(st.st_mode):
            raise StoreRefusal('path_escape', 'symbolic link %r' % name[:80])
        want_dir = name in (QUARANTINE_DIR, LOCKS_DIR)
        if stat.S_ISDIR(st.st_mode) != want_dir or not (stat.S_ISDIR(st.st_mode) or stat.S_ISREG(st.st_mode)):
            raise StoreRefusal('unexpected_file', 'unexpected file type for %r' % name[:80])
    numbers.sort()
    for index, (number, name) in enumerate(numbers, start=1):
        if number != index:
            raise StoreRefusal('sequence_gap', 'expected event %06d, found %s' % (index, name),
                               {'expected': index, 'found': number})
    if len(numbers) > bounds.max_events + RECOVERY_RESERVE + 1:
        raise StoreRefusal('workflow_full', 'more event files than the bound allows')

    events, torn, previous = [], [], None
    for index, (number, name) in enumerate(numbers, start=1):
        final = index == len(numbers)
        file_path = os.path.join(path, name)
        try:
            data = _read_regular(file_path, CEILING_EVENT_BYTES)
        except StoreRefusal as exc:
            if exc.code == 'event_too_large' and final:  # no valid event is this large
                torn.append(name)
                break
            raise
        try:
            event = loads_strict(data.decode('utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError):
            if final:
                torn.append(name)
                break
            raise StoreRefusal('event_corrupt', 'event %06d is not valid JSON' % index, {'sequence': index})
        except NestingError:
            if final:  # no valid event nests this deep: a junk or torn final file
                torn.append(name)
                break
            raise StoreRefusal('noncanonical_event', 'event %06d nests too deeply' % index, {'sequence': index})
        except ValueError as exc:
            raise StoreRefusal('noncanonical_event', 'event %06d: %s' % (index, exc), {'sequence': index})
        _check_stored_event(event, workflow_id)
        if jcs_bytes(event) != data:
            raise StoreRefusal('noncanonical_event', 'event %06d is not in canonical form' % index,
                               {'sequence': index})
        if len(data) > bounds.max_event_bytes and not _is_store_kind(event):
            raise StoreRefusal('event_too_large', 'event %06d is %d bytes' % (index, len(data)),
                               {'size': len(data)})
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
    if len(events) > bounds.max_events + RECOVERY_RESERVE:
        raise StoreRefusal('workflow_full', 'more events than the bound allows')

    recorded = {e['body'].get('quarantine') for e in events
                if e['kind'] == KIND_QUARANTINED and type(e['body'].get('quarantine')) is str}
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
        raise StoreRefusal('truncated', 'log ends at %d, caller-held head is %d (to discard on purpose, '
                           'recover(acknowledge_drop=True) is the explicit override)' % (len(scan.events), seq),
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


def load(directory, *, bounds=DEFAULT_BOUNDS, expected_head=None, ignore_in_flight=False):
    """Re-validate the whole chain of one workflow directory and return its events in order.

    Raises StoreRefusal with a typed code for gaps, reordering, tampering, truncation (against
    the caller-held `expected_head` = (sequence, digest)), a torn final write (`torn_tail`), a
    leftover temporary file (`leftover_temp`) or an unrecorded quarantine. Nothing is repaired.
    `ignore_in_flight=True` is for a reader that is not the writer: while a LOCK exists, temporary
    files are assumed to be a writer's append in progress and are not reported (a crashed writer's
    leftover stays hidden from such a reader until the lock is released or broken).
    """
    scan = _scan(directory, bounds)
    _check_head(scan, expected_head)
    if ignore_in_flight and _lock_state(scan.path)[0] != 'absent':
        scan.temps = []
    _raise_conditions(scan)
    return _loaded(scan)


def inspect(directory, *, bounds=DEFAULT_BOUNDS):
    """Report torn-write and lock-break conditions as a list of {code, files}; hard corruption still raises."""
    scan = _scan(directory, bounds)
    out = []
    if scan.torn:
        out.append({'code': 'torn_tail', 'files': list(scan.torn)})
    if scan.temps:
        out.append({'code': 'leftover_temp', 'files': list(scan.temps)})
    if scan.unrecorded:
        out.append({'code': 'unrecorded_quarantine', 'files': list(scan.unrecorded)})
    if scan.events and scan.events[-1]['kind'] == KIND_LOCK_BROKEN:
        body = scan.events[-1]['body']
        state, info, sha = _lock_state(scan.path)
        old_ok = state == 'ok' and body.get('broken_lock_id') is not None \
            and info['lock_id'] == body['broken_lock_id']
        old_corrupt = state == 'corrupt' and body.get('corrupt_lock_sha256') is not None \
            and sha == body['corrupt_lock_sha256']
        if old_ok or old_corrupt:  # the lock the break event names is still in place
            out.append({'code': 'lock_break_incomplete', 'files': []})
    return out


# --- locking ----------------------------------------------------------------------------

def _new_lock_id():
    return os.urandom(16).hex()


def _lock_bytes(owner, timestamp, lock_id):
    return jcs_bytes({'profile': LOCK_PROFILE, 'owner': owner, 'timestamp': timestamp, 'lock_id': lock_id})


def _marker_sha(marker):
    return 'sha256:' + hashlib.sha256(marker).hexdigest()


def _lock_state(path):
    """Return (state, info, sha256) with state 'absent', 'ok' or 'corrupt'."""
    lock = os.path.join(path, LOCK_NAME)
    try:
        st = os.lstat(lock)
    except FileNotFoundError:
        return 'absent', None, None
    except OSError as exc:
        raise _io(exc, LOCK_NAME)
    if stat.S_ISLNK(st.st_mode):  # a symlink is replaced, never followed
        try:
            target = os.readlink(lock)
        except OSError:
            target = ''
        return 'corrupt', None, _marker_sha(b'symlink:' + target.encode('utf-8', 'surrogateescape'))
    if not stat.S_ISREG(st.st_mode):  # FIFO, socket, device or directory: described by its file type
        return 'corrupt', None, _marker_sha(('nonregular:%o' % stat.S_IFMT(st.st_mode)).encode())
    try:
        fd, st = _open_regular(lock)
    except StoreRefusal as exc:
        if exc.detail.get('missing'):
            return 'absent', None, None
        if exc.code == 'unexpected_file':
            return 'corrupt', None, _marker_sha(b'nonregular:raced')
        raise
    try:
        digest, size, head = hashlib.sha256(), 0, b''
        while True:
            chunk = os.read(fd, 1 << 16)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
            if size <= 4096:
                head += chunk
    finally:
        os.close(fd)
    sha = 'sha256:' + digest.hexdigest()
    if size > 4096:
        return 'corrupt', None, sha
    try:
        obj = loads_strict(head.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        return 'corrupt', None, sha
    if type(obj) is not dict or set(obj) != {'profile', 'owner', 'timestamp', 'lock_id'} \
            or obj['profile'] != LOCK_PROFILE \
            or type(obj['owner']) is not str or not OWNER_RE.match(obj['owner']) or not _text(obj['timestamp'], 64) \
            or type(obj['lock_id']) is not str or not LOCK_ID_RE.match(obj['lock_id']):
        return 'corrupt', None, sha
    return 'ok', {'owner': obj['owner'], 'timestamp': obj['timestamp'], 'lock_id': obj['lock_id']}, sha


def read_lock(directory):
    """Return {owner, timestamp} of the current lock, or None. Staleness is the caller's judgment."""
    path, _ = _check_workflow_dir(directory)
    state, info, sha = _lock_state(path)
    if state == 'corrupt':
        raise StoreRefusal('lock_corrupt', 'lock file is not valid; see break_lock(corrupt_lock_sha256=...)',
                           {'sha256': sha})
    return None if info is None else {'owner': info['owner'], 'timestamp': info['timestamp']}


@contextlib.contextmanager
def _mutex(path):
    """Serialize every lock-state transition and append through an flock'd file inside the workflow.

    This is not the writer lock. It is held only for the duration of one store call (no waiting
    on a writer), is released by the kernel if the process dies, and makes check-then-act on
    LOCK atomic among callers that use this API.
    """
    locks = os.path.join(path, LOCKS_DIR)
    try:
        os.mkdir(locks, DIR_MODE)
        os.chmod(locks, DIR_MODE)
    except FileExistsError:
        pass
    except OSError as exc:
        raise _io(exc, LOCKS_DIR)
    try:
        if stat.S_ISLNK(os.lstat(locks).st_mode):
            raise StoreRefusal('path_escape', 'lock directory is a symbolic link')
        fd = os.open(os.path.join(locks, 'mutex'), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    except OSError as exc:
        raise _io(exc, LOCKS_DIR)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
        except OSError as exc:
            raise StoreRefusal('io_failure', 'flock failed (%s); a local filesystem with flock is required'
                               % (exc.strerror or exc.errno))
        try:
            yield
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)  # a forked child may share the descriptor: release explicitly
            except OSError:
                pass
    finally:
        os.close(fd)


def _stage_lock(path, owner, timestamp, lock_id):
    """Write a new lock file's content to a uniquely named temporary file in .locks and return its path.

    The name carries random bytes and creation is exclusive, retried, so pid reuse cannot collide.
    """
    data = _lock_bytes(owner, timestamp, lock_id)
    for _ in range(8):
        tmp = os.path.join(path, LOCKS_DIR, '%s.%s.%d' % (owner, os.urandom(6).hex(), next(_COUNTER)))
        try:
            _write_new_file(tmp, data, LOCK_MODE)
            return tmp
        except FileExistsError:
            continue
        except OSError as exc:
            raise _io(exc, 'lock temporary file')
    raise StoreRefusal('io_failure', 'could not create a unique lock temporary file')


def acquire(directory, *, owner, timestamp):
    """Take the single-writer lock. Never waits for a holder and never steals: a held lock is refused."""
    _check_owner(owner)
    if not _text(timestamp, 64):
        raise StoreRefusal('schema_invalid', 'timestamp must be non-empty opaque text')
    path, _ = _check_workflow_dir(directory)
    with _mutex(path):
        state, info, sha = _lock_state(path)
        if state != 'absent':
            raise StoreRefusal('lock_held', 'workflow is locked',
                               {'holder': None if info is None else {'owner': info['owner'],
                                                                     'timestamp': info['timestamp']},
                                'corrupt': state == 'corrupt'})
        tmp = _stage_lock(path, owner, timestamp, _new_lock_id())
        try:
            os.link(tmp, os.path.join(path, LOCK_NAME))  # exclusive even against callers outside this API
        except FileExistsError:
            raise StoreRefusal('lock_held', 'workflow is locked')
        except OSError as exc:
            raise _io(exc, 'lock')
        finally:
            os.unlink(tmp)
        try:
            _fsync_dir(path)
        except OSError as exc:
            raise StoreRefusal('outcome_ambiguous', 'the lock was created but the directory fsync failed (%s); '
                               'it may be held: check read_lock()' % exc)


def release(directory, *, owner):
    _check_owner(owner)
    path, _ = _check_workflow_dir(directory)
    with _mutex(path):
        _require_holder(path, owner)
        os.unlink(os.path.join(path, LOCK_NAME))
        try:
            _fsync_dir(path)
        except OSError as exc:
            raise StoreRefusal('outcome_ambiguous', 'the lock was removed but the directory fsync failed (%s); '
                               'it may still be reported as held after a crash: check read_lock()' % exc)


def _require_holder(path, owner):
    state, info, sha = _lock_state(path)
    if state == 'absent':
        raise StoreRefusal('lock_not_held', 'no lock is held')
    if state == 'corrupt':
        raise StoreRefusal('lock_corrupt', 'lock file is not valid; see break_lock(corrupt_lock_sha256=...)',
                           {'sha256': sha})
    if info['owner'] != owner:
        raise StoreRefusal('lock_owner_mismatch', 'lock is held by another owner')


# --- append -----------------------------------------------------------------------------

def _append_locked(path, workflow_id, record, bounds, scan, *, reserved=False):
    """Append under the mutex. `reserved` (store.* events only) may use the recovery reserve and ignores
    the per-event size bound, so recovery and lock-break records can never be refused for size or count."""
    check_record(record, allow_reserved=reserved, limit=CEILING_EVENT_BYTES if reserved else bounds.max_event_bytes)
    limit = bounds.max_events + (RECOVERY_RESERVE if reserved else 0)
    if len(scan.events) >= limit:
        raise StoreRefusal('workflow_full', 'maximum events per workflow reached')
    sequence = len(scan.events) + 1
    predecessor = scan.events[-1]['digest'] if scan.events else None
    event = _build_event(workflow_id, sequence, predecessor, record)
    data = jcs_bytes(event)
    if len(data) > (CEILING_EVENT_BYTES if reserved else bounds.max_event_bytes):
        raise StoreRefusal('event_too_large', 'event is %d bytes' % len(data), {'size': len(data)})
    name = '%06d.json' % sequence
    tmp = os.path.join(path, TMP_PREFIX + name)
    final = os.path.join(path, name)
    try:
        _write_new_file(tmp, data, EVENT_MODE)
    except FileExistsError:
        raise StoreRefusal('leftover_temp', 'temporary file already exists', {'files': [TMP_PREFIX + name]})
    except OSError as exc:
        raise _io(exc, 'event temporary file (the event was not created)')
    try:
        os.link(tmp, final)  # exclusive: never replaces an existing event
    except FileExistsError:
        os.unlink(tmp)
        raise StoreRefusal('sequence_conflict', 'event %s already exists' % name)
    except OSError as exc:
        raise _io(exc, 'event link (the event was not created)')
    try:
        _fsync_dir(path)
        os.unlink(tmp)
        _fsync_dir(path)
    except OSError as exc:
        raise StoreRefusal('outcome_ambiguous',
                           'event %s may exist (%s); reload with load() before doing anything else' % (name, exc),
                           {'sequence': sequence})
    return event


def append(directory, record, *, owner, bounds=DEFAULT_BOUNDS):
    """Append one event under the caller's lock; returns the stored event (retain its digest as a head).

    `outcome_ambiguous` means a failure after the event became visible: it may exist; reload.
    """
    _check_owner(owner)
    check_record(record, limit=bounds.max_event_bytes)
    path, workflow_id = _check_workflow_dir(directory)
    with _mutex(path):
        _require_holder(path, owner)
        scan = _scan(path, bounds)
        _raise_conditions(scan)
        return _deep_copy(_append_locked(path, workflow_id, record, bounds, scan))


# --- recover and break ------------------------------------------------------------------

def _complete_prefix(data, workflow_id, scan):
    """Digest of a complete, valid next event at the start of a torn tail's bytes, else None."""
    try:
        text = data.decode('utf-8', errors='ignore')
        event, _ = raw_decode_strict(text)
        _check_stored_event(event, workflow_id)
        if event['digest'] != object_digest(event) or event['sequence'] != len(scan.events) + 1:
            return None
        if event['predecessor'] != (scan.events[-1]['digest'] if scan.events else None):
            return None
        return event['digest']
    except (ValueError, StoreRefusal):
        return None


def _recover_locked(path, workflow_id, timestamp, bounds, expected_head, acknowledge_drop):
    scan = _scan(path, bounds)
    _check_head(scan, expected_head)
    moved = list(scan.torn) + list(scan.temps)
    if not moved and not scan.unrecorded:
        raise StoreRefusal('nothing_to_recover', 'no torn tail, leftover temporary file or unrecorded quarantine')
    discarded = None
    if scan.torn:
        data = _read_prefix(os.path.join(path, scan.torn[0]), CEILING_EVENT_BYTES)
        discarded = _complete_prefix(data, workflow_id, scan)
        if discarded is not None and not acknowledge_drop:
            last_digest = scan.events[-1]['digest'] if scan.events else None
            if expected_head is None:
                raise StoreRefusal('complete_event_in_tail',
                                   'the torn tail begins with a complete, valid event that may have been '
                                   'acknowledged; pass expected_head equal to the log head (the last head you '
                                   'were given) or acknowledge_drop=True', {'digest': discarded})
            if expected_head[0] != len(scan.events) or expected_head[1] != last_digest:
                raise StoreRefusal('complete_event_in_tail',
                                   'expected_head is behind the log head (%d valid events): events up to the '
                                   'head were acknowledged, so the tail event cannot be dropped on that '
                                   'basis; acknowledge_drop=True is the explicit override'
                                   % len(scan.events), {'digest': discarded})
    qroot = os.path.join(path, QUARANTINE_DIR)
    pre = {}
    if moved:
        last = len(scan.events)
        try:
            facts = [_stream_facts(os.path.join(path, name), name) for name in sorted(moved)]  # before any move
        except OSError as exc:
            raise _io(exc, 'quarantine facts (nothing was moved)')
        try:
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
        except OSError as exc:
            raise StoreRefusal('outcome_ambiguous',
                               'quarantine may be partly done (%s); run inspect() and recover() again' % exc)
        pre[qname] = facts
    recorded = []
    scan = _scan(path, bounds)
    for qname in list(scan.unrecorded):
        qdir = os.path.join(qroot, qname)
        facts = pre.get(qname)
        if facts is None:
            facts = [_stream_facts(os.path.join(qdir, n), n) for n in sorted(os.listdir(qdir))]
        body = {'quarantine': qname, 'last_good_sequence': len(scan.events), 'files_total': len(facts),
                'files': facts[:MAX_FACTS]}
        if qname in pre and discarded is not None:
            body['complete_event_discarded'] = discarded
        record = {'kind': KIND_QUARANTINED, 'timestamp': timestamp, 'body': body}
        event = _append_locked(path, workflow_id, record, bounds, scan, reserved=True)
        recorded.append(_deep_copy(event))
        scan = _scan(path, bounds)
    return recorded


def recover(directory, *, owner, timestamp, bounds=DEFAULT_BOUNDS, expected_head=None, acknowledge_drop=False):
    """Explicitly quarantine a torn tail and leftover temporary files, then record that in the log.

    Files move (never delete) into quarantine/torn-write-after-<last good sequence>-<n>/, and
    their sizes and sha256 are taken first, without a size cap. The caller must hold the lock.
    If the torn tail begins with a complete valid event (which may have been acknowledged), recovery
    is refused with `complete_event_in_tail` unless `expected_head` (the last head the caller was
    given) or `acknowledge_drop=True` is passed. Recovery records may use the recovery reserve
    beyond max_events. Returns the recorded `store.torn_tail_quarantined` events.
    """
    _check_owner(owner)
    if not _text(timestamp, 64):
        raise StoreRefusal('schema_invalid', 'timestamp must be non-empty opaque text')
    path, workflow_id = _check_workflow_dir(directory)
    with _mutex(path):
        _require_holder(path, owner)
        return _recover_locked(path, workflow_id, timestamp, bounds, expected_head, acknowledge_drop)


def break_lock(directory, *, expected_owner=None, breaker, reason, timestamp, recover_torn=False,
               corrupt_lock_sha256=None, bounds=DEFAULT_BOUNDS, expected_head=None, acknowledge_drop=False):
    """Explicitly break a lock the caller judges stale, record it, and hand the lock to `breaker`.

    A manual operator act. `expected_owner` must be the owner token currently in the lock file; the
    store has no clock and does not judge staleness, owner tokens are forgeable, and a holder that
    is in fact alive simply has its next call refused (`lock_owner_mismatch`).
    A corrupt lock file has no owner: pass expected_owner=None and `corrupt_lock_sha256` equal to
    the sha256 of the bytes you inspected (the refusal detail of `lock_corrupt` carries it).
    Order: checks, optional recovery (recorded), then the `store.lock_broken` event, then an atomic
    replace of LOCK. A crash between the last two leaves the old lock in place with the event
    recorded; `inspect` reports that as `lock_break_incomplete`. Returns the recorded event.
    """
    _check_owner(breaker)
    if expected_owner is not None:
        _check_owner(expected_owner)
    if not _text(reason, 256) or not _text(timestamp, 64):
        raise StoreRefusal('schema_invalid', 'reason and timestamp must be non-empty text')
    path, workflow_id = _check_workflow_dir(directory)
    with _mutex(path):
        state, info, sha = _lock_state(path)
        if state == 'absent':
            raise StoreRefusal('lock_not_held', 'no lock to break')
        if state == 'ok':
            if corrupt_lock_sha256 is not None or expected_owner is None:
                raise StoreRefusal('schema_invalid', 'name the lock owner you observed (expected_owner)')
            if info['owner'] != expected_owner:
                raise StoreRefusal('lock_owner_mismatch', 'lock is held by another owner')
            broken = {'broken_owner': info['owner'], 'broken_lock_timestamp': info['timestamp'],
                      'broken_lock_id': info['lock_id']}
        else:
            if expected_owner is not None or corrupt_lock_sha256 is None:
                raise StoreRefusal('lock_corrupt', 'lock file is not valid; pass expected_owner=None and '
                                   'corrupt_lock_sha256 of the bytes you inspected', {'sha256': sha})
            if sha is None or corrupt_lock_sha256 != sha:
                raise StoreRefusal('lock_owner_mismatch', 'corrupt lock bytes differ from the acknowledged digest',
                                   {'sha256': sha})
            broken = {'broken_owner': None, 'broken_lock_timestamp': None, 'broken_lock_id': None,
                      'corrupt_lock_sha256': sha}
            if stat.S_ISDIR(os.lstat(os.path.join(path, LOCK_NAME)).st_mode):
                raise StoreRefusal('io_failure', 'LOCK is a directory: remove it by hand (out-of-band)')
        scan = _scan(path, bounds)
        if (scan.torn or scan.temps or scan.unrecorded) and not recover_torn:
            _raise_conditions(scan)
        if len(scan.events) + 2 > bounds.max_events + RECOVERY_RESERVE:
            raise StoreRefusal('workflow_full', 'no room to record the break')
        new_lock_id = _new_lock_id()
        staged = _stage_lock(path, breaker, timestamp, new_lock_id)
        try:
            if scan.torn or scan.temps or scan.unrecorded:
                _recover_locked(path, workflow_id, timestamp, bounds, expected_head, acknowledge_drop)
                scan = _scan(path, bounds)
            body = dict(broken)
            body.update({'breaker': breaker, 'new_lock_id': new_lock_id, 'reason': reason})
            event = _append_locked(path, workflow_id, {'kind': KIND_LOCK_BROKEN, 'timestamp': timestamp,
                                                       'body': body}, bounds, scan, reserved=True)
            try:
                os.replace(staged, os.path.join(path, LOCK_NAME))  # atomic: no gap with no lock
                staged = None
                _fsync_dir(path)
            except OSError as exc:
                raise StoreRefusal('lock_break_incomplete',
                                   'the break event %06d is recorded but the lock was not handed over (%s); '
                                   'inspect() reports it; repeat break_lock' % (event['sequence'], exc),
                                   {'sequence': event['sequence']})
        finally:
            if staged is not None and os.path.lexists(staged):
                os.unlink(staged)
        return _deep_copy(event)


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

    def load(self, workflow_id, *, expected_head=None, ignore_in_flight=False):
        return load(self._existing(workflow_id), bounds=self.bounds, expected_head=expected_head,
                    ignore_in_flight=ignore_in_flight)

    def inspect(self, workflow_id):
        return inspect(self._existing(workflow_id), bounds=self.bounds)

    def recover(self, workflow_id, *, owner, timestamp, expected_head=None, acknowledge_drop=False):
        return recover(self._existing(workflow_id), owner=owner, timestamp=timestamp, bounds=self.bounds,
                       expected_head=expected_head, acknowledge_drop=acknowledge_drop)

    def break_lock(self, workflow_id, *, breaker, reason, timestamp, expected_owner=None, recover_torn=False,
                   corrupt_lock_sha256=None, expected_head=None, acknowledge_drop=False):
        return break_lock(self._existing(workflow_id), expected_owner=expected_owner, breaker=breaker,
                          reason=reason, timestamp=timestamp, recover_torn=recover_torn,
                          corrupt_lock_sha256=corrupt_lock_sha256, bounds=self.bounds,
                          expected_head=expected_head, acknowledge_drop=acknowledge_drop)
