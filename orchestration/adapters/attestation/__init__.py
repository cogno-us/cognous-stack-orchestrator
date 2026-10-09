"""Evidence-attestation adapter boundary."""
from .verifier import (
    ATTESTATION_REPOSITORY,
    ATTESTATION_REVISION,
    RESULT_VERSION,
    verify_attestation_binding,
)

__all__ = [
    "ATTESTATION_REPOSITORY",
    "ATTESTATION_REVISION",
    "RESULT_VERSION",
    "verify_attestation_binding",
]
