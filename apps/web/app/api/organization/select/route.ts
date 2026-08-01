import { NextRequest, NextResponse } from "next/server";

export async function POST(request: NextRequest) {
  const payload = (await request.json()) as { organization_id?: string };
  if (!payload.organization_id) return NextResponse.json({ detail: "organization_id required" }, { status: 422 });
  const response = NextResponse.json({ selected: payload.organization_id });
  response.cookies.set("nestora_org", payload.organization_id, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    maxAge: 60 * 60 * 24 * 365,
    path: "/",
  });
  return response;
}
