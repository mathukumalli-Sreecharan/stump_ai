# ModelStump development roadmap

## Security blockers

1. Implement and independently review a Windows execution backend using a restricted identity/AppContainer or another defensible OS boundary, Job Objects, memory/process/file limits, network denial, and process-tree cleanup.
2. Add adversarial escape tests before allowing untrusted code.
3. Replace process-local rate limiting with a deployment-appropriate shared limiter before multi-worker use.

## Benchmark quality

1. Add independent reference oracles and metamorphic/property-based checks for supported task families.
2. Expand failure categories only when the recorded evidence supports them.
3. Track generation and target model configurations plus before/after adaptive performance on independent task sets.
4. Broaden archetype-specific validators and structural diversity evaluation.

## Reliability and data

1. Add resumable persisted jobs, progress events, safe cancellation, and job retention policy.
2. Add formal migration tooling and backup/restore exercises.
3. Add dataset version manifests and export-history records.
4. Add SQL aggregate analytics and pagination for every high-volume endpoint.

## Frontend

1. Add evaluation history/actions, failure and weakness views, adaptive generation, dataset export controls, and settings/model health pages.
2. Add component/API tests and accessible loading/empty/error states.
3. Split large dashboard bundles and lazy-load charting code.

## Verification

Run the mocked regression suite and frontend production build on each change. A real Ollama smoke test is separate and must record the actual configured generator/target models and results.
