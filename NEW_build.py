#!/usr/bin/env python3
"""
build.py — Regenera o index.html com dados actualizados

Uso:
    python build.py

Lê:
    campos-golfe-portugal.json   (obrigatório)
    Pic1.jpg                     (opcional — hero + modal)
    Pic2.jpg                     (opcional — cards de campo)

Gera:
    index.html

Se as imagens não estiverem presentes, mantém as que já estão no index.html.
"""

import json
import re
import sys
import base64
import os
from datetime import datetime

# ── Ficheiros ──────────────────────────────────────────────
JSON_FILE   = "campos-golfe-portugal.json"
HTML_FILE   = "index.html"
PIC1_FILE   = "Pic1.jpg"   # hero + modal background
PIC2_FILE   = "Pic2.jpg"   # grid cards background

# ── Helpers ────────────────────────────────────────────────
def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def encode_image(path, max_w=1400, quality=83):
    """Redimensiona e converte imagem para base64."""
    try:
        from PIL import Image
        import io
        img = Image.open(path)
        img.thumbnail((max_w, 1000))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=quality)
        return base64.b64encode(buf.getvalue()).decode()
    except ImportError:
        # Sem Pillow — embutir directamente sem redimensionar
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode()

def find_array_end(content, start):
    """Encontra o índice do ] de fecho de um array JSON."""
    depth = 0
    for i, ch in enumerate(content[start:]):
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return start + i + 1
    return -1

def find_b64_end(content, start):
    """Encontra o fim de uma string base64 (termina em ')"""
    end = content.find("')", start)
    return end + 2 if end != -1 else -1

# ── Carregar JSON ──────────────────────────────────────────
if not os.path.exists(JSON_FILE):
    print(f"❌  Ficheiro '{JSON_FILE}' não encontrado.")
    sys.exit(1)

print(f"📂  A ler {JSON_FILE}...")
data = load_json(JSON_FILE)

# Suporta tanto { "campos": [...] } como directamente [...]
if isinstance(data, dict):
    campos = data.get("campos", data)
    meta = data.get("meta", {})
else:
    campos = data
    meta = {}

if not campos:
    print("❌  Nenhum campo encontrado no JSON.")
    sys.exit(1)

print(f"    {len(campos)} campos carregados.")

# ── Calcular totais dinâmicos ──────────────────────────────
total_campos   = len(campos)
total_distritos = len(set(c.get("distrito") for c in campos if c.get("distrito")))
total_tees = 0
for c in campos:
    for cart in (c.get("cartoes") or []):
        total_tees += len(cart.get("tees") or [])

# Top 9 por slope
def max_slope(c):
    slopes = [
        t.get("slope_homens", 0)
        for cart in (c.get("cartoes") or [])
        for t in (cart.get("tees") or [])
        if t.get("slope_homens")
    ]
    return max(slopes) if slopes else 0

sorted_ids = [c["id"] for c in sorted(campos, key=max_slope, reverse=True)]
campos_json  = json.dumps(campos, ensure_ascii=False, separators=(",", ":"))
sorted_json  = json.dumps(sorted_ids)

# ── Carregar index.html existente ──────────────────────────
if not os.path.exists(HTML_FILE):
    print(f"❌  Ficheiro '{HTML_FILE}' não encontrado.")
    print("    Coloca o index.html na mesma pasta que o build.py.")
    sys.exit(1)

print(f"📂  A ler {HTML_FILE}...")
with open(HTML_FILE, "r", encoding="utf-8") as f:
    content = f.read()

original_size = len(content)

# ── Substituir CAMPOS array ────────────────────────────────
m = re.search(r"const CAMPOS = (\[)", content)
if not m:
    print("❌  Não foi possível encontrar 'const CAMPOS = [' no HTML.")
    sys.exit(1)

arr_start = m.start(1)
arr_end   = find_array_end(content, arr_start)
if arr_end == -1:
    print("❌  Não foi possível encontrar o fecho do array CAMPOS.")
    sys.exit(1)

content = content[:arr_start] + campos_json + content[arr_end:]
print(f"✅  CAMPOS actualizado ({len(campos)} campos).")

# ── Substituir CAMPOS_SORTED_IDS (se existir) ─────────────
m2 = re.search(r"const CAMPOS_SORTED_IDS = (\[.*?\]);", content)
if m2:
    content = content[:m2.start(1)] + sorted_json + content[m2.end(1):]
    print(f"✅  CAMPOS_SORTED_IDS actualizado.")

# ── Actualizar estatísticas no hero (se usarem valores fixos) ─
content = re.sub(
    r'(<div class="val">)\d+(</div>\s*<div class="lbl">campos</div>)',
    rf'\g<1>{total_campos}\g<2>',
    content
)
content = re.sub(
    r'(<div class="val">)\d+(</div>\s*<div class="lbl">Campos</div>)',
    rf'\g<1>{total_campos}\g<2>',
    content
)
content = re.sub(
    r'(<div class="val">)\d+(</div>\s*<div class="lbl">Distritos</div>)',
    rf'\g<1>{total_distritos}\g<2>',
    content
)
content = re.sub(
    r'(<div class="val">)\d+(</div>\s*<div class="lbl">Tees</div>)',
    rf'\g<1>{total_tees}\g<2>',
    content
)
# Hero subtitle
content = re.sub(
    r'\d+ campos nacionais',
    f'{total_campos} campos nacionais',
    content
)
# Footer / subtítulo
content = re.sub(
    r'\d+ campos · Dados FPG',
    f'{total_campos} campos · Dados FPG',
    content
)
print(f"✅  Totais actualizados: {total_campos} campos · {total_distritos} distritos · {total_tees} tees.")

# ── Substituir imagens (se os ficheiros existirem) ─────────
def replace_b64_image(content, label, new_b64):
    """
    Substitui a primeira ocorrência de base64 dentro do bloco CSS/HTML
    que contém 'label'.
    """
    marker = f"url('data:image/jpeg;base64,"
    idx = 0
    while True:
        pos = content.find(marker, idx)
        if pos == -1:
            break
        # Verificar contexto (100 chars antes)
        ctx = content[max(0, pos - 150):pos]
        if label in ctx:
            b64_data_start = pos + len(marker)
            b64_data_end = content.find("')", b64_data_start)
            if b64_data_end == -1:
                break
            content = content[:b64_data_start] + new_b64 + content[b64_data_end:]
            return content, True
        idx = pos + 1
    return content, False

for pic_file, label, desc in [
    (PIC1_FILE, "hero-bg",       "hero + modal"),
    (PIC1_FILE, "modal-hero-bg", "modal hero"),
    (PIC2_FILE, "grid-card-bg",  "grid cards"),
]:
    if os.path.exists(pic_file):
        print(f"🖼️   A processar {pic_file} ({desc})...")
        b64 = encode_image(pic_file)
        content, replaced = replace_b64_image(content, label, b64)
        status = "✅" if replaced else "⚠️  não encontrado no HTML"
        print(f"    {status}  {desc}")
    else:
        print(f"ℹ️   {pic_file} não encontrado — imagem mantida do HTML existente.")

# ── Guardar ────────────────────────────────────────────────
with open(HTML_FILE, "w", encoding="utf-8") as f:
    f.write(content)

new_size = len(content)
print()
print(f"✅  {HTML_FILE} regenerado com sucesso!")
print(f"    Tamanho: {original_size/1024:.0f} KB → {new_size/1024:.0f} KB")
print(f"    Data: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print()
print("📋  Resumo:")
print(f"    Campos:    {total_campos}")
print(f"    Distritos: {total_distritos}")
print(f"    Tees:      {total_tees}")