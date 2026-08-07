import type { NextRequest } from "next/server";

export const dynamic = "force-dynamic";

/**
 * Proxies SSE stream from FastAPI backend without buffering.
 * @generated AI Assistant - 2026-08-07 15:40:00
 */
export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ sessionId: string }> }
) {
  const { sessionId } = await params;
  const backendUrl = process.env.BACKEND_URL ?? "http://localhost:8000";

  const response = await fetch(`${backendUrl}/api/stream/${sessionId}`, {
    headers: { Accept: "text/event-stream" },
  });

  if (!response.ok || !response.body) {
    return new Response("Backend stream unavailable", { status: 502 });
  }

  return new Response(response.body, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}
