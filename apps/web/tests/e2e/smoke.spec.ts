
import { expect, test } from "@playwright/test";
import { firstDemoProperty } from "./helpers";

test("home and search flow", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /Tìm ngôi nhà/ })).toBeVisible();
  await page.getByLabel("Yêu cầu tìm kiếm").fill("Nhà Cầu Giấy dưới 13 tỷ có 3D");
  await page.getByRole("button", { name: "Tìm bất động sản" }).click();
  await expect(page).toHaveURL(/properties/);
  await expect(page.getByText(/kết quả/)).toBeVisible();
});

test("property detail exposes chatbot", async ({ page }) => {
  const property = await firstDemoProperty(page.request);
  await page.goto(`/properties/${property.slug}`);
  await expect(page.getByRole("heading", { name: property.title }).first()).toBeVisible();
  await expect(page.getByLabel("Trợ lý bất động sản AI").first()).toBeVisible();
});
