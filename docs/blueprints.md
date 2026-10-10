# Blueprints — Guia

## Um blueprint é um blueprint

Não existem tipos. MILITAR, FINANCE USA, Cocomelon e os 5 Remotion
(Quiz, Social Media Reels, Top 10, Would You Rather, Inspirational
Long-Form) são todos blueprints: vivem em `seed/blueprints/`, são copiados
para `storage/blueprints/importados/` no arranque, aparecem todos na aba
**Blueprints > Blueprints Youtube** e no mesmo dropdown da UI.

A única diferença funcional: alguns blueprints têm `composition_id`. Quando
o canal usa a Fonte do Vídeo **Remotion** e o blueprint escolhido tem
`composition_id`, o pipeline gera o JSON estruturado do `output_schema`
desse blueprint e renderiza com a composição correspondente. Sem
`composition_id`, a rota Remotion usa o roteiro e a narração normais.

## Regras

- **Uma pasta**: `seed/blueprints/` (copiada para `storage/blueprints/importados/`).
- **Uma lista**: `list_blueprints()` no `hermes_ui/blueprint_loader.py` — todos os blueprints, sem filtro.
- **Um dropdown** no modo Remotion: a lista completa de blueprints.
- **Um prompt**: `build_system_prompt(blueprint)` usa apenas os campos do próprio blueprint (constraints, output_schema, reference_example, difficulty_calibration).
- O `{{difficulty}}` (blueprint Quiz) e o `{{language}}` são resolvidos em runtime; `default_values.difficulty = "Average"` quando o utilizador não escolhe.
- A validação Pydantic (`hermes_ui/schemas/`) é indexada pelo `composition_id` (Quiz, SocialReel, Top10, WouldYouRather, InspirationalVideo).
- A duração é derivada exclusivamente pelo `calculateMetadata` da composição Remotion — nunca calculada no Python.

## Como adicionar um novo blueprint Remotion

1. Criar o JSON em `seed/blueprints/` com `composition_id`, `fps`,
   `width`/`height`, `constraints`, `output_schema`, `reference_example` e
   `remotion_mapping`.
2. Criar a composição em `packages/remotion/src/compositions/<Nome>.tsx`.
3. Registar em `packages/remotion/src/Root.tsx` com `calculateMetadata` que
   espelha exactamente o layout de Sequences do componente.
4. Criar o modelo Pydantic em `hermes_ui/schemas/` e registá-lo no
   `SCHEMAS` com a chave = `composition_id`.
5. Adicionar os ramos de extração/injecção em `hermes_ui/blueprint_assets.py`
   (também por `composition_id`).
6. Adicionar testes em `tests/test_blueprint_loader.py`,
   `tests/test_blueprint_assets.py` e `tests/test_blueprint_pipeline.py`.

## Limitações

- Timeout total: 20 minutos por tarefa.
- Imagens: 4 workers paralelos máximo (pool de imagem do sistema).
- TTS: série, pela cadeia TTS do sistema (voz do canal/Configurações).

## Preparação para @remotion/lambda

A arquitectura é portável: os blueprints, schemas e wrapper não mudam. Apenas
`run_remotion_render()` precisa ser adaptado para chamar a API Lambda em vez
do subprocesso local.
