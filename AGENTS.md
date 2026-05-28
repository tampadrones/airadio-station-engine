# AI Radio Project Instructions

This project is an AI radio platform. Treat it as a production-oriented monorepo.

When asked to build or fix features:
- inspect the current tree first
- identify backend, frontend, worker, Docker, and config boundaries
- make minimal working changes
- keep migrations, scripts, and compose files consistent
- run validation commands before declaring completion
- avoid placeholders unless explicitly asked
- prefer complete, testable implementation over partial sketches

For service work:
- inspect docker compose, running containers, logs, ports, and health checks
- do not destroy volumes or generated media without explicit approval
