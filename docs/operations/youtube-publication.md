# Operação de publicação YouTube — BR-no-GTA

Este guia descreve a operação normal do YouTube sem criar autoridade paralela. O DeepSeek Harness continua sendo o único control plane. O Samsung A15/Termux é somente uma superfície de controle; render, VEdit, FFmpeg e upload do MP4 são executados no GitHub Actions.

## Princípio operacional

O fluxo é:

`Goal → Video → RenderJob → GitHub Actions → QA → Cloud Artifact → YouTube Publication → private upload → preview/readiness → aprovação explícita do usuário → PUBLICATION authorization → public → Analytics → Learning`

O upload privado e a publicação pública são operações diferentes. O upload privado **nunca** concede autorização para tornar o vídeo público.

## Controle A/B do RUN-001

Depois de atualizar a branch e ativar o venv, veja o estado canônico sem mutar nada:

```bash
PYTHONPATH="$PWD" .venv/bin/python scripts/run001_ab_control.py status
```

Avance **um único passo** do Goal A:

```bash
PYTHONPATH="$PWD" .venv/bin/python scripts/run001_ab_control.py advance --video A
```

Ou do Goal B:

```bash
PYTHONPATH="$PWD" .venv/bin/python scripts/run001_ab_control.py advance --video B
```

O comando é deliberadamente targeteado. Ele nunca usa o próximo item global quando A/B já são conhecidos. Se o RenderJob estiver `running`, repetir o mesmo comando posteriormente faz somente a reconciliação metadata-only do run cloud; o MP4 não é baixado no A15.

Job18 é um checkpoint congelado e nunca deve ser claimado, recuperado, redispatchado ou reutilizado. Job19 é o checkpoint histórico do canário.

## Publication específica

A operação de publicação não usa `next pending` para A/B. Use sempre o `publication_id` exato.

### 1. Upload privado

```bash
PYTHONPATH="$PWD" .venv/bin/python scripts/youtube_publication_control.py private-upload --publication-id <ID>
```

Isso executa Harness Routing para `youtube.upload-private`, persiste o claim no SQLite canônico e despacha `youtube-private-upload-worker.yml`. O runner materializa o Render Artifact, verifica hash, size, probe, áudio, vídeo, duração, QA e lineage e somente então chama o Google YouTube Publisher com `privacyStatus=private`.

### 2. Reconciliar upload privado

```bash
PYTHONPATH="$PWD" .venv/bin/python scripts/youtube_publication_control.py private-reconcile --publication-id <ID>
```

Se o run ainda estiver ativo, a Publication continua em progresso. Quando o artifact de resultado comprovar sucesso, o control plane persiste `youtube_video_id`, `youtube_url` e `status=uploaded` no mesmo SQLite canônico.

### 3. Preview antes de tornar público

```bash
PYTHONPATH="$PWD" .venv/bin/python scripts/youtube_publication_control.py preview --publication-id <ID>
```

Esse boundary é **somente leitura**. Ele verifica Publication, Goal, Video, RenderJob, artifact locator, QA, private upload e identidade do vídeo no YouTube. O resultado inclui `PUBLICATION_READY=true|false` e as razões. `PUBLICATION_READY=true` significa apenas prontidão técnica; não é aprovação.

### 4. “Pode postar”

A publicação pública exige aprovação explícita do usuário para a Publication exata. Pela CLI, há um interlock adicional:

```bash
PYTHONPATH="$PWD" .venv/bin/python scripts/youtube_publication_control.py pode-postar --publication-id <ID> --confirm PODE_POSTAR
```

Esse comando entra no boundary oficial `br_youtube_pode_postar(publication_id)`. O fluxo é:

`user approval → Harness Routing → youtube.publish-public → HarnessAuthorization(PUBLICATION) → youtube:publication:<ID> → Google publisher → Evidence → published`

O worker de upload privado não pode chamar esse gate e `PUBLICATION` não ocorre automaticamente após o upload.

### 5. Recuperar estado público incerto

Se o YouTube puder ter aceitado `make_public`, mas a resposta/persistência local ficar incerta, **não execute “pode postar” novamente**. Use:

```bash
PYTHONPATH="$PWD" .venv/bin/python scripts/youtube_publication_control.py public-reconcile --publication-id <ID>
```

Esse comando consulta a visibilidade remota sem side effect. Se o vídeo já estiver público, finaliza o estado local como `published`; se continuar private/unlisted, registra a tentativa como falha e uma nova aprovação explícita pode ser feita depois.

## Credenciais

O upload cloud usa GitHub Secrets:

- `YOUTUBE_OAUTH_TOKEN_JSON`
- `YOUTUBE_OAUTH_CLIENT_SECRET_JSON`

Nunca coloque os valores em comandos, RenderJobs, artifacts, commits, documentação ou mensagens de log.

## Analytics e Learning

Depois de `published`, `youtube.analytics.read` deve resolver o `youtube_video_id` a partir da Publication persistida. O contrato normalizado de janela é:

```json
{"metric_window":{"start_date":"YYYY-MM-DD","end_date":"YYYY-MM-DD"}}
```

O resultado pode alimentar `knowledge.learn.youtube-analytics`, que registra evidência/memória para decisões futuras do Harness. Learning não publica e não ganha autoridade editorial.

## Regras de segurança operacional

- Nunca publique por posição na fila quando o `publication_id` é conhecido.
- Nunca execute `make_public` diretamente no publisher.
- Nunca baixe o MP4 de 25 min no A15 para depois reenviá-lo.
- Nunca trate preview/readiness como aprovação.
- Nunca repita uma transição pública com estado remoto incerto; reconcilie primeiro.
- Nunca toque no Job18.
- Vídeo A e Vídeo B mantêm Goal, Video, RenderJob, artifact, Publication e `youtube_video_id` independentes.

## Quando o sistema pode ser chamado de GREEN

`SYSTEM_SYNERGY=GREEN` só pode ser gravado em checkpoint final depois de evidência real de CI, renders A/B, QA A/B, artifacts independentes, private uploads, aprovação/publicação específica de A e B, Analytics, Learning e retorno de conhecimento ao Harness. Até lá, este documento é o guia operacional do mecanismo, não uma declaração de conclusão do RUN-001.
