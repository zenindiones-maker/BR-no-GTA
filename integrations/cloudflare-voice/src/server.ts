import { Agent, routeAgentRequest } from "agents";
import { withVoiceInput } from "agents/voice";

const VoiceInputAgent = withVoiceInput(Agent);
const HARNESS_TOOL = "harness.voice.turn" as const;

export interface HarnessTurnClient {
  invoke(input: {
    conversation_id: string;
    transcript: string;
    intent_hint?: string;
    correlation_id: string;
  }): Promise<{
    canonical_text: string;
    status: string;
    execution_id?: string;
    spoken_summary?: string;
    requires_confirmation: boolean;
  }>;
}

export class BRVoiceIngressAgent extends VoiceInputAgent {
  harness!: HarnessTurnClient;

  async onTranscript(
    transcript: string,
    context: { connectionId?: string } = {}
  ) {
    const correlationId = context.connectionId ?? crypto.randomUUID();
    return this.harness.invoke({
      conversation_id: correlationId,
      transcript,
      intent_hint: undefined,
      correlation_id: correlationId,
    });
  }

  readonly authoritySurface = HARNESS_TOOL;
}

export default {
  fetch(request: Request, env: unknown) {
    return routeAgentRequest(request, env as never);
  },
};
