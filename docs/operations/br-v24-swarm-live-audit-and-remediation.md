# BR-no-GTA V24 — Auditoria integral do swarm e evidências de execução

**Estado:** desenvolvimento experimental não promovido. **Repositório único:** `zenindiones-maker/BR-no-GTA`. **Branch:** `work/br-slm-agent-reconstruction-v24`.

**Owner directive:** ligar o swarm **existente**, usando REA próprio do BR e provas operacionais reais; não criar outro swarm, autoridade, roteador ou agentes. **A15 = apenas SSH, controle e logs.** Instalação, testes, processamento e inferência sempre remotos. Não importar projetos de terceiros como autoridade e não incorporar HAZEWAVE.

## 1. Censo exaustivo do Registry — PASS

Run `37876518961`: https://github.com/zenindiones-maker/BR-no-GTA/actions/runs/37876518961

- **167** capacidades, decompostas em **19 AGENT + 53 CAPABILITY + 36 EXECUTOR + 2 PRESENTATION + 18 PROVIDER + 28 SKILL + 11 TOOL**.
- **44** `agent_id` distintos (não são 44 processos vivos).
- **147** capacidades com executor declarado; **20** bloqueadas/inativas no registro.
- **24** Addy skills (uma identidade `addy-agent-skills`), **11** skills locais em `.dsh/skills`.
- **51** capacidades YouTube, **17** identidades `agent_id` YouTube, **9** TUBEGENT especialistas.
- Outras **19** funções `youtube-intelligence` não têm necessariamente `agent_id`; são papéis sob demanda, não agentes autônomos.
- O `tubegent` raiz legado está inativo; os nove `tubegent-*` especialistas são distintos e válidos.
- Os sete agentes AgentTube derivados do upstream têm implementação adaptada à arquitetura BR, sem permitir o executor/controlador upstream Lumen.

O inventário completo (JSON por `capability_id`, `agent_id`, `skill_id`, action, binding e readiness) é um artifact do run; nunca interpretar a disponibilidade declarada como prova de execução.

## 2. Contratos e execuções atuais

### Registry ⇄ Hermes ⇄ Agent Office

Run `37875994691` — https://github.com/zenindiones-maker/BR-no-GTA/actions/runs/37875994691

- **69** task-owner profiles Agent Office, **147** projeções de executor Hermes.
- **0** divergências nos contratos de metadata inspecionados, **13** testes aprovados.
- Não prova processo vivo Hermes ou Agent Office em toda capacidade.

### Execução real do Harness: dois agentes distintos — PASS

Run `37876380790` — https://github.com/zenindiones-maker/BR-no-GTA/actions/runs/37876380790

- `deterministic-analysis`: perfil de **1.457** arquivos versionados.
- `system-improvement-agent`: consumiu resultado do primeiro, gerou proposta, executou novamente e registrou **dois** casos e competência observada.
- Recibos, autorizações, TaskResult e aprendizado real; nenhuma promoção/revisão dispensada.
- **Nenhum SLM participou** desta prova.

### Nove TUBEGENT — executor/adaptação do BR PASS, sem LLM

Run `37876732849` — https://github.com/zenindiones-maker/BR-no-GTA/actions/runs/37876732849

Cada um dos nove especialistas `youtube.department.*` executou o adaptador real da BR com autorização Harness, canonical result, receipt `COMPLETED` e Learning Plane episode lido de volta. São **nove identidades distintas**, nenhum payload YouTube enviado e nenhuma inferência semântica realizada. Não marcar como validado por SLM.

### 24 Addy skills — materialização/carga 24/24 PASS, sem LLM

Run `37876900262` — https://github.com/zenindiones-maker/BR-no-GTA/actions/runs/37876900262

- Fonte Addy recuperada do SHA original `be4e44a9fbc5e8df0beaefadbb28bd22ee61cc39`, confinada ao runner remoto.
- Registry, materialização e `resolve_pinned_addy_skill` executado para os 24 skills; nenhum skill foi criado.
- **24 prompts/instruções disponíveis não equivalem a 24 gerações por modelo**; funcionalidade semântica, adequação de SLM e tool calling permanecem sem aprovação.

### Executor bindings — 146 símbolos e um vínculo de módulo

Run `37877257058` — https://github.com/zenindiones-maker/BR-no-GTA/actions/runs/37877257058

- 147 executores declarados submetidos a inspeção estática: **146** apontam para funções/classes definidas em código Python; **1** `SOURCE_MODULE_ONLY_NOT_CALLABLE`.
- O item singular é `speech.transcription.whisperx`, registrado como `app.services.speech.whisperx_provider`. O arquivo **existe**; a classe é `WhisperXProvider`, porém o binding aponta para o **módulo**, não diretamente para uma função/classe invocável.
- **Não alterar binding nem dar PASS de WhisperX antes de reconciliar o loader de provider, o contrato SpeechProvider, QA e runtime realmente instalado.** Não instalar WhisperX sem avaliação de custo, memória, modelos e áudio permitido.
- Exame AST não importa módulos, não carrega providers e **não prova os 146 executores operacionais**.

## 3. Agentes adicionais e etapas bloqueadas

- **AgentTube (7)**: seis adaptadores advisory/typed read-only podem ser exercitados; o sétimo `youtube.publishing` só pode seguir seu gate de aprovação humana. O upstream Lumen, credenciais e scheduler não são autoridade do BR.
- **YouTube intelligence (19 roles)**: executores determinísticos recebem evidências e candidates validados, mas não são automaticamente especialistas generativos treinados. Provas de qualidade precisam de tarefas externas verificáveis e holdouts.
- **YouTube platform/API**: leitura e publicação reais requerem OAuth oficial de escopo mínimo, broker e quotas; chamadas externas e publicação continuam desautorizadas nesta auditoria.
- **Hermes durable resume / Agent Office histórico**: existem CI antigos reprovados; reavaliar jobs atuais, exato SHA, causa raiz e preservação de checkpoints antes de reativar operações com side effects.
- **SLM V22**: benchmark ONNX em holdout de 16 tarefas in-domain só **10/16 = 62,5%**, contra gate de 85%. **Reprovado para promoção**. Ver run `37857856572`.
- **Ollama local Qwen3 4B:** há um provider BR pré-existente e uma prova histórica apenas para repositório público; a receita não é automaticamente válida para a V24 privada. Verificar franquia real e runtime antes de download pesado.
- **Custos:** GitHub Actions em repositório privado consome franquia de minutos do proprietário. Sem leitura autorizada da cota restante, **nenhuma hipótese de US$0 ilimitado** é válida. Não provisionar GPU/maior máquina nem habilitar pagamento.

## 4. Próximas medidas que contam como real

1. **Reavaliar execuções problemáticas dos agentes existentes**, incluindo Agent Office, Hermes e YouTube, com jobs observáveis e recibos; corrigir causas, não mascarar falhas.
2. **Conectar SLM não autoritativo** somente em ambiente remoto, após admissibilidade de recursos/custo e verificação de pesos e licença. Primeiro para uma única tarefa read-only; comparar saída com baseline original e casos inéditos.
3. **BFCL/tool-use adaptado ao BR:** argument schema, executor selection, exatidão, abstenção, retries, injection, output JSON, p95, memória, disponibilidade, custo e resposta em PT-BR; nenhum resultado de prompt único autoriza executar ferramentas.
4. **Somente quando a qualidade independente superar baselines**, considerar shadow route do Harness para capability existente; jamais editar o roster de Agent Office/Hermes ou criar agent IDs para compensar falta de qualidade.
5. **Side effects de produção** (voz clonada, Telegram, canal YouTube, segredo, pagamento, merge) mantêm suas autorizações e aprovação humana.
6. Reconciliar cada `agent_id` do artifact completo com `REAL_EXECUTION_PASS`, `BLOCKED`, `UNVERIFIED`, `PROVIDER_PENDING` ou `HUMAN_GATE` por HEAD. Auditoria de metadata nunca pode preencher `REAL_EXECUTION_PASS` sozinha.

## Fontes técnicas públicas consultadas

- GitHub Actions workflow e least-privilege: https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax
- GitHub Actions para repositórios privados, cotas e billing: https://docs.github.com/en/billing/concepts/product-billing/github-actions
- Benchmark de tool-use BFCL: https://proceedings.mlr.press/v267/patil25a.html
- WhisperX oficial: https://github.com/m-bain/whisperX
- AgentTube upstream (somente proveniência, não autoridade): https://github.com/darkzOGx/youtube-automation-agent

**Nota:** este ledger é uma fotografia de evidências verificadas e dos bloqueios. Atualizá-lo após novos recibos reais, sem substituir o Harness ou afirmar cobertura não demonstrada.

## 5. Atualização verificada 2026-10-09 — evidência pós-auditoria

### Seis agentes AgentTube adaptados ao próprio BR: PASS (sem SLM)

Run `37877764539`:
https://github.com/zenindiones-maker/BR-no-GTA/actions/runs/37877764539

Os **seis** agentes `content-strategy-agent`, `script-writer-agent`,
`thumbnail-designer-agent`, `seo-optimizer-agent`,
`production-management-agent` e `analytics-optimization-agent` foram
executados no runner remoto usando as implementações **existentes do BR**,
`TaskExecutionEnvelope/v1`, `TypedTaskRequirement/v1`, autorização real do
Harness e `execute_capability`. Prova `BR_V24_AGENTTUBE_NATIVE_EXECUTED=6`,
`BR_V24_AGENTTUBE_ORIGINAL_EXECUTION=PASS`; sem calls externas, modelo, upload,
geração de vídeo, SLM ou promoção. O sétimo agente `publishing-scheduling-agent`
continua **HUMAN_GATE**, não foi executado.

A falha inicial na V24 era no próprio canary: `product_contract_digest`
foi incorretamente construído com um SHA de commit de 40 caracteres. O contrato
exige SHA-256 hex de 64 caracteres. A entrada foi corrigida; **não** se mudou
o validador ou a autoridade do Harness.

**Total de identidades com execução comprovada no Harness pela V24: 17**:
2 de análise/melhoria + 9 TUBEGENT + 6 AgentTube. Este número não inclui
24 skills Addy como agentes distintos, 19 funções YouTube Intelligence
sem `agent_id`, ou agentes sem execução observada.

### Hermes durability: causa raiz corrigida, regressão PASS

Run `37878130719`:
https://github.com/zenindiones-maker/BR-no-GTA/actions/runs/37878130719

Histórico `37159581274`: `runner-b` falhou ao tentar abrir
`task-results/retrieve-primary-1.json`, que o exporter do checkpoint
ignorava (copiava apenas `capability-results`). A V24 agora exporta e
restaura `task-results/*.json` com nomes e hashes exatos no manifesto.
**4** regressões PASS: cópia/restauração, arquivo ausente, alteração e
arquivo extra. `FULL_TWO_RUNNER_END_TO_END=NOT_ATTEMPTED` após a correção;
não declarar recuperabilidade durável comprovada em dois runners até execução.

### Agent Office: HIGH dependencies review PENDING

Run histórico `37822742513`:
https://github.com/zenindiones-maker/BR-no-GTA/actions/runs/37822742513

Falha `UPSTREAM_AUDIT_ALLOWLIST_DRIFT_REVIEW_REQUIRED`, novos pacotes HIGH
`@modelcontextprotocol/sdk`, `@types/jest`, `braces`, `expect`,
`jest-message-util`, `micromatch`. **Não adicionar à allowlist**
automaticamente: exige auditoria independente e avaliação de caminho de
exploração/impacto, licenças e versões exatas. CI histórico não representa
o estado operacional do checkout V24 sem nova prova.

### Próximo gate SLM real

A documentação de Qwen3-0.6B declara licença Apache-2.0, modo não-thinking
e suporte a integração de ferramentas. Candidato de baixo recurso,
**ainda não baixado, testado ou admitido no BR V24**. O benchmark ONNX V22
permanece REJECTED. Sem confirmação da franquia gratuita remanescente do
repositório privado, não baixar modelos pesados nem agendar sessões longas.
Modelos não ganham autoridade para executar/clicar/publicar; o Harness mantém
validações por capability e requer holdout independente por tarefa.

Fontes:
- https://huggingface.co/Qwen/Qwen3-0.6B
- https://docs.github.com/en/billing/concepts/product-billing/github-actions
- https://docs.github.com/en/actions/concepts/workflows-and-actions/workflow-artifacts

## 6. Pesquisa externa + engenharia reversa V24 (09/10/2026)

### BR-native REA recuperado em checkout isolado — revisão V4 real

- Auditoria `37881030519` PASS: https://github.com/zenindiones-maker/BR-no-GTA/actions/runs/37881030519
- Auditoria e **14/14 testes reais** do avaliador experimental V4 `37881628576` PASS: https://github.com/zenindiones-maker/BR-no-GTA/actions/runs/37881628576
- Fonte V4 fixada: `ad00c215ecd33ee74703cfeb0d72694220b666f0`, mesma origem Git do BR.
- **21** fontes, scripts e testes REA presentes na V4 e ausentes na V24. Estoque histórico preservado em outra branch, não deletado do repositório. Não é prova de sua adequação a uma API V24.
- Somente o **avaliador de experimentos V4** foi carregado dinamicamente, com dados sintéticos e pytest isolado; 14 testes passaram, incluindo holdout, drift, adulteração, custos e proibição de promoção.
- `REA_V24_RUNTIME_INTEGRATED=NOT_PROVEN`, `REA_V4_EXPERIMENT_COMPONENT_REUSABLE_CANDIDATE=TRUE`, `REA_SOURCE_REINTRODUCED=FALSE`, `REVIEW_REQUIRED=TRUE`.
- A reconciliação e quaisquer portes precisam respeitar `AGENTS.md`, rastrear origem por SHA, diffs semânticos, versões e autorização Harness. Nunca importar a arquitetura/Harness de outro projeto.
- Documentação pública REA v6: https://github.com/morluto/rea — grafos estáticos e pseudocódigo **não** são equivalência comportamental de aplicativos.

### Hermes — transferência real entre GitHub-hosted runners agora PASS

Run `37881244213`: https://github.com/zenindiones-maker/BR-no-GTA/actions/runs/37881244213

- Runner A gerou `TaskResultEnvelope` pelo serviço original do BR, persistiu sob `task-results`, e exportou checkpoint usando `export_hermes_mission_checkpoint`.
- Runner B, limpo, recebeu via `actions/upload-artifact`/`download-artifact`, validou manifesto/hash, restaurou com `restore_hermes_mission_checkpoint` e conferiu byte-a-byte mais `load_task_result_envelope`.
- `BR_HERMES_REAL_GITHUB_TWO_JOB_ARTIFACT_HANDOFF=PASS`.
- Evidência usa tarefa fixture sintética, **não** uma missão completa multiagente/SLM; `COMPLETE_HERMES_MISSION_RESUME=NOT_PROVEN`.
- Docs: https://docs.github.com/en/actions/tutorials/store-and-share-data

### Agent Office — risco externo medido e promoção bloqueada

Run `37881402970` (pinned upstream antes de patch): `11` high/critical.
Run `37881471066` (após aplicar em lock efêmero o patch BR já existente `proxy-addr@2.0.8`): `10` pacotes HIGH remanescentes.

- Resultado **intencionalmente FAIL-CLOSED**: `BLOCKED_UNRESOLVED_HIGH`, com recibo JSON e as dependências remanescentes.
- Permanecem `@modelcontextprotocol/sdk`, `@types/jest`, `axios`, `braces`, `expect`, `jest-message-util`, `localtunnel`, `micromatch`, `toml`, `tunnelmole`. **Não** presumir todas exploráveis em produção; analisar `nodes`, severidade, caminho de execução e remediações exatas por SHA.
- `proxy-addr` tinha risco crítico em versões anteriores a 2.0.8: https://github.com/jshttp/proxy-addr/security/advisories/GHSA-jqcg-44mw-7w3h
- `braces<=3.0.3` possui aviso HIGH sem release corrigida reportada até 09/10/2026: https://github.com/advisories/GHSA-vfj7-8cjw-p6xm
- Para MCP TypeScript SDK, avisos sobre cross-client leakage e DNS rebinding: https://github.com/modelcontextprotocol/typescript-sdk/security/advisories/GHSA-345p-7cg4-v4c7 e https://github.com/modelcontextprotocol/typescript-sdk/security/advisories/GHSA-w48q-cv73-mx4w
- `integrations/munder_difflin/UPSTREAM.lock` tem allowlist histórica, mas **NÃO** é permissão para executar; `scripts/br_v24_agent_office_untrusted_npm_gate.py` ignora qualquer dispensa histórica como fonte de admissão.
- Sem falsificar PASS nem atualizar dependências arbitrariamente. Até resolver advisories por pacote, runtime externo permanece **BLOCKED**. Executores determinísticos internos do BR comprovados por outros runs não dependem dessa readmissão.

### Próximos gates de engenharia, por ordem de retorno

1. **REA própria V4 → V24:** matriz de dependências/transitividade + diff de API + revisão por componente; começar pelo avaliador puro com autorização de pesquisa, sem restaurar 21 arquivos em massa. Depois investigar FFmpeg, web HAR, binários/Ghidra mediante provas independentes.
2. **Agent Office:** revisar exact nodes + advisories + impacto runtime, substituir componentes vulneráveis por versões corrigidas quando existirem e provar `npm audit --omit=dev` + testes originais; para `braces` sem patch não criar waiver automático; manter isolado/bloqueado até correção segura.
3. **Hermes:** usar a prova de dois runners como regressão; executar missão completa somente com checkpoint, autorização e recursos admitidos. Impedir redispatch cego da tarefa primária.
4. **SLM:** modelo pequeno generativo fora do A15, admissibilidade de custo, hash de pesos e licença; usar tarefas reais/holdout do BR e avaliar tool selection/arguments/abstention/latency/memory antes de ligar um agente original. Os modelos de embedding ONNX V22 continuam reprovados.
5. **WhisperX:** seu `executor_binding` aponta ao módulo `app.services.speech.whisperx_provider`, não a um callable; conciliar semântica de PROVIDER com loader atual, sem trocar binding sem analisar contrato. Nenhuma identidade vocal clonada ou áudio privado foi acessado.
6. **YouTube:** completar leitura OAuth oficial e analytics apenas com escopos mínimos quando houver autenticação; impedir acesso externo, upload, publicação ou learning-promotion a partir de um SLM sem gate original.

**Nenhum resultado acima autoriza promover V24, gastar além de franquia autorizada, enviar mensagens, gerar voz BR_OWNER_V1 ou executar no A15.**

## 6. V24 2026-10-09 — Hermes missão completa e Agent Office sem túneis

**Estado:** desenvolvido, analisado e testado somente na branch experimental
`work/br-slm-agent-reconstruction-v24`, **sem promoção**, sem runtime upstream
Munder autorizado, sem custos novos autorizados, sem A15 como executor e sem
uso de projeto externo.

### Hermes: retomada *completa* entre runners reais — PASS

- Run `37888701220`:
  https://github.com/zenindiones-maker/BR-no-GTA/actions/runs/37888701220
- `runner-a`: executou tarefa primária via **Harness BR original**, emitiu o
  TaskResultEnvelope, salvou board/checkpoint e parou com missão incompleta.
- `runner-b`: realizou novo checkout/instalação, restaurou a mesma missão,
  reconheceu primária como concluída sem repetir execução, entregou
  evidência ao dependente e **completou a tarefa dependente**.
- Gates: `DURABLE_MISSION_RESUME=PASS`,
  `DUPLICATE_AGENT_EXECUTION_AVOIDED=PASS`,
  `CROSS_RUNNER_TYPED_HANDOFF=PASS`,
  `BR_V24_REAL_HERMES_TWO_JOB_COMPLETE_MISSION=PASS`.
- **Escopo:** duas tarefas de recuperação/retrieval read-only no Harness,
  usando Hermes já integrado. Não prova todos os executores Hermes, SLM,
  treinamento, execução autônoma contínua nem produção final.

### Agent Office/Munder: engenharia reversa da cadeia vulnerável

Pin original: `6248293a7cd9dfdbf9633d12bbe857831ccfee88`,
referenciado em `integrations/munder_difflin/UPSTREAM.lock`.
**Não foi alterado.**

- Run `37888772322`: somente `npm audit fix --package-lock-only`,
  sem `--force`, no runner descartável, reduziu `HIGH: 10 → 9`.
  MCP upstream permaneceu bloqueado.
- Run `37888947949`: análise de ancestrais de dependências mostrou
  nove HIGH alcançáveis por arestas declaradas de dependências de produção:
  a partir de `localtunnel` (ex.: `axios`) e `tunnelmole`
  (ex.: `toml`, `@types/jest`, `expect`, `jest-message-util`,
  `micromatch`, `braces`). O grafo estático **não prova explorabilidade**.
  O workflow recebeu correção posterior para salvar o JSON sem bytes
  escapados extra no final; não reutilizar artefatos antigos como JSON canônico.
- Runs `37889090586` e `37889195522`: retirar somente
  `localtunnel`/`tunnelmole` do manifest temporário e atualizar o lockfile
  resultou em **0 HIGH / 0 CRITICAL** no `npm audit --omit=dev`.
  **Não removeu** pacotes do repositório BR nem do upstream canônico.
- Engenharia reversa do código original localizou
  `src/main/slack.ts` (`SlackWebhookServer`) e
  `src/main/webhook.ts` (`WebhookServer`): seus `start()` invocam
  `listen()` **antes** de `openTunnel()`. O `listen()` faz
  `server.listen(this.port)` sem limitar endereço a loopback. Logo,
  dependência removida **sozinha não elimina o listener**.
- Run `37889406316`: o patch **temporário** em
  `scripts/br_v24_agent_office_no_ingress_patch.py` inseriu guardas
  fail-closed nos dois `start()` e substituiu imports dinâmicos de túnel por
  stubs de erro; **5 testes adversariais e typecheck Node TypeScript PASS**;
  npm audit manteve `0 HIGH / 0 CRITICAL`.
  `BR_V24_OFFICE_RUNTIME_STARTED=FALSE`:
  https://github.com/zenindiones-maker/BR-no-GTA/actions/runs/37889406316

**Escopo da correção:** viabilidade de isolamento da integração pública de
túneis Slack/webhook. A implementação do upstream nunca foi autorizada como
executor real, listener, MCP server ou autoridade do Harness. Antes de
admitir *qualquer* runtime Agent Office de terceiros, são obrigatórios:
(1) revisão de segurança independente do patch e dependências;
(2) validação de endpoints, imports dinâmicos e chamadas indiretas;
(3) ensaios reais com rede isolada, sem segredo, fora de produção;
(4) prova que funcionalidades essenciais não dependem dos túneis;
(5) autorização exata do Harness sem promover capacidades obsoletas.

### Recibos ainda bloqueados

- `V24_AGENT_OFFICE_UPSTREAM_RUNTIME=BLOCKED_PENDING_INDEPENDENT_REVIEW`
- `V24_SLM_GENERATIVE_AGENT_INFERENCE=NOT_ATTEMPTED`
- `V24_OWNER_VOICE_QWEN_PRODUCTION=BLOCKED`
- `V24_YOUTUBE_PUBLISH=HUMAN_APPROVAL_REQUIRED`
- `V24_NATIVE_REA_PORT_INTO_RUNTIME=NOT_AUTHORIZED`
- `V24_ALL_44_AGENTS_REAL_EXECUTION=NOT_PROVEN`
- `A15_COMPUTE=FORBIDDEN`

### Fontes de técnica e alertas consultados

- npm docs: https://docs.npmjs.com/cli/audit.html/
- npm overrides: https://docs.npmjs.com/cli/v11/configuring-npm/package-json#overrides
- `braces` unpatched high CVE-2026-93687:
  https://github.com/advisories/GHSA-vfj7-8cjw-p6xm
- MCP SDK cross-client fix 1.26.0:
  https://github.com/advisories/GHSA-345p-7cg4-v4c7
- GitHub Actions artifact and attestations:
  https://docs.github.com/en/actions/concepts/security/artifact-attestations
