# GigBid Web UI

React 18, TypeScript, Vite, and Playwright application. Start with `npm ci && npm run dev`.
The UI provides the sample job inbox, risk/evidence review drawer, editable proposal,
human approval/rejection actions, pipeline summary, and visible API errors. Its API URL defaults
to `http://localhost:8000` and may be changed with `VITE_API_URL` at build time. The Docker image
accepts this value through a build argument.

Run the seven browser tests with `npx playwright install chromium && npm test`. API requests in those
tests are intercepted; backend contract and persistence behavior is covered in Python tests.
Remaining required screens and a full multi-user onboarding experience are tracked in
`docs/IMPLEMENTATION_CHECKLIST.md`.
