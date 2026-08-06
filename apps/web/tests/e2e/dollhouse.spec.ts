import { expect, test } from "@playwright/test";

import { firstDemoProperty } from "./helpers";

test("dollhouse loads GLB and exposes its core controls", async ({ page }) => {
  test.setTimeout(60_000);

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

  const toolbar = page.locator(".viewer-toolbar");

  async function clickToolbarButton(name: string | RegExp) {
    const button = toolbar.getByRole("button", { name });
    await button.scrollIntoViewIfNeeded();
    await button.click({ force: true });
    return button;
  }

  await clickToolbarButton("Xoay tự do");
  await expect(page.getByText("Orbit", { exact: true })).toBeVisible();

  await clickToolbarButton("Dollhouse");
  await expect(page.getByText("Dollhouse", { exact: true }).last()).toBeVisible();

  await clickToolbarButton("Ẩn nội thất");
  await expect(toolbar.getByRole("button", { name: "Hiện nội thất" })).toBeVisible();

  await clickToolbarButton("Hiện mái");
  await expect(toolbar.getByRole("button", { name: "Ẩn mái" })).toBeVisible();

  const floorToggle = toolbar.getByRole("button", {
    name: /^(Ghép tầng|Tách tầng)$/,
  });
  await expect(floorToggle).toBeVisible();
  const before = await floorToggle.textContent();
  await floorToggle.scrollIntoViewIfNeeded();
  await floorToggle.click({ force: true });
  await expect(floorToggle).not.toHaveText(before || "");

  await clickToolbarButton("Reset camera");

  const hotspot = page.getByRole("button", { name: /Mở thông tin/ }).first();
  await expect(hotspot).toBeVisible({ timeout: 15_000 });
  await hotspot.click({ force: true });
  await expect(page.locator(".viewer-hotspot-card")).toBeVisible();
});
