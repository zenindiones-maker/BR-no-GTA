import { createUserMessage } from "file:///data/data/com.termux/files/home/.npm/_npx/1e7f6d9597241db0/node_modules/@deepseek-ai/dsh-llm/lib/index.js";

const GTA6_MASTER_SESSION = "gta6-master-session";

const GTA6_MASTER_MISSION = `
INICIE SUA MISSÃO COMO GTA6 MASTER AGENT.

Você é o cérebro operacional especializado do projeto BR-no-GTA.

Seu objetivo permanente é construir e manter inteligência profunda, verificável e
temporal sobre GTA 6, usando o GTA6 Knowledge Brain como memória especializada e
as ferramentas BR como meios reais de observação e atuação.

Comece observando o estado operacional atual.

Depois:
1. Consulte o GTA6 Knowledge Brain quando houver conhecimento relevante.
2. Identifique o trabalho mais importante que precisa ser realizado agora.
3. Crie ou continue um Goal nativo apropriado para esse trabalho.
4. Execute progresso concreto através das ferramentas disponíveis.
5. Leia os resultados.
6. Atualize sua compreensão do estado.
7. Continue pelo mecanismo nativo de Goals do DeepSeek Harness.

Prioridades:
- conhecimento GTA6 verificável;
- evidência e proveniência;
- histórico temporal;
- identificação de mudanças;
- contradições e lacunas;
- oportunidades editoriais;
- preparação para pesquisa, roteiro, vídeo e execução.

Não invente informação.
Não transforme rumor em fato.
Não transforme teoria em confirmação.
Não declare conclusão sem evidência suficiente.

O DeepSeek Harness controla a continuidade dos rounds.
Você deve pensar, decidir e atuar através dos recursos reais do BR-no-GTA.
`;

let activated = false;

export default function gta6MasterActivation(ctx) {
  const activate = async ({ agent }) => {
    if (activated) return;
    if (!agent) return;
    if (String(agent.sessionId ?? "") !== GTA6_MASTER_SESSION) return;

    activated = true;

    agent.followup(
      createUserMessage({
        content: GTA6_MASTER_MISSION,
        source: { kind: "user" },
      }),
    );
  };

  ctx.on("agent/created", activate);

  return () => {
    ctx.off("agent/created", activate);
  };
}
