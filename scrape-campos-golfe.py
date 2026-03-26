#!/usr/bin/env python3
"""
Scraper de Campos de Golfe — Federação Portuguesa de Golfe
Fonte: scoring-pt.datagolf.pt

Uso:
    pip install requests beautifulsoup4
    python scrape-campos-golfe.py

Output: campos-golfe-portugal.json
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
MAX_CARDS   = 6      # máximo de cartões por campo (025-1, 025-2, ...)
CONCURRENCY = 5
DELAY_S     = 0.3
OUTPUT      = "campos-golfe-portugal.json"
TIMEOUT     = 15

# ------------------------------------------------------------
# Mapeamento de bgcolor → nome do tee
# ------------------------------------------------------------
TEE_BGCOLOR_MAP = {
    "#ffffff": "Branco",
    "#ffff00": "Amarelo",
    "#0000ff": "Azul",
    "#ff0000": "Vermelho",
    "#a000a0": "Roxo",
    "#ff8c00": "Laranja",
    "#008000": "Verde",
    "#808080": "Cinzento",
    "#000000": "Preto",
}
# Cores inequivocamente tee (nunca são par/SI)
UNAMBIGUOUS_TEE_COLORS = {
    "#ffff00", "#0000ff", "#ff0000", "#a000a0",
    "#ff8c00", "#008000", "#808080", "#000000"
}

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; GolfPT-Scraper/1.0)"
})

# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------
def fetch(url: str) -> str | None:
    """Faz um pedido HTTP e devolve o HTML. Encoding real é UTF-8."""
    try:
        r = SESSION.get(url, timeout=TIMEOUT)
        r.encoding = "utf-8"
        return r.text
    except Exception:
        return None

def clean(text: str | None) -> str | None:
    """Remove espaços e caracteres não-breaking."""
    if not text:
        return None
    text = text.replace("\xa0", "").replace("&nbsp;", "").strip()
    return text or None

def _norm_bg(bg: str) -> str:
    """Normaliza bgcolor para lowercase com #."""
    bg = bg.strip().lower()
    return bg if bg.startswith("#") else "#" + bg

# ------------------------------------------------------------
# Parse course.asp → info geral + iframes + GPS
# ------------------------------------------------------------
def parse_course(html: str, ncourse: str) -> dict | None:
    if not html or len(html) < 300:
        return None

    soup = BeautifulSoup(html, "html.parser")

    h5 = soup.find("h5")
    if not h5:
        return None
    nome = clean(h5.get_text())
    if not nome or len(nome) < 3:
        return None

    def get_field(label: str) -> str | None:
        for td in soup.find_all("td", attrs={"align": "right"}):
            if label.lower() in td.get_text().lower():
                tr = td.find_parent("tr")
                if not tr:
                    continue
                tds = tr.find_all("td")
                for i, t in enumerate(tds):
                    if t is td:
                        for nxt in tds[i + 1:]:
                            val = clean(nxt.get_text())
                            if val:
                                return val
        return None

    proprietario = get_field("Propriet")
    morada       = get_field("Morada")
    cidade       = get_field("Cidade")
    cod_postal   = get_field("Postal")
    telefone     = get_field("Telefone")
    fax          = get_field("Fax")
    distrito     = get_field("Distrito")
    data_ab      = get_field("Data Abertura")
    profissional = get_field("Profissional")

    email = None
    mailto = soup.find("a", href=re.compile(r"^mailto:", re.I))
    if mailto:
        email = clean(mailto.get_text())
        if email:
            email = email.lower()

    website = None
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("http") and "datagolf" not in href and "mailto" not in href:
            website = clean(a.get_text()) or href
            break

    # Facilidades
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

    # IDs dos cartões (iframes show_card.asp?ncourse=025-1, 025-2, ...)
    card_ids = []
    for iframe in soup.find_all("iframe", src=True):
        src = iframe["src"]
        m = re.search(r"ncourse=(\d{3}-\d+)", src)
        if m:
            card_ids.append(m.group(1))

    # Coordenadas GPS do Google Maps embed
    lat = lon = None
    for iframe in soup.find_all("iframe", src=True):
        src = iframe["src"]
        m = re.search(r"daddr=([-\d.]+),([-\d.]+)", src)
        if m:
            lat = float(m.group(1))
            lon = float(m.group(2))
            break

    return {
        "id": int(ncourse),
        "codigo": ncourse,
        "nome": nome,
        "proprietario": proprietario,
        "morada": morada,
        "cidade": cidade,
        "cod_postal": cod_postal,
        "telefone": telefone,
        "fax": fax,
        "email": email,
        "distrito": distrito,
        "website": website,
        "data_abertura": data_ab,
        "profissional": profissional,
        "coordenadas": {"lat": lat, "lon": lon} if lat else None,
        "facilidades": facilidades,
        "card_ids": card_ids,  # temporário
        "cartoes": [],
        "url": f"{BASE_URL}/course.asp?ncourse={ncourse}&ack={ACK}&club={CLUB}",
    }

# ------------------------------------------------------------
# Parse show_card.asp → cartão completo (18 buracos, slope, CR)
# ------------------------------------------------------------
def parse_card(html: str, card_id: str) -> dict | None:
    """
    Estrutura da linha de buraco (rowspan do separador colapsado pelo BS4):
      [0]=hole_f  [1..n]=metros_f  [n+1]=par_f  [n+2]=si_f
      [n+3]=hole_b  [n+4..2n+3]=metros_b  [2n+4]=par_b  [2n+5]=si_b
    """
    if not html or len(html) < 300:
        return None
    if "Erro de Parametros" in html or "BOF or EOF" in html:
        return None

    soup = BeautifulSoup(html, "html.parser")

    nome = None
    b = soup.find("b")
    if b:
        nome = b.get_text(strip=True)

    arquitecto = None
    for td in soup.find_all("td", attrs={"align": "right"}):
        if "arquitecto" in td.get_text().lower() or "arquiteto" in td.get_text().lower():
            tr = td.find_parent("tr")
            if tr:
                tds = tr.find_all("td")
                for i, t in enumerate(tds):
                    if t is td and i + 1 < len(tds):
                        val = clean(tds[i + 1].get_text())
                        if val:
                            arquitecto = val
            break

    # Tabela principal — tem "hole" no cabeçalho
    main_table = None
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if rows and "hole" in rows[0].get_text().lower():
            main_table = table
            break
    if not main_table:
        return None

    rows = main_table.find_all("tr")

    # Detectar tee_order a partir da 1ª linha de dados (buraco 1-9)
    first_row_cells = None
    for row in rows[1:]:
        cells = row.find_all("td")
        if not cells:
            continue
        v0 = cells[0].get_text(strip=True).replace("\xa0", "").strip()
        if re.match(r"^\d{1,2}$", v0) and 1 <= int(v0) <= 9:
            first_row_cells = cells
            break

    if not first_row_cells:
        return None

    # Identificar tees:
    # - Cores inequívocas (#ffff00, #0000ff, etc.) → sempre tee
    # - Branco (#ffffff) → tee só se valor >= 50 (metros); abaixo de 50 é par/SI
    tee_order = []
    for cell in first_row_cells[1:]:
        bg  = _norm_bg(cell.get("bgcolor", ""))
        val = cell.get_text(strip=True).replace("\xa0", "").strip()
        if bg in UNAMBIGUOUS_TEE_COLORS:
            tee_order.append(bg)
        elif bg == "#ffffff":
            try:
                if int(val) >= 50:
                    tee_order.append(bg)
                else:
                    break
            except ValueError:
                break
        else:
            break

    n_tees = len(tee_order)
    if n_tees == 0:
        return None

    # Offsets (rowspan do separador já colapsado pelo BS4):
    back_start = n_tees + 3  # índice da coluna do buraco da 2ª metade

    tees_data = {bg: {
        "cor": TEE_BGCOLOR_MAP[bg],
        "bgcolor": bg,
        "metros_total": None, "par_total": None,
        "cr_homens": None, "slope_homens": None,
        "cr_senhoras": None, "slope_senhoras": None,
    } for bg in tee_order}

    buracos = []
    any_slope_h = False

    for row in rows[1:]:
        cells = row.find_all("td")
        if not cells or len(cells) <= 2:
            continue
        vals  = [td.get_text(strip=True).replace("\xa0", "").strip() for td in cells]
        first = vals[0]

        # Buraco frente (1-9)
        if re.match(r"^\d{1,2}$", first) and 1 <= int(first) <= 9:
            h_f     = int(first)
            metros_f = {}
            for i, bg in enumerate(tee_order):
                v = vals[1 + i] if 1 + i < len(vals) else ""
                if v.isdigit():
                    metros_f[TEE_BGCOLOR_MAP[bg]] = int(v)
            par_f = int(vals[n_tees + 1]) if n_tees + 1 < len(vals) and vals[n_tees + 1].isdigit() else None
            si_f  = int(vals[n_tees + 2]) if n_tees + 2 < len(vals) and vals[n_tees + 2].isdigit() else None
            buracos.append({"buraco": h_f, "par": par_f, "si": si_f, "metros": metros_f})

            # Buraco trás (10-18) na mesma linha
            if back_start < len(vals):
                h_b_val = vals[back_start]
                if re.match(r"^\d{1,2}$", h_b_val) and 10 <= int(h_b_val) <= 18:
                    h_b      = int(h_b_val)
                    metros_b = {}
                    for i, bg in enumerate(tee_order):
                        idx = back_start + 1 + i
                        v   = vals[idx] if idx < len(vals) else ""
                        if v.isdigit():
                            metros_b[TEE_BGCOLOR_MAP[bg]] = int(v)
                    par_b_idx = back_start + 1 + n_tees
                    si_b_idx  = back_start + 2 + n_tees
                    par_b = int(vals[par_b_idx]) if par_b_idx < len(vals) and vals[par_b_idx].isdigit() else None
                    si_b  = int(vals[si_b_idx])  if si_b_idx  < len(vals) and vals[si_b_idx].isdigit()  else None
                    buracos.append({"buraco": h_b, "par": par_b, "si": si_b, "metros": metros_b})

        # TOT — totais
        elif first.upper() == "TOT":
            for i, bg in enumerate(tee_order):
                idx = back_start + 1 + i
                v   = vals[idx] if idx < len(vals) else ""
                if v.isdigit():
                    tees_data[bg]["metros_total"] = int(v)
            par_idx = back_start + 1 + n_tees
            if par_idx < len(vals) and vals[par_idx].isdigit():
                pv = int(vals[par_idx])
                if 54 <= pv <= 75:
                    for bg in tee_order:
                        tees_data[bg]["par_total"] = pv

        # C.Rat.
        elif "c.rat" in first.lower():
            mode = "s" if "senhor" in row.get_text().lower() else "h"
            for i, bg in enumerate(tee_order):
                v = vals[1 + i] if 1 + i < len(vals) else ""
                try:
                    fv = float(v)
                    if 50 <= fv <= 90:
                        if mode == "h": tees_data[bg]["cr_homens"]   = fv
                        else:           tees_data[bg]["cr_senhoras"]  = fv
                except ValueError:
                    pass

        # Slope
        elif first.lower() == "slope":
            mode = "s" if any_slope_h else "h"
            for i, bg in enumerate(tee_order):
                v = vals[1 + i] if 1 + i < len(vals) else ""
                if v.isdigit():
                    iv = int(v)
                    if 50 <= iv <= 160:
                        if mode == "h": tees_data[bg]["slope_homens"]   = iv
                        else:           tees_data[bg]["slope_senhoras"]  = iv
            if mode == "h":
                any_slope_h = True

    buracos.sort(key=lambda x: x["buraco"])

    return {
        "card_id":    card_id,
        "nome":       nome,
        "arquitecto": arquitecto,
        "tees":       list(tees_data.values()),
        "buracos":    buracos,
    }

# ------------------------------------------------------------
# Scraper de um campo completo (course.asp + show_card.asp)
# ------------------------------------------------------------
def scrape_course(ncourse: str) -> dict | None:
    # 1. Info geral
    url  = f"{BASE_URL}/course.asp?ncourse={ncourse}&ack={ACK}&club={CLUB}"
    html = fetch(url)
    if not html:
        return None

    campo = parse_course(html, ncourse)
    if not campo:
        return None

    # 2. Cartões detectados nos iframes
    for card_id in campo.get("card_ids", []):
        card_url  = f"{BASE_URL}/show_card.asp?ncourse={card_id}&inframe=Y&stat=Y&info=Y&ack={ACK}&club={CLUB}"
        card_html = fetch(card_url)
        if card_html:
            cartao = parse_card(card_html, card_id)
            if cartao:
                campo["cartoes"].append(cartao)

    # 3. Fallback: força bruta se não havia iframes
    if not campo["card_ids"]:
        for i in range(1, MAX_CARDS + 1):
            card_id   = f"{ncourse}-{i}"
            card_url  = f"{BASE_URL}/show_card.asp?ncourse={card_id}&inframe=Y&stat=Y&info=Y&ack={ACK}&club={CLUB}"
            card_html = fetch(card_url)
            if not card_html:
                break
            if "Erro de Parametros" in card_html or "BOF or EOF" in card_html:
                break
            cartao = parse_card(card_html, card_id)
            if cartao:
                campo["cartoes"].append(cartao)

    del campo["card_ids"]
    return campo

# ------------------------------------------------------------
# Main
# ------------------------------------------------------------
def main():
    print(f"\n⛳  Scraper de Campos de Golfe Portugal")
    print(f"   Intervalo: {RANGE_FROM} → {RANGE_TO}")
    print(f"   Concorrência: {CONCURRENCY} | Delay: {DELAY_S}s\n")

    numbers = [str(i).zfill(3) for i in range(RANGE_FROM, RANGE_TO + 1)]
    results = []
    failed  = []

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
                        n_cartoes = len(campo["cartoes"])
                        n_tees    = sum(len(c["tees"]) for c in campo["cartoes"])
                        print(f"  ✓ [{ncourse}] {campo['nome']} — {n_cartoes} cartão(ões), {n_tees} tee(s)")
                    else:
                        print(f"  · [{ncourse}] vazio")
                except Exception as e:
                    print(f"  ✗ [{ncourse}] erro: {e}")
                    failed.append({"ncourse": ncourse, "erro": str(e)})

        if batch_start + CONCURRENCY < len(numbers):
            time.sleep(DELAY_S)

        done = min(batch_start + CONCURRENCY, len(numbers))
        pct  = done / len(numbers) * 100
        print(f"\n  [{done}/{len(numbers)} — {pct:.0f}%] — {len(results)} campos encontrados\n")

    results.sort(key=lambda x: x["id"])

    output = {
        "meta": {
            "fonte":             "scoring-pt.datagolf.pt",
            "total_campos":      len(results),
            "extraido_em":       datetime.utcnow().isoformat() + "Z",
            "range_pesquisado":  f"{RANGE_FROM}-{RANGE_TO}",
            "falhas":            len(failed),
        },
        "campos": results,
    }

    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✅  Concluído!")
    print(f"   Campos encontrados: {len(results)}")
    print(f"   Com cartões:        {sum(1 for c in results if c['cartoes'])}")
    print(f"   Falhas:             {len(failed)}")
    print(f"   Ficheiro gerado:    {OUTPUT}\n")


if __name__ == "__main__":
    main()
