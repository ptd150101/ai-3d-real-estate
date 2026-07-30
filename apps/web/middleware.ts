import { NextRequest, NextResponse } from "next/server";
export function middleware(request:NextRequest){const token=request.cookies.get("nestora_token")?.value;if(!token){const url=new URL('/login',request.url);url.searchParams.set('next',request.nextUrl.pathname);return NextResponse.redirect(url)}return NextResponse.next()}
export const config={matcher:['/admin/:path*','/favorites/:path*']};
