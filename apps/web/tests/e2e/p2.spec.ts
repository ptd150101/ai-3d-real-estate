import { expect, test } from "@playwright/test";

test("P2 payment return surface renders publicly", async ({ page }) => {
  await page.goto("/payments/return");
  await expect(
    page.getByRole("heading", { name: /Đang xác minh giao dịch/ }),
  ).toBeVisible();
});

test("buyer can view valuation and recommendations after login", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill("buyer@nestora.vn");
  await page
    .getByLabel("Mật khẩu")
    .fill(process.env.E2E_BUYER_PASSWORD || "ci-e2e-buyer-password");

  await Promise.all([
    page.waitForURL(/\/$/),
    page.getByRole("button", { name: /Đăng nhập/ }).click(),
  ]);

  await page.goto("/account/valuations");
  await expect(page).toHaveURL(/\/account\/valuations/);
  await expect(
    page.getByRole("heading", { name: /Ước tính giá/ }),
  ).toBeVisible();

  await page.goto("/account/recommendations");
  await expect(page).toHaveURL(/\/account\/recommendations/);
  await expect(
    page.getByRole("heading", { name: /Bất động sản dành cho bạn/ }),
  ).toBeVisible();
});
