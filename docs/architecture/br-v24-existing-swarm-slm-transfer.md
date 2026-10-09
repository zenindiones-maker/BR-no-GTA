# BR-no-GTA V24 — reaproveitar o swarm existente com SLMs (sem recriar agentes)

**Estado:** candidato experimental, *SHADOW / INVENTÁRIO*. **Repositório único:** `zenindiones-maker/BR-no-GTA`. **Autoridade única:** DeepSeek Harness. Não modifica os executores, o roteador, os modelos, os direitos ou a produção.

## Objetivo do proprietário

Há um swarm grande de agentes, skills e executores do BR já registrados. **Não criar outro swarm.** Reconstruir por engenharia reversa o comportamento observável dos agentes existentes e qualificar SLMs menores para tarefas **específicas**. O A15 continua só para SSH/controle; modelos, datasets e tarefas pesadas exclusivamente remotas.

A imagem LLM/SLM é ilustração. Um SLM **não substitui automaticamente** Hermes, Agent Office, Codex, Qwen3-TTS, FFmpeg, REA ou qualquer ferramenta externa. Um modelo de embeddings ONNX (V21/V22) é apenas um *encoder para propostas de classificação*, não um LLM generativo com tool-use.

## Fonte de verdade e wiring atual

- `GLOBAL_CAPABILITY_REGISTRY` define capabilities, agent_ids, vínculos de executor, actions, security boundary, provider/model, availability, health/evidence contracts.
- `app/services/agent_office/task_owner_registry.py` deriva perfis do registro canônico, sem segundo cadastro.
- `app/services/hermes_multiagent/registry_roster.py` projeta o mesmo registro e valida identidade de agentes/skills, actions e executor vinculado.
- `app/services/harness_routing_policy_service.py` mantém seleção de capacidade/provedor e políticas; **não é alterado** nesta fase.
- `app/services/br_slm_onnx_shadow_v21.py` e `app/services/br_slm_evidence_verifier_v22.py` fornecem somente o experimento de domínio visual/ledger e verificação estrutural.
- `app/services/br_slm_swarm_bridge_v24.py` acrescenta leitura/triagem e sugestões **não executáveis** de SLM por capacidade; não altera nenhum registro, executor, roteamento ou agente.

### Evidence-first / REA do próprio BR

Usar exclusivamente a trajetória REA do BR (V1/V3/V4), documentada em `docs/operations/br-v23-rea-native-provenance.md`, para investigar os contratos, entradas, saídas, ferramentas, falhas e comportamento de cada agente original. REA é um sensor subordinado; seu grafo estático e metadata **não demonstram** equivalência operacional ou competência de um SLM.

## O que implementar depois do censo

1. **Censo executável:** contar capabilities e agent_ids do registro real (não confundir número de entradas com processos, sessões ou agentes funcionando), separar AVAILABLE/DECLARED executor de runtime testado. Gerar recibo SHA exato com somente metadados de contratos.
2. **Matriz agent × task × tool × SLM:** para cada capacidade candidata, ligar `capability_id` original a dados de tarefas autorizadas, critério de sucesso e modelo candidato, sem mudar `selected_executor_binding`.
3. **Ablation com baselines:** comparar agente atual, modelo pequeno, regras determinísticas e abstenção sobre os *mesmos* casos; medir qualidade, conformidade JSON, tool-call accuracy, violação de permissão, latência p50/p95, RAM, custo, PT-BR e degradação por tipo de tarefa.
4. **Dados independentes:** benchmark com dados sintéticos próprios e tarefas anonimizadas autorizadas; segregar desenvolvimento, validação e holdout. Proibir usar a biometria BR_OWNER_V1, dados do Telegram ou segredos de operações.
5. **Adversarial:** injeção de prompt, alucinação de executor, argumentos de ferramenta fora do schema, alteração de branch/capability, falso PASS, classificação OOD, timeout/crash/retentativas sem checkpoints.
6. **Execução real:** iniciar com uma única rota não sensível e read-only em Codespace/runner remoto. Somente com autorização independente do Harness, tool calls observáveis e evidências de competência é possível cogitar propor a integração operacional.
7. **Promoção:** autorização, revisão de segurança independente, custo comprovado, testes repetidos, aprovação humana e limite de regressão. Caso contrário, manter o agente original e/ou abster-se; nunca habilitar fallback de gastos ou passar processamento para o A15.

## Estado real de qualidade anterior

O V22 reproduziu ONNX CPU e registrou holdout (run `37857856572`):
- 16 tarefas in-domain, acurácia **0,625** (10 corretas, 6 incorretas); rejeitado diante de mínimo 0,85.
- 12 OOD, abstenção 1,0.
- A maioria dos erros do holdout foi **abstenção indevida**, não concessão de autoridade: cinco visuais e um ledger.
- Isso **não valida** a aptidão de agentes generativos e não autoriza promover um classificador com limiar relaxado.

## Limites de afirmação V24

`app/services/br_slm_swarm_bridge_v24.py` só inventaria metadados do Registry e valida sugestão hipotética. `benchmark_approved` é uma **alegação de entrada de teste**, não um recibo autenticado do Harness; mesmo verdadeiro, o retorno é `PROPOSAL_ONLY`, sem chamada de ferramenta. Runtime do agente, modelo, servidor SLM, qualidade e equivalência são todos **NOT_PROVEN** até testes específicos.

- `NEW_AGENTS=0`
- `SLM_INFERENCE=NOT_ATTEMPTED`
- `HERMES_DISPATCH=NOT_ATTEMPTED`
- `AGENT_OFFICE_DISPATCH=NOT_ATTEMPTED`
- `QWEN3_TTS=NOT_ATTEMPTED`
- `BR_OWNER_V1=NOT_ACCESSED`
- `ROUTER_MUTATION=NONE`
- `CANONICAL_PROMOTION=NOT_ATTEMPTED`
- `A15_COMPUTE=FORBIDDEN`

**Referência:** run V22 `https://github.com/zenindiones-maker/BR-no-GTA/actions/runs/37857856572`.
