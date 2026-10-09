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
