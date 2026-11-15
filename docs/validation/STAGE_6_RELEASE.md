# Stage 6 Release Readiness

## Workstation layout

The frontend now uses a compact header, a keyboard-accessible activity rail, a
site directory and calculation controls, a dominant global Moon viewport, a
selected-site inspector, a separate local terrain preview, and a bottom results
area. Registered 2D lunar map layers remain available in a disclosure below the
global viewport. The inspector displays values returned by the API when present;
it does not calculate visibility or ranking values.

This change preserves the existing API client, observation/timeline/comparison
flows, job polling, terrain coverage and heightmap requests, map layer client,
CSA resource client, and scene implementations.

## Verification in this checkout

Application commit: `eafdca559d71c52efdf188c3cabfa1f6ebbd67e3`.

| Check | Result |
| --- | --- |
| Frontend lint | Passed (`npm.cmd run lint`) |
| OpenAPI generated types | Passed (`npm.cmd run check:api`) |
| Frontend tests | Passed: 200 tests in 16 files (`npm.cmd test -- --run`) |
| Production build | Passed (`npm.cmd run build`); Vite reports a 1.3 MB JavaScript chunk warning |
| API-backed browser workflow | Not run; Docker Desktop returned permission denied for its engine pipe |
| Browser visual review | Not completed; the CUA browser timed out opening the local Vite URL |
| Screenshots and viewport measurements | Not captured |
| Backend suite and PostgreSQL integration | Not run in this Stage 6 pass |
| Current commit CI | No status checks were returned for the local HEAD SHA |

The controlled frontend tests mock API responses. They verify UI workflow
behavior but do not establish live backend integration. The browser visual
acceptance and release gate therefore remain open. The approved reference image
was not available in the working tree or this task input, so comparison here is
against the written composition checklist only.

Local frontend verification used Node `v24.16.0` and npm `11.13.0`. The
repository pins Node `22.13.0` in `.nvmrc`, and GitHub Actions reads that file;
rerun locally with the pinned version when available.

## Reproduction

Use Node 22.13.0, then from `frontend/`:

```powershell
npm ci
npm run lint
npm run check:api
npm test -- --testTimeout=10000
npm run build
```

For live integration, follow the root README to start PostgreSQL, apply backend
migrations, run the API and the separate observation worker, and configure
`frontend/.env.local` with `VITE_API_URL` if the API is not at its default
address. Keep backend `CORS_ORIGINS` aligned with the frontend origin. Do not put
credentials in frontend configuration.

## Remaining release checks

- Review the rendered workstation at desktop and compact viewport sizes against
  the approved reference and save screenshots.
- Run representative observation, timeline playback, comparison, terrain
  unavailable, provider failure, and stale-response workflows against the
  known local application version.
- Run the backend suite and PostgreSQL integration tests in their intended
  isolated environment.
- Confirm deployment hosting limits, terrain asset provisioning, database
  backup/recovery, and provider behavior before selecting or publishing to a
  host. No hosting plan or deployment is selected by this report.
