import { useState } from "react";
import { useVoiceInput } from "agents/voice/react";

export type VoiceUiState =
  | "idle"
  | "listening"
  | "thinking"
  | "speaking"
  | "interrupted"
  | "error";

export function VoiceControl() {
  const [state, setState] = useState<VoiceUiState>("idle");
  const voice = useVoiceInput({ agent: "BRVoiceIngressAgent" });

  return (
    <main aria-label="BR no GTA voice control">
      <p>Estado: {state}</p>
      <p aria-live="polite">{voice.transcript ?? ""}</p>
      <button onClick={() => { setState("listening"); void voice.start(); }}>Ouvir</button>
      <button onClick={() => { voice.stop(); setState("interrupted"); }}>Interromper áudio</button>
      <button onClick={() => { voice.stop(); setState("idle"); }}>Parar</button>
      <button onClick={() => setState("idle")}>Usar texto</button>
    </main>
  );
}
