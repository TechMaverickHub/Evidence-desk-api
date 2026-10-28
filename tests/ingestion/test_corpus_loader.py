from collections.abc import Callable
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.auth.models import Tenant
from app.documents import service as documents_service
from app.ingestion import cli

FIXTURE_MANIFEST = Path(__file__).parents[1] / "fixtures" / "corpus" / "manifest.yaml"


@pytest.fixture(autouse=True)
def use_test_session(monkeypatch: pytest.MonkeyPatch, db_session: Session) -> None:
    # Run the CLI inside this test's rolled-back session instead of a real one.
    monkeypatch.setattr(cli, "get_sessionmaker", lambda: lambda: db_session)


def test_loads_every_manifest_entry_with_its_licence(
    db_session: Session, make_tenant: Callable[..., Tenant]
) -> None:
    tenant = make_tenant("corpus-tenant")

    exit_code = cli.main(
        ["load-corpus", "--tenant", tenant.name, "--manifest", str(FIXTURE_MANIFEST)]
    )

    assert exit_code == 0
    documents, total = documents_service.list_documents(db_session, tenant.id, None, None, 10, 0)
    assert total == 2
    by_slug = {document.slug: document for document in documents}
    assert by_slug["incidents/0001"].doc_metadata == {
        "license": "CC0-1.0",
        "path": "incident-0001.md",
    }


def test_second_run_is_a_no_op(make_tenant: Callable[..., Tenant]) -> None:
    tenant = make_tenant()

    first = cli.load_corpus(tenant.name, FIXTURE_MANIFEST)
    second = cli.load_corpus(tenant.name, FIXTURE_MANIFEST)

    assert (first, second) == ((2, 0), (0, 2))


@pytest.mark.parametrize(
    ("manifest_text", "expected_message"),
    [
        ("documents: []", "Invalid manifest"),
        (
            "documents: [{path: missing.md, source: s, slug: s, "
            "version: '1', title: t, license: MIT}]",
            "Cannot load missing.md",
        ),
        ("documents: [unclosed", "Invalid manifest"),
    ],
)
def test_bad_manifest_fails_with_a_clear_message(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    make_tenant: Callable[..., Tenant],
    manifest_text: str,
    expected_message: str,
) -> None:
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(manifest_text, encoding="utf-8")

    exit_code = cli.main(
        ["load-corpus", "--tenant", make_tenant().name, "--manifest", str(manifest)]
    )

    assert exit_code == 1
    assert expected_message in capsys.readouterr().err


def test_unknown_tenant_fails(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = cli.main(["load-corpus", "--tenant", "nope", "--manifest", str(FIXTURE_MANIFEST)])

    assert exit_code == 1
    assert "Unknown tenant 'nope'" in capsys.readouterr().err
