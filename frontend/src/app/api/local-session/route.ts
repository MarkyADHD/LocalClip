import { auth } from "@/lib/auth";

// LocalClip has one built-in account instead of a login screen. Its password is generated per
// install by LocalClip.ps1 and never reaches the browser; the app only listens on 127.0.0.1.
const EMAIL = "me@localclip.local";

export async function POST(request: Request) {
  const password = process.env.LOCALCLIP_PASSWORD;
  if (!password) {
    return Response.json({ error: "Local sign-in is not configured" }, { status: 404 });
  }
  const signIn = await auth.api.signInEmail({
    body: { email: EMAIL, password },
    headers: request.headers,
    asResponse: true,
  });
  if (signIn.ok) return signIn;
  return auth.api.signUpEmail({
    body: { name: "LocalClip", email: EMAIL, password },
    headers: request.headers,
    asResponse: true,
  });
}
