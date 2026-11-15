import { expect, test } from "@playwright/test";

test("local inbox loads live Upwork listings and opens a listing detail", async ({ page }) => {
  const apiToken = process.env.GIGBID_UPWORK_TEST_TOKEN;
  if (!apiToken) throw new Error("Use npm run test:upwork to run the live inbox test.");

  await page.goto("/");
  await page.getByLabel("Local API access token").fill(apiToken);
  const search = page.waitForResponse((response) =>
    response.request().method() === "GET" && new URL(response.url()).pathname === "/api/jobs"
  );
  await page.getByRole("button", { name: "Connect workspace" }).click();
  const searchResponse = await search;
  expect(searchResponse.ok(), `Upwork search returned HTTP ${searchResponse.status()}`).toBe(true);

  const listing = page.getByRole("button", { name: "View Upwork listing" }).first();
  await expect(listing).toBeVisible();
  const detail = page.waitForResponse((response) =>
    response.request().method() === "GET" && new URL(response.url()).pathname.startsWith("/api/jobs/")
  );
  await listing.click();
  const detailResponse = await detail;
  expect(detailResponse.ok(), `Upwork detail returned HTTP ${detailResponse.status()}`).toBe(true);
  await expect(page.getByRole("heading", { name: "Upwork listing", exact: true })).toBeVisible();
});
