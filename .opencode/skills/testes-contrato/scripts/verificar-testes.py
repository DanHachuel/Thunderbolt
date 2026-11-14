#!/usr/bin/env python3
"""
Auditoria de Testes: Detecta testes frágeis que apenas checam a existência de strings.
Uso: python scripts/verificar-testes.py
"""
import os
import re
import sys

# AGENTS.md (regra 3): zero mojibake. A consola do Windows (cp1252) nao imprime
# os emojis dos relatorios - reconfiguramos a saida antes de qualquer print.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (ValueError, OSError):
            pass

TARGET_DIR = "tests"
# Padrão para detectar `assert "string" in source` (testes frágeis)
FRAGILE_PATTERN = r'assert\s+["\'][^"\']+["\']\s+in\s+.*source.*'

def main():
    fragiles = []
    for root, _, files in os.walk(TARGET_DIR):
        for file in files:
            if file.endswith(".py"):
                path = os.path.join(root, file)
                with open(path, "r", encoding="utf-8") as f:
                    for i, line in enumerate(f, 1):
                        if re.search(FRAGILE_PATTERN, line):
                            fragiles.append(f"{path}:{i}")

    if fragiles:
        print("⚠️  ALERTA: Testes frágeis (apenas checam strings) encontrados:")
        for f in fragiles: print(f" - {f}")
        print("\nConsidere usar AST (ast.parse) para testar a lógica de roteamento real.")
    else:
        print("✅ Nenhum teste frágil detectado.")

if __name__ == "__main__":
    main()