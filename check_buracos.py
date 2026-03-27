#!/usr/bin/env python3
import json
import os

JSON_FILE = "campos-golfe-portugal.json"

def main():
    if not os.path.exists(JSON_FILE):
        print(f"❌ Erro: O ficheiro '{JSON_FILE}' não foi encontrado.")
        return

    with open(JSON_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    campos = data.get("campos", [])
    
    sem_buracos = []
    apenas_9_buracos = []

    for campo in campos:
        nome = campo.get("nome", "Sem Nome")
        codigo = campo.get("codigo", str(campo.get("id")))
        cartoes = campo.get("cartoes", [])
        
        # Calcular o total de buracos juntando todos os cartões (se houver mais do que um)
        total_buracos = 0
        for cartao in cartoes:
            total_buracos += len(cartao.get("buracos", []))
            
        if total_buracos == 0:
            sem_buracos.append(f"[{codigo}] {nome}")
        elif total_buracos == 9:
            apenas_9_buracos.append(f"[{codigo}] {nome}")

    # --- Mostrar os Resultados ---
    print(f"⛳ Foram analisados {len(campos)} campos no total.\n")

    print(f"🔴 CAMPOS SEM BURACOS ({len(sem_buracos)}):")
    if not sem_buracos:
        print("  ✓ Nenhum! Todos os campos têm pelo menos um buraco.")
    else:
        for c in sem_buracos:
            print(f"  - {c}")

    print(f"\n🟡 CAMPOS COM APENAS 9 BURACOS ({len(apenas_9_buracos)}):")
    if not apenas_9_buracos:
        print("  ✓ Nenhum campo tem apenas 9 buracos.")
    else:
        for c in apenas_9_buracos:
            print(f"  - {c}")

if __name__ == "__main__":
    main()