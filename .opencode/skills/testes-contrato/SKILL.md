---
name: Estratégia de Testes de Contrato
description: Evita que testes fiquem "verdes" com o app quebrado. Use ao escrever testes ou corrigir bugs.
---

# 🧪 Skill: Testes de Contrato e Integração

## 1. O que é um bom teste?
- ❌ **Ruim:** `assert "render_growth" in source_code` (o código existe, mas pode nunca ser chamado).
- ✅ **Bom:** Simular a resolução do menu e verificar se a função correta é retornada.
- ✅ **Bom:** Usar AST (Abstract Syntax Tree) para verificar se o mapa de rotas aponta para o lugar certo.

## 2. Proibição de Testes Frágeis
- Se um teste falha por mudança de layout (ex: mudou de 3 para 4 colunas), atualize o teste para refletir o novo layout. **Nunca** apague o teste sem justificar.

## 3. Testes de Regressão (O Cão de Guarda)
Para cada bug corrigido:
1. Escreva um teste que simula o bug.
2. Verifique que o teste falha no código atual.
3. Corrija o código.
4. Verifique que o teste passa.
- Corrigir um bug sem adicionar um teste de regressão garante que ele voltará em poucas versões.

## 4. Blindagem do Launcher
- Sempre que alterar o `cli.mjs`, adicione testes que garantam que as flags `windowsHide`, `stdio: ignore` e o `setInterval` de Keep-Alive não foram removidas.