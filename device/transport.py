"""Exceptions shared by every jobs transport (fake for L2, real AWS IoT for L3)."""


class NetworkError(Exception):
    """The link to the cloud is down (blackholed / unreachable)."""


class JobRejected(Exception):
    """Cloud refused a job update, e.g. the execution already TIMED_OUT."""


class FetchError(Exception):
    """A release artifact could not be fetched (missing object, bad URL)."""
