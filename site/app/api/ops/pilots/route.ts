import { env } from "cloudflare:workers";
import { getChatGPTUser } from "../../../chatgpt-auth";
import { handlePilotOperations } from "../../../ops/pilot-policy.mjs";
export const dynamic = "force-dynamic";
async function handle(request: Request) {
  return handlePilotOperations(request, await getChatGPTUser(), (env as unknown as Record<string, unknown>).PILOT_OPERATOR_USER_ID, env.DB);
}
export const GET = handle;
export const POST = handle;
