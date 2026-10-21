export { default } from "next-auth/middleware";

// Every page under /app needs a signed-in user (the API routes check it themselves).
export const config = { matcher: ["/app/:path*"] };
