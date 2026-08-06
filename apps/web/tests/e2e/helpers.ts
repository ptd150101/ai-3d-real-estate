
import type { APIRequestContext } from "@playwright/test";

export type PropertySummary = {
  slug: string;
  title: string;
  property_type: string;
  has_3d: boolean;
};

type PropertyList = { items: PropertySummary[] };

export async function firstDemoProperty(
  request: APIRequestContext,
  query = "has_3d=true&page_size=1",
): Promise<PropertySummary> {
  const response = await request.get(`/api/backend/properties?${query}`);
  if (!response.ok()) throw new Error(`Property lookup failed: ${response.status()}`);
  const payload = (await response.json()) as PropertyList;
  const property = payload.items[0];
  if (!property) throw new Error("Demo property catalog is empty");
  return property;
}
