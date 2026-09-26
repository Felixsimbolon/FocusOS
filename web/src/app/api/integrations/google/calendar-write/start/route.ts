import { NextRequest } from "next/server";
import { startGoogleFlow } from "../../start-google-flow";

export async function GET(request: NextRequest) {
  return startGoogleFlow(request, "calendar_write");
}
