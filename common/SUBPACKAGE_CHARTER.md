# Common Package Sub-package Charter

## Allowed Sub-packages

### common.schemas
- **Owner:** data platform team
- **Purpose:** Cross-component schema definitions (Record, Feed envelope, etc.)
- **Public surface:** Record, Feed, Schema classes via `__all__`
- **Prohibited:** Business logic, UI code

### common.feeds
- **Owner:** data platform team
- **Purpose:** Feed reading and writing contracts
- **Public surface:** FeedReader, FeedWriter classes
- **Prohibited:** Component-specific logic

### common.bus
- **Owner:** infrastructure team
- **Purpose:** Message bus abstractions
- **Public surface:** Publisher, Subscriber, Topic classes
- **Prohibited:** Business domain knowledge

### common.config
- **Owner:** platform team
- **Purpose:** Centralized configuration layer
- **Public surface:** Config dataclass, load_config()
- **Prohibited:** Component-specific overrides

### common.observability
- **Owner:** observability team
- **Purpose:** Logging, metrics, tracing, correlation
- **Public surface:** Logger, emit_metric(), get_correlation_id()
- **Prohibited:** Component-specific observers

### common.lifecycle
- **Owner:** infrastructure team
- **Purpose:** Container lifecycle management
- **Public surface:** install_shutdown_handler(), seed_all(), env_isolation_check()
- **Prohibited:** Component-specific startup logic

### common.security
- **Owner:** security team
- **Purpose:** mTLS, token auth, secrets management
- **Public surface:** CertAuthority, InternalToken, SecretsBackend
- **Prohibited:** Application-level auth

### common.api
- **Owner:** API team
- **Purpose:** Cross-component API contracts
- **Public surface:** OpenAPI descriptors, gRPC stubs
- **Prohibited:** Handler implementations

### common.isolation
- **Owner:** platform team
- **Purpose:** Isolation policy and checking
- **Public surface:** IsolationChecker, policy loading
- **Prohibited:** Component-specific allow-lists

### common.test_fixtures
- **Owner:** all teams (shared)
- **Purpose:** Shared test fixtures across components
- **Public surface:** Fixture factories, mock data builders
- **Prohibited:** Cross-component integration (use component-specific fixtures)

### common.compat
- **Owner:** platform team
- **Purpose:** Version compatibility and migration
- **Public surface:** SkewMatrix, compat checks
- **Prohibited:** Business logic

### common.db
- **Owner:** database team
- **Purpose:** Database roles, owner checks, migrations
- **Public surface:** OwnerCheck, per-role connection strings
- **Prohibited:** ORM logic

### common.errors
- **Owner:** platform team
- **Purpose:** Cross-component error codes
- **Public surface:** NegelirError, error code registry
- **Prohibited:** Component-specific error handling
