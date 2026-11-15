import { expect, test } from "@playwright/test";

const job = {
  job_id: "sample-job-001",
  title: "Build a customer churn prediction baseline",
  description: "Compare classification models with Python.",
  required_skills: ["Python", "classification"],
  budget: { min: 250, max: 450, currency: "USD" },
  duration_days: 14,
  connects_cost: 8,
  recommendation: "bid",
  fit_score: 1,
  risk_score: 0,
  suggested_price_usd: 250,
};

const proposal = {
  id: "proposal-001",
  job_id: "sample-job-001",
  status: "awaiting_review",
  proposal: {
    cover_letter: "My portfolio includes Customer churn classification coursework.",
    screening_answers: [],
  },
  analysis: {
    decision: { action: "bid", reasons: ["Skill coverage meets threshold."] },
    risk_report: { score: 0, flags: [], explanation: "No risk signal." },
    fit_report: { score: 1, matched_skills: ["Python"], missing_skills: [] },
    price_quote: { amount: 250, connects_cost: 8, rationale: "Within the listed budget." },
    evidence: [{
      evidence_id: "evidence-001",
      title: "Customer churn classification coursework",
      summary: "Built a Python classification model and evaluated precision and recall.",
      outcome: "coursework demonstration",
      source: "synthetic sample",
    }],
    claim_verification: [{
      claim: "My portfolio includes Customer churn classification coursework.",
      status: "supported",
      evidence_ids: ["evidence-001"],
    }],
    compliance_verdict: { allowed: true, violations: [] },
    dry_run: { external_write_enabled: false, connects_cost: 8 },
  },
};

async function installApiMocks(page, fail = false) {
  const messages = [];
  await page.route("http://localhost:8000/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (fail) {
      await route.fulfill({ status: 503, json: { detail: "API unavailable" } });
    } else if (path === "/api/jobs") {
      await route.fulfill({ status: 200, json: [job] });
    } else if (path === "/api/proposals" && request.method() === "GET") {
      await route.fulfill({ status: 200, json: [] });
    } else if (path === "/api/messages" && request.method() === "GET") {
      await route.fulfill({ status: 200, json: messages });
    } else if (path === "/api/messages/draft" && request.method() === "POST") {
      const body = request.postDataJSON();
      const negotiating = /\$\s*\d/.test(body.message);
      const message = {
        id: "message-001", job_id: body.job_id, status: "awaiting_review",
        intent: negotiating ? "negotiation" : "interview_request",
        incoming_message: body.message,
        draft: negotiating
          ? "My minimum for this scope is $200. If that works, I can confirm the deliverables."
          : "Thanks for reaching out. I can discuss the project.",
        negotiation_decision: negotiating ? {
          action: "counter", offered_amount: 150, offer_unit: "fixed",
          recommended_amount: 200, unit: "fixed", profile_floor: 200,
          budget_ceiling: 450, reason: "The offer is below the selected profile's minimum rate.",
        } : undefined,
      };
      messages.unshift(message);
      await route.fulfill({ status: 201, json: message });
    } else if (path === "/api/messages/message-001/approve") {
      await route.fulfill({ status: 200, json: { id: "message-001", external_send: "simulated" } });
    } else if (path === "/api/messages/message-001/reject") {
      await route.fulfill({ status: 200, json: { id: "message-001", status: "rejected" } });
    } else if (path === "/api/runs") {
      await route.fulfill({ status: 200, json: [] });
    } else if (path === "/api/analytics") {
      await route.fulfill({
        status: 200,
        json: {
          proposal_count: 0, simulated_outcome_count: 0,
          simulated_reply_rate: null, simulated_hire_rate: null,
          synthetic_connects_spent: 0, outcome_provenance: "synthetic_simulator",
        },
      });
    } else if (path === "/api/portfolio") {
      await route.fulfill({
        status: 200,
        json: {
          profiles: [{
            freelancer_id: "sample-ai-engineer", display_name: "Alex (synthetic)",
            headline: "Junior AI/ML Engineer", hourly_rate_usd: 25,
            minimum_project_budget_usd: 200, skills: ["Python"],
          }],
          evidence: [], provenance: "synthetic_personas_and_portfolio_examples",
          uploads_enabled: false,
        },
      });
    } else if (path.endsWith("/analyze") && request.method() === "POST") {
      await route.fulfill({ status: 201, json: proposal });
    } else if (path === "/api/proposals/proposal-001" && request.method() === "PUT") {
      const body = request.postDataJSON();
      await route.fulfill({
        status: 200,
        json: { ...proposal, status: "edited", proposal: { ...proposal.proposal, ...body } },
      });
    } else if (path.endsWith("/approve")) {
      await route.fulfill({
        status: 200,
        json: {
          id: proposal.id,
          status: "approved",
          external_submission: "disabled; no marketplace write was made",
        },
      });
    } else if (path.endsWith("/reject")) {
      await route.fulfill({ status: 200, json: { id: proposal.id, status: "rejected" } });
    } else {
      await route.fulfill({ status: 404, json: { detail: "not found" } });
    }
  });
}

async function signIn(page) {
  await page.goto("/");
  await page.getByLabel("Local API access token").fill("local-test-token");
  await page.getByRole("button", { name: "Connect workspace" }).click();
  await expect(page.getByRole("heading", { name: "Find your next good fit." })).toBeVisible();
}

test("onboarding connects to the job inbox", async ({ page }) => {
  await installApiMocks(page);
  await signIn(page);
  await expect(page.getByText("Build a customer churn prediction baseline")).toBeVisible();
});

test("Upwork approval requests a proposal preview and releases a reply for manual handoff", async ({ page }) => {
  await installApiMocks(page);
  const listing = { ...job, fit_score: null, data_provenance: "upwork_live", upwork_url: "https://www.upwork.com/jobs/example" };
  const liveProposal = { ...proposal, marketplace: "upwork" };
  const reply = { id: "upwork-reply", job_id: "", marketplace: "upwork", status: "awaiting_review", intent: "question",
    incoming_message: "Could you clarify the timeline?", draft: "Thanks. I will review the details and follow up." };
  let messageStatus = "";
  let approvals = 0;
  await page.route("http://localhost:8000/api/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === "/api/jobs") await route.fulfill({ json: [listing] });
    else if (path === `/api/jobs/${job.job_id}`) await route.fulfill({ json: listing });
    else if (path === "/api/portfolio") await route.fulfill({ json: {
      provenance: "local_owner_portfolio", profiles: [], evidence: proposal.analysis.evidence,
    } });
    else if (path.endsWith("/analyze")) {
      expect(request.postDataJSON()).toEqual({ evidence_id: "evidence-001", amount: 250, unit: "fixed" });
      await route.fulfill({ json: liveProposal });
    } else if (path === `/api/proposals/${proposal.id}/approve`) {
      approvals += 1;
      await route.fulfill({ json: { id: proposal.id, status: "preview_ready",
        external_submission: "Upwork returned a preview. No proposal was submitted.",
        upwork_preview: { ready: true, connects_cost: 8, connects_balance: 20, screening_questions: [] } } });
    } else if (path === "/api/messages/draft") {
      messageStatus = "awaiting_review";
      await route.fulfill({ json: reply });
    } else if (path === `/api/messages/${reply.id}/approve`) {
      messageStatus = "ready_to_copy";
      await route.fulfill({ json: { ...reply, status: messageStatus, external_send: "Copy for final review." } });
    } else if (path === "/api/messages") await route.fulfill({ json: messageStatus ? [{ ...reply, status: messageStatus }] : [] });
    else await route.fallback();
  });

  await signIn(page);
  await page.getByRole("button", { name: "View Upwork listing" }).click();
  await page.getByLabel("Portfolio evidence").selectOption("evidence-001");
  await page.getByLabel("Bid in USD").fill("250");
  await page.getByRole("button", { name: "Prepare proposal draft" }).click();
  await expect(page.getByRole("heading", { name: "Proposal studio" })).toBeVisible();
  expect(approvals).toBe(0);
  await page.getByRole("button", { name: "Approve and request Upwork preview" }).click();
  await expect(page.getByRole("heading", { name: "Upwork preview received" })).toBeVisible();
  await expect(page.getByText("Connects balance: 20")).toBeVisible();
  expect(approvals).toBe(1);

  await page.getByRole("button", { name: "Close" }).click();
  await page.getByRole("button", { name: "Messages" }).click();
  await page.getByLabel("Received message").fill(reply.incoming_message);
  await page.getByRole("button", { name: "Draft reply" }).click();
  await expect(page.getByRole("button", { name: "Copy approved reply" })).toHaveCount(0);
  await page.getByRole("button", { name: "Approve reply" }).click();
  await expect(page.getByRole("button", { name: "Copy approved reply" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Open Upwork Messages" })).toHaveAttribute("href", /upwork\.com/);
});

test("proposal approval is confirmed in the review drawer", async ({ page }) => {
  await installApiMocks(page);
  await signIn(page);
  await page.getByRole("button", { name: "Review opportunity" }).click();
  await expect(page.getByText("Evidence behind this match")).toBeVisible();
  await page.getByRole("button", { name: "Approve draft" }).click();
  await expect(page.getByText(/Approved for your records/)).toBeVisible();
});

test("proposal rejection records a reason", async ({ page }) => {
  await installApiMocks(page);
  await signIn(page);
  await page.getByRole("button", { name: "Review opportunity" }).click();
  page.on("dialog", async (dialog) => dialog.accept("Scope is not suitable."));
  await page.getByRole("button", { name: "Reject" }).click();
  await expect(page.getByText("Proposal rejected. Reason recorded.")).toBeVisible();
});

test("edited proposal is saved for evidence re-check", async ({ page }) => {
  await installApiMocks(page);
  await signIn(page);
  await page.getByRole("button", { name: "Review opportunity" }).click();
  const editor = page.getByLabel("Proposal draft");
  await editor.fill("My portfolio includes Customer churn classification coursework.");
  await page.getByRole("button", { name: "Save edits" }).click();
  await expect(page.getByText("Draft saved and all claims re-verified.")).toBeVisible();
});

test("API failure is visible on the sign-in screen", async ({ page }) => {
  await installApiMocks(page, true);
  await page.goto("/");
  await page.getByLabel("Local API access token").fill("bad-token");
  await page.getByRole("button", { name: "Connect workspace" }).click();
  await expect(page.getByText(/API unavailable/)).toBeVisible();
});

test("message replies are drafted and held for approval", async ({ page }) => {
  await installApiMocks(page);
  await signIn(page);
  await page.getByRole("button", { name: "Messages", exact: true }).click();
  await page.getByLabel("Related job").selectOption("sample-job-001");
  await page.getByLabel("Received message").fill("Can we schedule an interview?");
  await page.getByRole("button", { name: "Draft reply" }).click();
  await expect(page.getByText(/Reply drafted for your review/)).toBeVisible();
  await expect(page.getByText("Thanks for reaching out. I can discuss the project.")).toBeVisible();
  await page.getByRole("button", { name: "Approve reply" }).click();
  await expect(page.getByText(/Reply approved/)).toBeVisible();
});

test("negotiation reply shows its floor-based counter recommendation", async ({ page }) => {
  await installApiMocks(page);
  await signIn(page);
  await page.getByRole("button", { name: "Messages", exact: true }).click();
  await page.getByLabel("Related job").selectOption("sample-job-001");
  await page.getByLabel("Received message").fill("I can offer $150 for this project.");
  await page.getByRole("button", { name: "Draft reply" }).click();
  await expect(page.getByText(/Negotiation coach \(counter\)/)).toBeVisible();
  await expect(page.getByText(/My minimum for this scope is \$200/)).toBeVisible();
});
