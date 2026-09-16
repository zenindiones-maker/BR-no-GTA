# BR-no-GTA — próximas metas de produção

## Regra central

DeepSeek Harness continua sendo a única autoridade/control plane.
Telegram é ingress, revisão e aprovação humana. Workers executam operações determinísticas.
Nenhum vídeo pode ficar público sem a operação exata `br_youtube_pode_postar(publication_id)`.

## M1 — Pesquisa GTA 6 profissional

Status: runtime principal comprovado.

- Fresh research obrigatório para fatos atuais.
- Prioridade: Rockstar oficial -> fontes secundárias corroboradas -> Knowledge Brain -> comunidade como sinal.
- Fail-closed quando não houver evidência atual suficiente.
- Evidência de pesquisa precisa permanecer ligada ao tema/roteiro/publicação.

Definition of Done:
- fontes + checked_at + claims/proveniência;
- separação factual entre oficial, secundário, rumor e hipótese;
- pacote de evidências consumível pelo roteirista.

## M2 — Roteirista profissional PT-BR

- Roteiro final só pode ser gerado com evidence pack válido.
- Proibir fallback genérico para produção final.
- Estrutura: hook, contexto, desenvolvimento, comparação/evidência, conclusão e CTA.
- Duração-alvo ~25 min com volume real de narração compatível.
- Fact-check pós-roteiro contra o evidence pack.
- QA de repetição, ritmo, clareza e afirmações sem fonte.

Definition of Done:
- roteiro final PT-BR;
- fact-check PASS;
- nenhuma afirmação factual atual sem provenance;
- artefato de roteiro ligado ao Goal/ContentItem/Publication.

## M3 — Voz oficial do canal

- Criar capability de narração PT-BR.
- Selecionar uma voz oficial fixa do BR no GTA.
- Cloud-only: A15 nunca sintetiza áudio pesado.
- Normalização de loudness, duração e QA de áudio.
- Persistir voice profile/version como identidade do canal.

Definition of Done:
- WAV/PCM ou equivalente de produção;
- voice profile versionado;
- loudness/stream/duration QA PASS;
- mesma identidade vocal para novos vídeos.

## M4 — Identidade audiovisual permanente

- Intro oficial + marca d'água via Telegram.
- Persistir identidade/proveniência dos arquivos.
- Materializar no runner cloud.
- Verificar SHA-256, MIME, tamanho e ffprobe.
- Aplicar com FFmpeg/VEdit.
- `BR_NO_GTA_VIDEO_BRANDING_V1` fail-closed.

Definition of Done:
- intro aplicada;
- watermark aplicada;
- MP4 final com vídeo+áudio;
- branding evidence + QA PASS.

## M5 — Canal/sala Telegram de revisão humana

Fluxo obrigatório:

`Render QA PASS -> upload privado YouTube -> proxy Telegram -> revisão humana -> decisão`

O worker de upload privado gera uma cópia de revisão compatível com o Bot API, envia para o destino `TELEGRAM_REVIEW_CHAT_ID` e grava `telegram_review.status=DELIVERED` no resultado do upload.

A publicação pública fica bloqueada na readiness se essa evidência não existir. A entrega de review NÃO concede autoridade de publicação.

No review post devem aparecer:
- publication_id e video_id;
- proxy reproduzível no Telegram;
- link para o master privado no YouTube;
- instrução exata para aprovação pública: `/pode_postar <publication_id>`;
- instrução para solicitar edição.

Definition of Done:
- destino de review pareado e sincronizado ao GitHub variable;
- proxy entregue;
- duração do proxy compatível com master;
- review evidence persistida no private-upload result;
- `PUBLICATION_READY=False` se review não tiver sido entregue.

## M6 — Loop profissional de revisão/edição

Próxima implementação após M5 runtime proof.

Estados previstos:
- `PENDING_REVIEW`
- `CHANGES_REQUESTED`
- `REVISION_RENDERING`
- `PENDING_REVIEW` (nova revisão)
- `APPROVED_FOR_PUBLIC_GATE`

Regras:
- pedido de edição nunca muta o MP4 anterior;
- gera nova revisão/RenderJob com lineage;
- manter histórico de versões e feedback;
- só a revisão atual pode seguir para publicação;
- feedback de edição enviado no Telegram deve ser persistido e consumido pelo Harness.

## M7 — Prova de vídeo real do canal

Executar um vídeo de teste completo com:
- pesquisa atual;
- roteiro final PT-BR;
- voz oficial;
- intro;
- marca d'água;
- render real;
- review Telegram;
- edição/revisão se necessária;
- upload privado;
- aprovação explícita;
- somente então publicação pública.
