"""Static check of the closed refusal-code set: no dynamic or order-dependent state.

1. Every `StoreRefusal('<code>', ...)` literal in the package is in CODES, and every code in CODES
   is raised from a literal in the package (the set is closed in both directions).
2. TRIGGERS maps each code to the negative test that raises it; that test must exist in this
   directory and name the code as a literal.
"""
import ast
import os

from orchestration import workflow_store as ws

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(ws.store.__file__)

TRIGGERS = {
    'bounds_invalid': 'test_bounds_must_be_within_ceilings',
    'chain_broken': 'test_resigned_tamper_breaks_the_successor_link',
    'complete_event_in_tail': 'test_recover_refuses_when_the_tail_holds_a_complete_valid_event',
    'digest_mismatch': 'test_tampered_body_detected_as_digest_mismatch',
    'event_corrupt': 'test_corrupt_middle_event_is_not_treated_as_torn',
    'event_too_large': 'test_max_event_size',
    'forbidden_member': 'test_forbidden_members_refused_by_name',
    'invalid_owner': 'test_invalid_owner_token_refused',
    'invalid_workflow_id': 'test_invalid_workflow_ids_refused_everywhere',
    'io_failure': 'test_link_failure_before_the_event_exists_is_io_failure',
    'leftover_temp': 'test_crash_between_temp_write_and_link_leaves_only_a_temp',
    'lock_break_incomplete': 'test_replace_failure_is_a_typed_incomplete_break',
    'lock_corrupt': 'test_corrupt_lock_file_is_reported_not_overwritten',
    'lock_held': 'test_second_acquire_refused_and_never_steals',
    'lock_not_held': 'test_append_requires_lock',
    'lock_owner_mismatch': 'test_append_requires_lock',
    'not_archivable': 'test_every_non_terminal_or_unknown_status_name_is_not_archivable',
    'archive_incomplete': 'test_crash_after_the_intent_and_before_the_move_is_reported_blocks_appends_and_is_repeatable',
    'archive_root_invalid': 'test_archive_root_must_be_a_separate_real_directory_on_the_same_filesystem',
    'archive_exists': 'test_an_existing_archive_entry_blocks_the_move_before_the_intent',
    'noncanonical_event': 'test_load_refuses_duplicate_key_and_float_in_stored_event',
    'nothing_to_recover': 'test_recover_requires_lock_and_something_to_recover',
    'outcome_ambiguous': 'test_directory_fsync_failure_after_link_is_ambiguous_not_raw',
    'path_escape': 'test_unknown_file_and_symlink_refused',
    'reserved_kind': 'test_reserved_kind_refused',
    'schema_invalid': 'test_append_refuses_floats_and_nonjson_values',
    'sequence_conflict': 'test_exclusive_final_name_never_overwrites_an_existing_event',
    'sequence_gap': 'test_gap_in_sequence_detected',
    'sequence_mismatch': 'test_reordered_files_detected',
    'store_full': 'test_max_workflows_per_store',
    'torn_tail': 'test_break_lock_refused_when_log_has_torn_tail_unless_explicit',
    'truncated': 'test_truncation_detected_against_caller_held_head',
    'unexpected_file': 'test_unknown_file_and_symlink_refused',
    'unrecorded_quarantine': 'test_crash_between_quarantine_move_and_record_is_reported_then_recorded',
    'workflow_exists': 'test_duplicate_workflow_refused',
    'workflow_full': 'test_max_events_per_workflow',
    'workflow_id_mismatch': 'test_event_from_another_workflow_refused',
    'workflow_not_found': 'test_load_of_missing_workflow',
}


def _package_literals():
    raised, mentioned = set(), set()
    for name in os.listdir(PKG):
        if not name.endswith('.py'):
            continue
        tree = ast.parse(open(os.path.join(PKG, name)).read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, 'id', None) == 'StoreRefusal' and node.args \
                    and isinstance(node.args[0], ast.Constant):
                raised.add(node.args[0].value)
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                mentioned.add(node.value)
    return raised, mentioned


def _test_sources():
    out = {}
    for name in os.listdir(HERE):
        if name.startswith('test_workflow_store_') and name.endswith('.py'):
            src = open(os.path.join(HERE, name)).read()
            for node in ast.parse(src).body:
                if isinstance(node, ast.FunctionDef):
                    out[node.name] = ast.get_source_segment(src, node)
    return out


def test_literals_in_the_package_equal_the_closed_set():
    raised, mentioned = _package_literals()
    assert raised == ws.CODES
    assert ws.CODES <= mentioned


def test_every_code_has_a_named_negative_test_that_mentions_it():
    assert set(TRIGGERS) == set(ws.CODES)
    sources = _test_sources()
    for code, test in TRIGGERS.items():
        assert test in sources, (code, test)
        assert "'%s'" % code in sources[test], (code, test)
