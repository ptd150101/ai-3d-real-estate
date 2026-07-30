import { NextResponse } from "next/server";
export async function POST(request:Request){const response=NextResponse.redirect(new URL("/",request.url),303);response.cookies.delete("nestora_token");return response;}
