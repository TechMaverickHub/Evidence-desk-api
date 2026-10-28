# Task 002 — Auth: tenants, users, JWT, RBAC

**Status:** ✅ Done (2026-10-27); 33 tests passed, ruff clean
**Week:** W1 · **Modules:** `app/auth`, `app/core` · **Branch:** `task/002-auth`

## Goal

Every later endpoint can ask "who is calling, which tenant are they in, and what may they
do?" with one dependency, and the test suite has helpers to prove that one tenant can never
see another tenant's data.

## Scope

In:
- `tenants` and `users` tables (migration `0002`).
- Password hashing (argon2) and JWT access tokens (HS256, 60 min).
- `POST /v1/auth/token`, `GET /v1/auth/me`, `POST /v1/auth/users` (see [api-spec.md](../api-spec.md)).
- Dependencies `get_current_user` and `require_role(Role.X)` in `app/core/deps.py`.
- CLI to create a tenant and its first admin: `uv run python -m app.auth.cli create-tenant`.
- New `AppError` subclasses: `NotAuthenticatedError`, `InvalidCredentialsError`,
  `ForbiddenError`, `ConflictError`.
- Test infrastructure: migrate the test DB once per session, roll back each test, and
  fixtures `make_tenant`, `make_user`, `auth_headers`.

Out (recorded under Future improvements):
- Refresh tokens, logout / token revocation, password reset, user deactivation endpoint.
- Login rate limiting / lockout.
- Tenant management over HTTP (tenants are created only by the CLI).
- Postgres row-level security (plan.md lists it as possible hardening).

## Assumptions

1. **Email is globally unique**, not per tenant, so login needs only email + password (no
   tenant picker). A person in two tenants needs two emails. Fine for this project.
2. An admin may create users of **any role, including admin, but only in their own tenant**.
3. A 60-minute access token without refresh is acceptable for an API used by a dashboard and
   scripts. The trade-off is that a stolen token stays valid until it expires.
4. One symmetric signing key (`JWT_SECRET_KEY`) is enough; no key rotation yet.

## Architecture decisions

| Decision | Choice | Reason / trade-off |
|---|---|---|
| Source of truth for tenant and role | **The DB row**, loaded by `get_current_user` on every request (one primary-key lookup) | A deactivated user or changed role takes effect at once, not after token expiry. The token still carries `tenant_id` and `role` claims for clients and logs, but the server never authorises from them alone |
| Token format | JWT HS256 via PyJWT; claims `sub`, `tenant_id`, `role`, `iat`, `exp` | Standard and inspectable. Decoding passes `algorithms=["HS256"]` explicitly, which rejects `alg: none` and algorithm-swap tokens |
| Password hashing | `pwdlib` with argon2id (`PasswordHash.recommended()`) | What the FastAPI docs recommend now; `passlib` is unmaintained |
| Login form | OAuth2 password flow (`OAuth2PasswordRequestForm`, `username` = email) | Makes Swagger's "Authorize" button work out of the box. Needs `python-multipart` |
| User enumeration | Same 401 `INVALID_CREDENTIALS` for unknown email, wrong password and inactive user; a dummy hash is verified when the email is unknown | Response body and timing don't reveal which emails exist |
| Role hierarchy | `Role` is a `StrEnum` with a rank: `viewer < editor < admin`; `require_role(Role.EDITOR)` allows editor and admin | One comparison instead of role lists repeated across routers (DRY) |
| Tenant in requests | Never accepted from the body. `CreateUserRequest` uses `extra="forbid"`, so sending `tenant_id` is a 422, not silently ignored | Makes the tenant boundary explicit and testable |
| Repositories | Module-level functions taking a `Session` (e.g. `get_user_by_email(session, email)`) | No class needed for a handful of queries; tenant-owned lookups take a required `tenant_id` |
| CLI | `argparse` + `getpass` (password never passed as an argument, so it isn't kept in shell history) | No extra CLI dependency |
| Test isolation | Each test runs inside an outer transaction with `join_transaction_mode="create_savepoint"` and is rolled back | Fast, no cleanup code, and services can still call `session.begin()` normally |

### Design principles applied

| Principle | Where it shows up |
|---|---|
| SRP | `security.py` only hashes and signs/verifies tokens; `repository.py` only queries; `service.py` holds the rules (authenticate, create user, create tenant with admin); `router.py` only maps HTTP to the service; `cli.py` only parses arguments and calls the same service |
| OCP | New protected endpoints declare `Depends(require_role(Role.X))`; nothing in auth changes. New error types are `AppError` subclasses |
| LSP | All four new errors render through the existing handler with the same envelope |
| ISP / DIP | Routers depend on `CurrentUser` (a small frozen dataclass: `id`, `tenant_id`, `role`, `email`), not on the ORM `User` model, so later modules don't couple to auth's tables. No `Protocol` for hashing or tokens: one implementation each |
| DRY | One `require_role` factory, one `CurrentUser` loader. The CLI and the endpoint share `service.create_user` |
| Flat control flow | `authenticate` and `get_current_user` use guard clauses (missing token → invalid → user not found → inactive) |
| Error handling | `jwt.InvalidTokenError` (covers expired, bad signature, malformed) is caught at the security boundary and becomes `NotAuthenticatedError`; `IntegrityError` on duplicate email becomes `ConflictError` |

### Dependencies added (and why)
- `pyjwt` — sign and verify JWTs.
- `pwdlib[argon2]` — argon2id password hashing.
- `python-multipart` — FastAPI needs it to parse the OAuth2 login form.
- `email-validator` — backs Pydantic's `EmailStr` for real email validation.

### Small change to existing code
`AppError` gains an optional `headers` class attribute, and `_handle_app_error` passes it on,
so 401 responses can send `WWW-Authenticate: Bearer` as the HTTP spec requires. Existing
behaviour is unchanged when `headers` is empty.

## Data model (migration `0002_auth_tables`)

- **tenants**: `id UUID PK`, `name VARCHAR(100) UNIQUE NOT NULL`, `created_at`.
- **users**: `id UUID PK`, `tenant_id UUID FK tenants RESTRICT NOT NULL (indexed)`,
  `email VARCHAR(254) UNIQUE NOT NULL` (stored lower-case), `password_hash VARCHAR NOT NULL`,
  `role VARCHAR(16) NOT NULL CHECK (role IN ('admin','editor','viewer'))`,
  `is_active BOOLEAN NOT NULL DEFAULT true`, `created_at`.

## API

| Method | Path | Roles | Request | Response |
|---|---|---|---|---|
| POST | `/v1/auth/token` | public | form: `username` (email), `password` | `200 {access_token, token_type: "bearer", expires_in}`; `401 INVALID_CREDENTIALS` |
| GET | `/v1/auth/me` | any | — | `200 {id, email, role, tenant: {id, name}}` |
| POST | `/v1/auth/users` | admin | `{email, password, role}` | `201 {id, email, role, tenant_id}`; `409 CONFLICT` duplicate email; `403 FORBIDDEN` non-admin |

Validation: password 12–128 characters (upper bound stops very large inputs to argon2);
email normalised to lower case.

## Files to create / modify

```
pyproject.toml, uv.lock            + pyjwt, pwdlib[argon2], python-multipart, email-validator
.env.example                       + JWT_SECRET_KEY (dummy), ACCESS_TOKEN_EXPIRE_MINUTES
app/core/config.py                 + jwt_secret_key (required, min 32 chars), access_token_expire_minutes
app/core/errors.py                 + headers on AppError; NotAuthenticated/InvalidCredentials/Forbidden/Conflict errors
app/core/security.py               hash_password, verify_password, create_access_token, decode_access_token
app/core/deps.py                   CurrentUser, get_current_user, require_role
app/auth/__init__.py
app/auth/models.py                 Tenant, User, Role
app/auth/schemas.py                TokenResponse, CreateUserRequest, UserResponse, MeResponse
app/auth/repository.py             get_user_by_email, get_user_in_tenant, get_tenant, add_tenant, add_user
app/auth/service.py                authenticate, create_user, create_tenant_with_admin
app/auth/router.py                 /v1/auth/token, /v1/auth/me, /v1/auth/users
app/auth/cli.py                    create-tenant command
app/main.py                        include auth router (one line)
migrations/env.py                  import app.auth.models so autogenerate sees them
migrations/versions/0002_auth_tables.py
tests/conftest.py                  migrate test DB, per-test rollback session, make_tenant/make_user/auth_headers
tests/core/test_security.py
tests/auth/test_login.py
tests/auth/test_current_user.py
tests/auth/test_create_user.py
.claude/api-spec.md, .claude/database.md, .claude/tasks.md   status updates at handover
```

`require_role` and `CurrentUser` live in `app/core/deps.py` (not `app/auth`) because every
feature module will import them; `deps.py` imports from `app.auth.repository` to load the user.

## Step-by-step implementation plan

0. `git switch -c task/002-auth` from `task/001-project-setup` (001 is not merged into
   `dev` yet; rebase onto `dev` once it is).
1. `uv add` the four dependencies; add settings and `.env.example` entries.
2. `security.py` + its unit tests (hash/verify round trip, token round trip, expired token,
   tampered signature, `alg: none` token).
3. Add `headers` to `AppError` and the four error subclasses.
4. `models.py` (`Role` enum with rank, `Tenant`, `User`); import in `migrations/env.py`;
   autogenerate `0002`, review it by hand, add the CHECK constraint; upgrade/downgrade/upgrade.
5. `tests/conftest.py`: run `alembic upgrade head` on the test DB at session start; per-test
   connection + transaction + savepoint session; override `get_session`; add the factories.
6. `repository.py` and `service.py` (authenticate with dummy-hash check, create_user,
   create_tenant_with_admin).
7. `deps.py` (`get_current_user` with `OAuth2PasswordBearer`, `require_role`).
8. `schemas.py`, `router.py`, register the router in `main.py`.
9. `cli.py`; try it once against the dev DB and log in through Swagger.
10. Tests (below), `ruff check`, `ruff format --check`, `alembic check`; update docs and handover.

## Tests (chosen by risk)

| Risk | Test |
|---|---|
| Token forgery | Tampered signature, `alg: none`, expired token, token for a deleted user → all 401 |
| Stale permissions | Token issued, then user set inactive → 401 on the next request |
| User enumeration | Unknown email and wrong password return identical status and body |
| Privilege | Viewer and editor get 403 on `POST /auth/users`; admin gets 201 |
| **Cross-tenant** | Admin of tenant A creates a user → the user belongs to A; body containing `tenant_id` → 422; `/auth/me` for users in A and B returns their own tenant only |
| Duplicates | Same email twice (different case) → 409 |
| Password storage | Stored hash is argon2id and never equals the password; responses never include `password_hash` |
| Missing token | No `Authorization` header → 401 with `WWW-Authenticate: Bearer` |

## Edge cases and security

- `JWT_SECRET_KEY` is required with no default and must be ≥ 32 characters; the app refuses
  to start otherwise. The `.env.example` value is a clearly fake placeholder.
- Emails compared lower-case at both creation and login.
- `password_hash` never leaves the service layer: response schemas are explicit, never
  `from_attributes` dumps of the whole model.
- Logs record login success/failure with user id when known, never the password, the token
  or the submitted email for failed attempts.

## Risks

- **Savepoint-based test isolation surprises** (e.g. a service that commits outside
  `session.begin()`). Mitigation: services only use `with session.begin():`; one test
  checks rollback works by asserting a created tenant is gone in the next test.
- **argon2 makes tests slow** (each hash takes tens of ms). Mitigation: hash the shared test
  password once per session in the `make_user` fixture.
- **python-multipart parser CVEs** have happened before. Mitigation: keep it current via
  `uv lock --upgrade-package` when advisories appear.

## Future improvements

- Refresh tokens + revocation list, if a long-lived dashboard session is needed.
- Login rate limiting / lockout.
- `PATCH /v1/auth/users/{id}` to deactivate users or change roles (with an audit log).
- Postgres row-level security on tenant tables as a second line of defence.
- Signing-key rotation (`kid` header).

## Checklist

- [x] Branch `task/002-auth`
- [x] Dependencies added with reasons; settings + `.env.example`
- [x] `security.py` + unit tests
- [x] `AppError.headers` + four error subclasses
- [x] Models + migration `0002` (upgrade/downgrade verified, `alembic check` clean)
- [x] Test infrastructure: migrated test DB, per-test rollback, factories
- [x] Repository + service
- [x] `deps.py`: `CurrentUser`, `get_current_user`, `require_role`
- [x] Router + schemas, registered in `main.py`
- [x] CLI `create-tenant`, tried against the dev DB
- [x] Tests in the table above pass; `ruff check`, `ruff format --check` clean
- [x] Self-review against the design-principles table
- [x] Update [api-spec.md](../api-spec.md), [database.md](../database.md), [tasks.md](../tasks.md), handover below

---

## Handover

### Summary
Tenants and users with argon2id passwords, HS256 JWT access tokens, and three endpoints
(`POST /v1/auth/token`, `GET /v1/auth/me`, `POST /v1/auth/users`). `app/core/deps.py` gives
every later module `SessionDep`, `CurrentUserDep` and `require_role(Role.X)`. A CLI creates a
tenant with its first admin. The test suite now migrates the test DB, rolls back every test,
and offers `make_tenant`, `make_user` and `auth_headers`. 33 tests (25 new) pass.

### Architecture Notes
- `get_current_user` decodes the token, then loads the user with **both** `user_id` and
  `tenant_id` from the claims. A validly signed token whose tenant claim doesn't match the
  user's real tenant is a 401. Role and tenant in `CurrentUser` come from the row.
- `Role.includes()` implements the hierarchy (admin ⊃ editor ⊃ viewer) in one place.
- `role` is mapped with SQLAlchemy `Enum(native_enum=False, create_constraint=True)`, which
  produces `VARCHAR(16)` + a `user_role` CHECK constraint without hand-written SQL.
- `AppError.headers` lets 401s send `WWW-Authenticate: Bearer`. `ErrorResponse` (a Pydantic
  model of the envelope) was added so routers can document error responses in OpenAPI.
- The CLI reuses `CreateUserRequest` for email and password validation, and the same
  `service.create_tenant_with_admin` code path a future endpoint would use.

### Deviations from the plan
- **Services call `session.commit()` instead of `with session.begin():`.** `get_current_user`
  reads from the session first, which auto-begins a transaction, so a later `session.begin()`
  would raise. architecture.md and coding-standards.md are updated.
- **All timestamps are `TIMESTAMPTZ`**, set once in `Base.type_annotation_map`, instead of
  naive `timestamp` (the autogenerate default).
- **Migration template modernised** (`collections.abc.Sequence`, `X | None`) so new
  revisions pass ruff without edits.
- Test emails use `example.com`: `email-validator` rejects the reserved `.test` TLD.
- Extra tests beyond the plan: tampered payload with original signature, non-UUID `sub`,
  short password → 422, CLI happy path.
- Manual check: tenant + admin created on the dev DB via the real (non-test) session, login,
  `/me`, user creation and duplicate-tenant conflict all worked; rows deleted afterwards.

### Database Changes
- `0002_auth_tables`: `tenants`, `users` (FK `RESTRICT`, index on `tenant_id`, unique
  `email`, CHECK `user_role`). Upgrade → downgrade → upgrade verified; `alembic check` clean.

### API Changes
- `POST /v1/auth/token`, `GET /v1/auth/me`, `POST /v1/auth/users` (details in api-spec.md).

### Evaluation Results
None.

### Future Work
- As listed under Future improvements (refresh tokens, rate limiting, deactivate endpoint,
  RLS, key rotation).
- A CLI option to read the password from an env var for non-interactive setup (task 013,
  Docker/CI).

### Modified Files
| File | Why |
|---|---|
| `pyproject.toml`, `uv.lock` | `pyjwt`, `pwdlib[argon2]`, `python-multipart`, `email-validator` |
| `.env.example` | `JWT_SECRET_KEY`, `ACCESS_TOKEN_EXPIRE_MINUTES` |
| `app/core/config.py` | Required JWT secret (≥ 32 chars), token lifetime |
| `app/core/db.py` | TIMESTAMPTZ type map on `Base` |
| `app/core/errors.py` | `headers`, four error subclasses, `ErrorResponse` |
| `app/core/security.py` | Hashing and JWT |
| `app/core/deps.py` | `SessionDep`, `CurrentUser`, `get_current_user`, `require_role` |
| `app/auth/{models,schemas,repository,service,router,cli}.py` | Auth feature |
| `app/main.py` | Register auth router |
| `migrations/env.py`, `migrations/script.py.mako`, `migrations/versions/0002_auth_tables.py` | Models import, template, migration |
| `tests/conftest.py` | Migrate test DB, per-test rollback, factories, `auth_headers` |
| `tests/test_isolation.py`, `tests/core/test_security.py`, `tests/auth/*` | Tests |
| `.claude/{architecture,coding-standards,api-spec,database,plan,tasks}.md` | Docs in step with the code |
