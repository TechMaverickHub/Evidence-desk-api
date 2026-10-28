"""Guards the per-test rollback in conftest: both tests insert the same unique name, so
the second one fails with a unique violation if the first one's data leaked."""

from collections.abc import Callable

from app.auth.models import Tenant

PROBE_NAME = "rollback-probe"


def test_first_insert_of_probe_tenant(make_tenant: Callable[..., Tenant]) -> None:
    assert make_tenant(PROBE_NAME).name == PROBE_NAME


def test_second_insert_of_probe_tenant(make_tenant: Callable[..., Tenant]) -> None:
    assert make_tenant(PROBE_NAME).name == PROBE_NAME
