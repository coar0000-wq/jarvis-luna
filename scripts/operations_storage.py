"""Explicit operations-state capacity; no IO, pruning, reset or trust bypass.

Only the canonical state path gets the larger budget. Callers still own safe
paths, JSON/schema validation, authentication and atomic replacement.
"""
OPS_STATE_PATH = 'data/operations/state.json'
OPS_STATE_MAX_BYTES = 32 * 1024 * 1024


def operations_file_max_bytes(relative, ordinary_max_bytes=8 * 1024 * 1024):
    """Return the state exception only for its exact canonical repository path."""
    return OPS_STATE_MAX_BYTES if relative == OPS_STATE_PATH else ordinary_max_bytes


def require_operations_state_size(body):
    """Reject oversized serialized bytes before a caller mutates any files."""
    if not isinstance(body, bytes):
        raise TypeError('operations state must be serialized bytes')
    if len(body) > OPS_STATE_MAX_BYTES:
        raise ValueError('operations state storage capacity reached; pruning/reset forbidden')
