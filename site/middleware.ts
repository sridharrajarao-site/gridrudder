import { NextResponse } from "next/server";
export function middleware() {
  const response = NextResponse.next();
  response.headers.set("Cache-Control", "private, no-store");
  response.headers.set("X-Robots-Tag", "noindex, nofollow");
  return response;
}
export const config = { matcher: ["/ops", "/api/ops/:path*"] };
