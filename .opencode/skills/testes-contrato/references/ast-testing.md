# Testes de Contrato com AST (Abstract Syntax Tree)

Testar apenas se uma string existe no arquivo não garante que o código funciona. Exemplo de teste ruim:
```python
assert '"Growth": render_growth_pages' in source_code
```

(O código existe, mas e se a rota nunca for chamada?)

Exemplo de teste robusto com AST:

```python
import ast

def test_growth_route_resolution():
    source = open("app/main.py").read()
    tree = ast.parse(source)
    # Lógica para encontrar o dicionário de rotas e verificar se a chave "Growth" 
    # aponta para a função "render_growth_pages".
```


