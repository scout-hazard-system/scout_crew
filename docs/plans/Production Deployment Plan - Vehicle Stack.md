# Problem statement
Deploy the current local\-first vehicle stack \(pipeline, Java backend, frontend UI\) into a production\-ready environment that remains lightweight for in\-vehicle use, supports future companion app growth, and can evolve to consumer\-scale operation\.
## Current state
The stack currently runs on one machine with no required cloud infrastructure using a unified launcher script \(`run_vehicle_stack.sh`\) and a lightweight executable JAR build flow \(`frontend/java_backend/build_executable.sh`\)\.
The backend exposes local APIs for pipeline, route/weather, and mobile bootstrap/snapshot/stream capabilities, and the frontend consumes those APIs through configurable base URLs\.
## Deployment objectives
Primary objective is reliability under long\-running vehicle sessions with minimal operational overhead\.
Secondary objective is clean migration path from single\-machine LAN mode to hosted production services without breaking API contracts used by frontend and mobile clients\.
## Production deployment architecture
Phase 1 should keep the current single\-node model but formalize service supervision, startup ordering, and restart behavior\.
Phase 2 should separate concerns into independently deployable services: ingest pipeline worker, API service, and static frontend delivery\.
Phase 3 should add managed external dependencies \(weather/provider integrations, auth, push channels\) while preserving compatibility with existing `/api/*` contracts\.
## Runtime and packaging plan
Standardize releases around versioned executable JAR artifacts plus a versioned launcher package\.
Introduce environment\-specific config files for ports, log paths, provider settings, and feature flags rather than hardcoded values\.
Package launcher and configs into an install bundle that supports Linux first, then add per\-OS wrappers for Windows/macOS\.
## Process supervision and startup plan
Replace ad\-hoc backgrounding with a supervised runtime target \(for example: systemd user service on Linux\) that starts pipeline, backend, and UI bridge in deterministic order\.
Enforce health\-gated startup: backend health endpoint must be healthy before frontend is marked ready\.
Add restart policies with backoff and bounded retry counts to prevent crash loops from draining power/resources in vehicle operation\.
## Networking and security plan
Default to LAN\-local access with explicit bind/port config and firewall allow rules for trusted local subnet only\.
Add optional remote access mode behind TLS reverse proxy when cloud rollout begins\.
Move all provider credentials/API keys to environment secrets and scrub secrets from logs and crash outputs\.
## Data and privacy plan
Define retention windows for pipeline transcripts/events and implement periodic cleanup to keep local disk usage bounded\.
Classify data fields into required runtime telemetry versus optional analytics and disable non\-essential collection by default\.
Add user\-visible controls for data retention policy and local data purge in companion/mobile flows\.
## Observability and diagnostics plan
Add structured logs for process lifecycle, health checks, provider calls, and endpoint error categories\.
Expose lightweight status endpoints for launcher/runtime diagnostics that can be checked by mobile clients\.
Add rotation/size limits for all local logs to avoid unbounded growth during long vehicle sessions\.
## API/provider readiness plan
Freeze versioned API contracts for `/api/pipeline/*`, `/api/platform/*`, and `/api/mobile/*` and add compatibility tests\.
Implement provider adapters behind interfaces so weather/map providers can be swapped without frontend contract changes\.
Track provider compliance requirements \(terms, attribution, rate limits\) as explicit release criteria before consumer launch\.
## Rollout plan
First rollout target is a controlled private beta using the current local\-LAN deployment model with scripted install/start workflows\.
Second rollout adds staged remote access and telemetry dashboards while maintaining backward\-compatible local mode\.
Consumer rollout should require passing reliability SLOs, privacy controls, provider compliance, and upgrade rollback validation\.
## Validation and acceptance criteria
Stack must auto\-start and recover cleanly after reboot/power interruption on target hardware\.
Launcher status must accurately reflect process state and health for pipeline, backend, and UI services\.
Mobile bootstrap/snapshot/stream endpoints must remain low\-latency and stable across extended runtime sessions\.
No credential leakage, uncontrolled log growth, or repeated crash loops should occur during endurance runs\.