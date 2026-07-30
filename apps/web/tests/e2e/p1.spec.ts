import { test, expect } from "@playwright/test";

test("P1 buyer account surfaces", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill("buyer@nestora.vn");
  await page.getByLabel("Mật khẩu").fill("ci-e2e-buyer-password");
  await page.getByRole("button", { name: "Đăng nhập" }).click();
  await expect(page).toHaveURL(/\/$/);
  await page.goto("/account/notifications");
  await expect(page.getByRole("heading", { name: "Thông báo" })).toBeVisible();
  await page.goto("/account/saved-searches");
  await expect(page.getByRole("heading", { name: "Tìm kiếm đã lưu" })).toBeVisible();
  await page.goto("/messages");
  await expect(page.getByRole("heading", { name: "Tin nhắn trực tiếp" })).toBeVisible();
});

test("P1 public experience remains progressively enhanced", async ({ page }) => {
  await page.goto("/properties/nha-pho-hien-dai-cau-giay");
  await expect(page.getByRole("heading", { name: /Nhà phố hiện đại/ })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Di chuyển giữa các phòng" })).toBeVisible();
  await expect(page.getByRole("button", { name: /brochure/i })).toBeVisible();
});
