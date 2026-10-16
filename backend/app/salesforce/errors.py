class SalesforceError(Exception):
    """Salesforce rejected a request (message is safe to show to the user)."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class SalesforceAuthExpired(SalesforceError):
    """The stored tokens no longer work; the user must reconnect."""
