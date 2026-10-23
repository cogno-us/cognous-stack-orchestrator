"""Orchestrator-side checkpoint production. Non-authorizing; pure; no I/O, clock, network or subprocess.

The producer holds no anchor: it derives a checkpoint from a head the store reported and from the
last checkpoint the custodian acknowledged (supplied by the caller). Retention is the custodian's.
"""
from . import record
from .refusal import CheckpointRefusal


def checkpoint_from_head(workflow_id, head_count, head_digest, producer, previous=None):
    """Checkpoint for (count, digest). `previous` is the last custodian-acknowledged record or None."""
    if previous is None:
        return record.build(workflow_id, head_count, head_digest, producer, 1, None)
    record.validate(previous)
    if previous['workflow_id'] != workflow_id:
        raise CheckpointRefusal('workflow_mismatch', 'previous checkpoint belongs to another workflow')
    return record.build(workflow_id, head_count, head_digest, producer,
                        previous['checkpoint_sequence'] + 1, previous['digest'])


def checkpoint_from_loaded(loaded, producer, previous=None):
    """Checkpoint from a workflow_store LoadedWorkflow (head_sequence is the event count)."""
    return checkpoint_from_head(loaded.workflow_id, loaded.head_sequence, loaded.head_digest, producer, previous)
