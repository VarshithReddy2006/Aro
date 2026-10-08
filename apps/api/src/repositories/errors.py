"""Domain and persistence error taxonomy for Aro repositories."""


class PersistenceError(Exception):
    """Base exception for all repository and persistence failures."""


class NotFoundError(PersistenceError):
    """Raised when a requested resource does not exist."""

    def __init__(self, resource_type: str, identifier: str) -> None:
        self.resource_type = resource_type
        self.identifier = identifier
        super().__init__(f"{resource_type} with identifier '{identifier}' was not found.")


class ConflictError(PersistenceError):
    """Raised when an operation conflicts with current system state."""


class ConditionalWriteFailedError(ConflictError):
    """Raised when a DynamoDB condition expression evaluates to false."""


class VersionMismatchError(ConflictError):
    """Raised when optimistic concurrency detects a stale version during update."""

    def __init__(
        self, case_id: str, expected_version: int, actual_version: int | None = None
    ) -> None:
        self.case_id = case_id
        self.expected_version = expected_version
        self.actual_version = actual_version
        msg = f"Version conflict for case '{case_id}': expected {expected_version}"
        if actual_version is not None:
            msg += f", but current version is {actual_version}"
        super().__init__(msg)


class DuplicateRequestError(ConflictError):
    """Raised when an identical request or event ID is submitted."""

    def __init__(self, request_id: str) -> None:
        self.request_id = request_id
        super().__init__(f"Duplicate request detected for identifier '{request_id}'.")


class IdempotencyConflictError(ConflictError):
    """Raised when a concurrent or conflicting operation holds an idempotency lock."""

    def __init__(self, key: str, status: str) -> None:
        self.key = key
        self.status = status
        super().__init__(f"Idempotency conflict for key '{key}' with status '{status}'.")


class OrganizationAccessDeniedError(PersistenceError):
    """Security violation: Attempted unauthorized cross-tenant organization access."""

    def __init__(self, target_resource: str, expected_org_id: str, actual_org_id: str) -> None:
        self.target_resource = target_resource
        self.expected_org_id = expected_org_id
        self.actual_org_id = actual_org_id
        super().__init__(
            f"Cross-organization access denied: target resource '{target_resource}' "
            f"belongs to organization '{actual_org_id}', not '{expected_org_id}'."
        )


class AlreadyExecutingError(ConflictError):
    """Raised when an action or operation is currently executing and cannot be re-executed concurrently."""

    def __init__(self, action_id: str) -> None:
        self.action_id = action_id
        super().__init__(f"Action '{action_id}' is already executing.")


class AlreadyCompletedError(ConflictError):
    """Raised when an action has already reached completion and cannot be re-executed."""

    def __init__(self, action_id: str) -> None:
        self.action_id = action_id
        super().__init__(f"Action '{action_id}' has already completed.")
