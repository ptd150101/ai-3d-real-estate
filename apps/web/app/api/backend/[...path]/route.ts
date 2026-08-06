
import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";

import { API_URL } from "@/lib/api";

function encodePathSegment(segment: string): string {
  try {
    return encodeURIComponent(decodeURIComponent(segment));
  } catch {
    return encodeURIComponent(segment);
  }
}

async function proxy(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const { path } = await params;
  const cookieStore = await cookies();
  const token = cookieStore.get("nestora_token")?.value;
  const organizationId = cookieStore.get("nestora_org")?.value;
  const target = new URL(`${API_URL}/${path.map(encodePathSegment).join("/")}`);
  request.nextUrl.searchParams.forEach((value, key) => {
    target.searchParams.append(key, value);
  });

  const headers = new Headers();
  const contentType = request.headers.get("content-type");
  if (contentType) headers.set("content-type", contentType);
  headers.set("accept", request.headers.get("accept") || "application/json");
  if (token) headers.set("authorization", `Bearer ${token}`);
  if (organizationId) headers.set("x-organization-id", organizationId);

  const hasBody = !["GET", "HEAD"].includes(request.method);
  const body = hasBody ? await request.arrayBuffer() : undefined;
  const response = await fetch(target, {
    method: request.method,
    headers,
    body,
    cache: "no-store",
    redirect: "manual",
  });
  const responseHeaders = new Headers();
  const responseType = response.headers.get("content-type");
  if (responseType) responseHeaders.set("content-type", responseType);
  return new NextResponse(response.body, {
    status: response.status,
    headers: responseHeaders,
  });
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
