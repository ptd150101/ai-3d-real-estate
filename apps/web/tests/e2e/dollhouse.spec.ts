
import { expect, test } from "@playwright/test";
import { firstDemoProperty } from "./helpers";

test("dollhouse loads GLB and exposes its core controls", async ({ page }) => {
  const property = await firstDemoProperty(
    page.request,
    "has_3d=true&property_type=villa&page_size=1",
  );
  await page.goto(`/properties/${property.slug}`);
  const [assetResponse] = await Promise.all([
    page.waitForResponse(
      (response) => response.url().endsWith(".glb") && response.status() === 200,
      { timeout: 20_000 },
    ),
    page.getByRole("button", { name: "Bắt đầu xem 3D" }).click(),
  ]);
  expect(assetResponse.headers()["content-type"]).toContain("model/gltf-binary");
  await expect(page.locator(".viewer-canvas canvas")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText("● Live 3D")).toBeVisible();
  await expect(page.getByText("Không thể tải mô hình 3D")).toHaveCount(0);
  await page.getByRole("button", { name: "Xoay tự do" }).click();
  await expect(page.getByText("Orbit", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Dollhouse" }).click();
  await expect(page.getByText("Dollhouse", { exact: true }).last()).toBeVisible();
  await page.getByRole("button", { name: "Ẩn nội thất" }).click();
  await expect(page.getByRole("button", { name: "Hiện nội thất" })).toBeVisible();
  await page.getByRole("button", { name: "Hiện mái" }).click();
  await expect(page.getByRole("button", { name: "Ẩn mái" })).toBeVisible();
  const floorToggle = page.getByRole("button", { name: /^(Ghép tầng|Tách tầng)$/ });
  await expect(floorToggle).toBeVisible();
  const before = await floorToggle.textContent();
  await floorToggle.click();
  await expect(floorToggle).not.toHaveText(before || "");
  await page.getByRole("button", { name: "Reset camera" }).click();
  const hotspot = page.getByRole("button", { name: /Mở thông tin/ }).first();
  await expect(hotspot).toBeVisible({ timeout: 15_000 });
  await hotspot.click();
  await expect(page.locator(".viewer-hotspot-card")).toBeVisible();
});
