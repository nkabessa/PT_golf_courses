#!/usr/bin/env python3
"""
Scraper de Campos de Golfe — Federação Portuguesa de Golfe
Versão Definitiva: Extração Matemática Estrutural
"""

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import requests
from bs4 import BeautifulSoup

# ------------------------------------------------------------
# Configuração
# ------------------------------------------------------------
ACK         = "8428ACK987"
CLUB        = "ALL"
BASE_URL    = "https://scoring-pt.datagolf.pt/scripts"
RANGE_FROM  = 1
RANGE_TO    = 350
MAX_CARDS   = 6      
CONCURRENCY = 2       
DELAY_S     = 1.0     
OUTPUT      = "campos-golfe-portugal.json"
TIMEOUT     = 15

TEE_BGCOLOR_MAP = {
    "#ffffff": "Branco", "#ffff00": "Amarelo", "#0000ff": "Azul",
    "#ff0000": "Vermelho", "#a000a0": "Roxo", "#ff8c00": "Laranja",
    "#008000": "Verde", "#808080": "Cinzento", "#000000": "Preto",
    "#dddddd": "Prateado"
}

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; GolfPT-Scraper/3.0)"
})

def fetch(url: str) -> str | None:
    try:
        r = SESSION.get(url, timeout=TIMEOUT)
        r.encoding = "utf-8"
        return r.text
    except Exception:
        return None

def clean(text: str | None) -> str | None:
    if not text: return None
    return text.replace("\xa0", "").replace("&nbsp;", "").strip() or None

def get_bg_color(cell) -> str:
    """Extrai a cor de fundo com segurança"""
    bg = cell.get("bgcolor", "").strip()
    if not bg and cell.get("style"):
        m = re.search(r"background(?:-color)?:\s*(#[0-9a-fA-F]{3,6}|[a-zA-Z]+)", cell.get("style", ""), re.I)
        if m: bg = m.group(1)
    bg = bg.strip().lower()
    return bg if bg.startswith("#") else "#" + bg

def parse_course(html: str, ncourse: str) -> dict | None:
    if not html or len(html) < 300: return None
    soup = BeautifulSoup(html, "html.parser")
    h5 = soup.find("h5")
    if not h5: return None
    nome = clean(h5.get_text())
    if not nome or len(nome) < 3: return None

    def get_field(label: str) -> str | None:
        for td in soup.find_all("td", attrs={"align": "right"}):
            if label.lower() in td.get_text().lower():
                tr = td.find_parent("tr")
                if not tr: continue
                tds = tr.find_all("td")
                for i, t in enumerate(tds):
                    if t is td:
                        for nxt in tds[i + 1:]:
                            val = clean(nxt.get_text())
                            if val: return val
        return None

    facilidades = []
    for td in soup.find_all("td"):
        if "facilidades" in td.get_text().lower():
            fac_table = td.find_parent("table")
            if fac_table:
                for b in fac_table.find_all("b"):
                    f = clean(b.get_text())
                    if f and len(f) > 1 and f not in facilidades:
                        facilidades.append(f)
            break

    card_ids = []
    for iframe in soup.find_all("iframe", src=True):
        src = iframe["src"]
        m = re.search(r"ncourse=(\d{3}-\d+)", src)
        if m: card_ids.append(m.group(1))

    return {
        "id": int(ncourse), "codigo": ncourse, "nome": nome,
        "distrito": get_field("Distrito"), "facilidades": facilidades, 
        "card_ids": card_ids, "cartoes": [],
        "url": f"{BASE_URL}/course.asp?ncourse={ncourse}&ack={ACK}&club={CLUB}",
    }

def parse_card(html: str, card_id: str) -> dict | None:
    if not html or len(html) < 300 or "Erro" in html or "BOF" in html: return None
    soup = BeautifulSoup(html, "html.parser")

    main_table = None
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        for row in rows[:10]:
            txt = row.get_text().lower()
            if "hole" in txt or "buraco" in txt:
                main_table = table
                break
        if not main_table:
            for row in rows[:15]:
                cells = row.find_all(["td", "th"])
                if cells and cells[0].get_text(strip=True).replace(".", "") in ["1", "01"] and len(cells) > 3:
                    main_table = table
                    break
        if main_table: break

    if not main_table: return None
    rows = main_table.find_all("tr")

    # Encontrar a linha de dados do Buraco 1
    first_row_cells = None
    for row in rows:
        cells = row.find_all(["td", "th"])
        if not cells: continue
        v0 = cells[0].get_text(strip=True).replace("\xa0", "").replace(".", "").strip()
        if re.match(r"^\d{1,2}$", v0) and 1 <= int(v0) <= 9:
            first_row_cells = cells
            break

    if not first_row_cells: return None

    # ESTRATÉGIA MATEMÁTICA: Conta os tees com base nas distâncias
    n_tees = 0
    for cell in first_row_cells[1:]:
        val_str = cell.get_text(strip=True).replace("\xa0", "").replace(".", "").strip()
        if val_str.isdigit():
            val = int(val_str)
            if val <= 10:  # É o Par do buraco! Para a contagem.
                break
            else:
                n_tees += 1
        else:
            n_tees += 1 # Conta como tee se for espaço vazio nas distâncias
            
    if n_tees == 0: return None

    # Procurar a linha de cabeçalho (para sacar as cores)
    header_row = None
    for row in rows[:15]:
        txt = row.get_text().lower()
        if "buraco" in txt or "hole" in txt:
            header_row = row
            break

    # Associa as cores exatas às colunas encontradas
    tee_order = []
    for i in range(1, n_tees + 1):
        bg = get_bg_color(first_row_cells[i])
        
        # Se a cor não estiver explícita no dado, tenta ler do cabeçalho
        if bg == "#" or bg not in TEE_BGCOLOR_MAP:
            if header_row:
                h_cells = header_row.find_all(["td", "th"])
                if i < len(h_cells):
                    bg_head = get_bg_color(h_cells[i])
                    if bg_head in TEE_BGCOLOR_MAP:
                        bg = bg_head
                        
        # Prevenção final se falhar leitura
        if bg not in TEE_BGCOLOR_MAP:
            defaults = ["#ffff00", "#ff0000", "#0000ff", "#ffffff", "#000000"]
            bg = defaults[i - 1] if i - 1 < len(defaults) else "#ffffff"
            
        tee_order.append(bg)

    tees_data = {bg: {
        "cor": TEE_BGCOLOR_MAP.get(bg, "Branco"), "bgcolor": bg,
        "metros_total": None, "par_total": None,
        "cr_homens": None, "slope_homens": None,
        "cr_senhoras": None, "slope_senhoras": None,
    } for bg in tee_order}

    buracos = []
    any_slope_h = False
    global_back_start = None

    # Extração Perfeita Alinhada
    for row in rows:
        cells = row.find_all(["td", "th"])
        if not cells or len(cells) <= 2: continue
        vals = [td.get_text(strip=True).replace("\xa0", "").strip() for td in cells]
        first_raw = vals[0]
        first_num = first_raw.replace(".", "").strip()

        if re.match(r"^\d{1,2}$", first_num) and 1 <= int(first_num) <= 9:
            h_f = int(first_num)
            metros_f = {}
            for i, bg in enumerate(tee_order):
                v = vals[1 + i] if 1 + i < len(vals) else ""
                if v.isdigit(): metros_f[TEE_BGCOLOR_MAP.get(bg, "Branco")] = int(v)
            
            par_f = int(vals[n_tees + 1]) if n_tees + 1 < len(vals) and vals[n_tees + 1].isdigit() else None
            si_f  = int(vals[n_tees + 2]) if n_tees + 2 < len(vals) and vals[n_tees + 2].isdigit() else None
            buracos.append({"buraco": h_f, "par": par_f, "si": si_f, "metros": metros_f})

            target_b = str(h_f + 9)
            row_back_start = -1
            for idx in range(n_tees + 1, len(vals)):
                if vals[idx].replace(".", "").strip() == target_b:
                    row_back_start = idx
                    global_back_start = idx
                    break
            
            if row_back_start != -1:
                h_b = int(vals[row_back_start].replace(".", ""))
                metros_b = {}
                for i, bg in enumerate(tee_order):
                    idx = row_back_start + 1 + i
                    v = vals[idx] if idx < len(vals) else ""
                    if v.isdigit(): metros_b[TEE_BGCOLOR_MAP.get(bg, "Branco")] = int(v)
                
                par_b_idx = row_back_start + 1 + n_tees
                si_b_idx  = row_back_start + 2 + n_tees
                par_b = int(vals[par_b_idx]) if par_b_idx < len(vals) and vals[par_b_idx].isdigit() else None
                si_b  = int(vals[si_b_idx])  if si_b_idx  < len(vals) and vals[si_b_idx].isdigit()  else None
                buracos.append({"buraco": h_b, "par": par_b, "si": si_b, "metros": metros_b})

        elif first_raw.upper() == "TOT":
            target_start = global_back_start if global_back_start is not None else 0
            for i, bg in enumerate(tee_order):
                idx = target_start + 1 + i
                v   = vals[idx] if idx < len(vals) else ""
                if v.isdigit(): tees_data[bg]["metros_total"] = int(v)
            par_idx = target_start + 1 + n_tees
            if par_idx < len(vals) and vals[par_idx].isdigit():
                pv = int(vals[par_idx])
                if 27 <= pv <= 75:
                    for bg in tee_order: tees_data[bg]["par_total"] = pv

        elif "c.rat" in first_raw.lower() or "rating" in first_raw.lower():
            mode = "s" if "senhor" in row.get_text().lower() else "h"
            for i, bg in enumerate(tee_order):
                v = vals[1 + i] if 1 + i < len(vals) else ""
                try:
                    fv = float(v.replace(",", "."))
                    if 50 <= fv <= 90:
                        if mode == "h": tees_data[bg]["cr_homens"] = fv
                        else: tees_data[bg]["cr_senhoras"] = fv
                except ValueError: pass

        elif first_raw.lower() == "slope":
            mode = "s" if any_slope_h else "h"
            for i, bg in enumerate(tee_order):
                v = vals[1 + i] if 1 + i < len(vals) else ""
                if v.isdigit():
                    iv = int(v)
                    if 50 <= iv <= 160:
                        if mode == "h": tees_data[bg]["slope_homens"] = iv
                        else: tees_data[bg]["slope_senhoras"] = iv
            if mode == "h": any_slope_h = True

    unique_buracos = {}
    for b in buracos: unique_buracos[b["buraco"]] = b
    final_buracos = [unique_buracos[k] for k in sorted(unique_buracos.keys())]

    return { "card_id": card_id, "tees": list(tees_data.values()), "buracos": final_buracos }

def scrape_course(ncourse: str) -> dict | None:
    url = f"{BASE_URL}/course.asp?ncourse={ncourse}&ack={ACK}&club={CLUB}"
    html = fetch(url)
    if not html: return None

    campo = parse_course(html, ncourse)
    if not campo: return None

    for card_id in campo.get("card_ids", []):
        card_url = f"{BASE_URL}/show_card.asp?ncourse={card_id}&inframe=Y&stat=Y&info=Y&ack={ACK}&club={CLUB}"
        card_html = fetch(card_url)
        if card_html:
            cartao = parse_card(card_html, card_id)
            if cartao: campo["cartoes"].append(cartao)

    if not campo["card_ids"]:
        for i in range(1, MAX_CARDS + 1):
            card_id = f"{ncourse}-{i}"
            card_url = f"{BASE_URL}/show_card.asp?ncourse={card_id}&inframe=Y&stat=Y&info=Y&ack={ACK}&club={CLUB}"
            card_html = fetch(card_url)
            if not card_html or "Erro de Parametros" in card_html or "BOF" in card_html: break
            cartao = parse_card(card_html, card_id)
            if cartao: campo["cartoes"].append(cartao)

    del campo["card_ids"]
    
    # FUSÃO INTELIGENTE:
    if campo["cartoes"]:
        cartoes_finais = []
        for c in campo["cartoes"]:
            merged = False
            for final_c in cartoes_finais:
                b_existentes = {b["buraco"] for b in final_c["buracos"]}
                b_novos = {b["buraco"] for b in c["buracos"]}
                
                if not b_existentes.intersection(b_novos):
                    t_dict = {t["cor"]: t for t in final_c["tees"]}
                    for t in c["tees"]: t_dict[t["cor"]] = t
                    final_c["tees"] = list(t_dict.values())
                    final_c["buracos"].extend(c["buracos"])
                    final_c["buracos"].sort(key=lambda x: x["buraco"])
                    merged = True
                    break
                elif len(final_c["buracos"]) == 9 and len(c["buracos"]) == 9:
                    t_dict = {t["cor"]: t for t in final_c["tees"]}
                    for t in c["tees"]: t_dict[t["cor"]] = t
                    final_c["tees"] = list(t_dict.values())
                    for b in c["buracos"]: b["buraco"] += 9
                    final_c["buracos"].extend(c["buracos"])
                    final_c["buracos"].sort(key=lambda x: x["buraco"])
                    merged = True
                    break
            
            if not merged: cartoes_finais.append(c)
        campo["cartoes"] = cartoes_finais
    return campo

def main():
    print(f"\n⛳ A extrair campos (IDs {RANGE_FROM}-{RANGE_TO}) - Delay: {DELAY_S}s...")
    numbers = [str(i).zfill(3) for i in range(RANGE_FROM, RANGE_TO + 1)]
    results, failed = [], []

    for batch_start in range(0, len(numbers), CONCURRENCY):
        batch = numbers[batch_start : batch_start + CONCURRENCY]
        with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
            futures = {executor.submit(scrape_course, n): n for n in batch}
            for future in as_completed(futures):
                ncourse = futures[future]
                try:
                    campo = future.result()
                    if campo:
                        results.append(campo)
                        b_cartao1 = len(campo["cartoes"][0]["buracos"]) if campo["cartoes"] else 0
                        print(f"  ✓ [{ncourse}] {campo['nome']} — [{b_cartao1} buracos extraídos]")
                except Exception as e:
                    failed.append(ncourse)

        time.sleep(DELAY_S)

    results.sort(key=lambda x: x["id"])
    
    output = {
        "meta": {
            "fonte": "scoring-pt.datagolf.pt",
            "total_campos": len(results),
            "extraido_em": datetime.utcnow().isoformat() + "Z",
            "range_pesquisado": f"{RANGE_FROM}-{RANGE_TO}",
            "falhas": len(failed)
        },
        "campos": results
    }
    
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
        
    print(f"\n✅ Concluído! Extraídos {len(results)} campos.")

if __name__ == "__main__":
    main()