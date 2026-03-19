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

# Mapeamento de bgcolor para nome do tee
TEE_COLORS = {
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

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; GolfPT-Scraper/1.0)"
})

# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------
def get(url: str) -> str | None:
    try:
        r = SESSION.get(url, timeout=TIMEOUT)
        # O servidor serve UTF-8 real apesar do Content-Type inconsistente
        r.encoding = "utf-8"
        return r.text
    except Exception:
        return None

def fix_encoding(text: str | None) -> str | None:
    """Corrige texto que foi lido como latin-1 mas é UTF-8."""
    if not text:
        return text
    try:
        return text.encode("latin-1").decode("utf-8")
    except Exception:
        return text

def clean(text: str | None) -> str | None:
    if not text:
        return None
    text = text.replace("\xa0", "").replace("&nbsp;", "").strip()
    return text or None

def normalize_color(bgcolor: str | None) -> str | None:
    if not bgcolor:
        return None
    c = bgcolor.strip().lower()
    if not c.startswith("#"):
        c = "#" + c
    return TEE_COLORS.get(c, c)

# ------------------------------------------------------------
# Parse course.asp  →  info geral + iframes + GPS
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
        "card_ids": card_ids,   # temporário, removido no output final
        "cartoes": [],
        "url": f"{BASE_URL}/course.asp?ncourse={ncourse}&ack={ACK}&club={CLUB}",
    }

# ------------------------------------------------------------
# Parse show_card.asp  →  cartão completo com tees, buracos, slope/CR
# ------------------------------------------------------------
def parse_card(html: str, card_id: str) -> dict | None:
    """
    Extrai de show_card.asp:
      - nome do cartão
      - tees (cor, metros total, par, CR homens, slope homens, CR senhoras, slope senhoras)
      - buracos (metros por tee, par, stroke index)
      - arquitecto
    """
    if not html or len(html) < 300:
        return None
    if "Erro de Parametros" in html or "BOF or EOF" in html:
        return None

    soup = BeautifulSoup(html, "html.parser")

    # Nome do cartão — <b> no início
    nome_cartao = None
    b = soup.find("b")
    if b:
        nome_cartao = clean(b.get_text())

    # Arquitecto
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

    # Tabela principal — a maior tabela com buracos
    main_table = None
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        # A tabela certa tem linha com "Hole" no cabeçalho
        header_text = rows[0].get_text() if rows else ""
        if "hole" in header_text.lower() and "par" in header_text.lower():
            main_table = table
            break

    if not main_table:
        return None

    rows = main_table.find_all("tr")

    # Detectar quais bgcolors estão presentes (= quais tees existem)
    # Percorrer todas as células com bgcolor para descobrir a ordem dos tees
    tee_order = []
    seen_colors = set()
    for row in rows:
        for td in row.find_all("td", bgcolor=True):
            bg = td.get("bgcolor", "").strip().lower()
            if not bg.startswith("#"):
                bg = "#" + bg
            if bg in TEE_COLORS and bg not in seen_colors and bg != "#e9e9e9":
                seen_colors.add(bg)
                tee_order.append(bg)
        if tee_order:
            break  # já temos a ordem da primeira linha de dados

    n_tees = len(tee_order)
    if n_tees == 0:
        return None

    # Inicializar estrutura de tees
    tees_data = {
        bg: {
            "cor": normalize_color(bg),
            "bgcolor": bg,
            "metros_total": None,
            "par_total": None,
            "cr_homens": None,
            "slope_homens": None,
            "cr_senhoras": None,
            "slope_senhoras": None,
        }
        for bg in tee_order
    }

    # Buracos: lista de 18 (ou 9) entradas
    buracos = []

    # Percorrer linhas para extrair dados
    # Estrutura das linhas:
    #   linhas 1-9  : buraco 1-9 (OUT) + buraco 10-18 (IN) em paralelo
    #   linha OUT   : subtotais frente
    #   linha IN    : subtotais trás (repetição)
    #   linha C.Rat (Homens)
    #   linha Slope (Homens)
    #   linha TOT   : totais
    #   linha C.Rat (Senhoras)
    #   linha Slope (Senhoras)

    current_mode = "holes"  # holes | cr_h | slope_h | cr_s | slope_s

    for row in rows[1:]:  # skip header
        tds = row.find_all("td")
        if not tds:
            continue

        first_cell = clean(tds[0].get_text()) or ""

        # Detectar tipo de linha pelo primeiro td
        if first_cell.upper() in ("OUT", "IN", "TOT"):
            if first_cell.upper() == "TOT":
                # Linha de totais: extrair metros e par total por tee
                colored = [td for td in tds if td.get("bgcolor", "").lower().strip("#") and
                           "#" + td.get("bgcolor", "").lower().strip("#") in tee_order]
                for i, bg in enumerate(tee_order):
                    matching = [td for td in tds if td.get("bgcolor", "").lower() == bg.strip("#") or
                                "#" + td.get("bgcolor", "").lower().strip("#") == bg]
                    if matching:
                        val = clean(matching[0].get_text())
                        if val and val.isdigit():
                            tees_data[bg]["metros_total"] = int(val)
                # Par total está numa td bgcolor="#FFFFFF" após os tees
                par_td = None
                for td in reversed(tds):
                    val = clean(td.get_text())
                    if val and val.isdigit() and 54 <= int(val) <= 75:
                        par_td = int(val)
                        break
                # Distribuir par_total para todos os tees (é igual para todos)
                if par_td:
                    for bg in tee_order:
                        tees_data[bg]["par_total"] = par_td
            continue

        if "c.rat" in first_cell.lower() or "course rat" in first_cell.lower():
            # Verificar se é Homens ou Senhoras pelo texto da linha
            row_text = row.get_text()
            if "senhor" in row_text.lower():
                current_mode = "cr_s"
            else:
                current_mode = "cr_h"
            # Extrair valores por tee
            for bg in tee_order:
                matching = [td for td in tds
                            if ("#" + td.get("bgcolor", "").lower().strip("#")) == bg
                            or td.get("bgcolor", "").lower() == bg.strip("#")]
                if matching:
                    val = clean(matching[0].get_text())
                    if val:
                        try:
                            fval = float(val)
                            if current_mode == "cr_h":
                                tees_data[bg]["cr_homens"] = fval
                            else:
                                tees_data[bg]["cr_senhoras"] = fval
                        except ValueError:
                            pass
            continue

        if "slope" in first_cell.lower():
            if current_mode in ("cr_h",):
                current_mode = "slope_h"
            elif current_mode in ("cr_s",):
                current_mode = "slope_s"
            else:
                # Determinar pelo contexto: slope depois de cr_h ou cr_s
                # Se já temos slope_h, é slope_s
                any_slope_h = any(v["slope_homens"] for v in tees_data.values())
                current_mode = "slope_s" if any_slope_h else "slope_h"

            for bg in tee_order:
                matching = [td for td in tds
                            if ("#" + td.get("bgcolor", "").lower().strip("#")) == bg
                            or td.get("bgcolor", "").lower() == bg.strip("#")]
                if matching:
                    val = clean(matching[0].get_text())
                    if val and val.isdigit():
                        ival = int(val)
                        if 50 <= ival <= 160:
                            if current_mode == "slope_h":
                                tees_data[bg]["slope_homens"] = ival
                            else:
                                tees_data[bg]["slope_senhoras"] = ival
            continue

        # Linha de buraco: primeiro td é número do buraco
        if re.match(r"^\d{1,2}$", first_cell):
            hole_num = int(first_cell)
            if 1 <= hole_num <= 18:
                # Coletar metros por tee
                metros = {}
                for bg in tee_order:
                    matching = [td for td in tds
                                if ("#" + td.get("bgcolor", "").lower().strip("#")) == bg
                                or td.get("bgcolor", "").lower() == bg.strip("#")]
                    if matching:
                        val = clean(matching[0].get_text())
                        if val and val.isdigit():
                            metros[normalize_color(bg)] = int(val)

                # Par e S.I.: últimas 2 células com bgcolor #FFFFFF não-tee
                par_hole = si_hole = None
                white_tds = [td for td in tds
                             if td.get("bgcolor", "").lower() in ("#ffffff", "ffffff", "white", "#FFFFFF")
                             and not any(td.get("bgcolor", "").lower() == bg.strip("#") for bg in tee_order)]
                # Fallback: últimas 2 células da primeira metade da linha
                # A estrutura da linha tem 2 metades (frente + trás) separadas por td vazio
                # Tentamos pegar o par e SI da parte mais próxima do número do buraco
                for td in tds:
                    val = clean(td.get_text())
                    if val and val.isdigit():
                        ival = int(val)
                        if 3 <= ival <= 6 and par_hole is None:
                            par_hole = ival
                        elif 1 <= ival <= 18 and si_hole is None and td != tds[0]:
                            si_hole = ival

                buracos.append({
                    "buraco": hole_num,
                    "par": par_hole,
                    "si": si_hole,
                    "metros": metros,
                })

    # Limpar card_ids temporário e montar output
    tees_list = [v for v in tees_data.values()]

    return {
        "card_id": card_id,
        "nome": nome_cartao,
        "arquitecto": arquitecto,
        "tees": tees_list,
        "buracos": sorted(buracos, key=lambda x: x["buraco"]),
    }

# ------------------------------------------------------------
# Scraper principal
# ------------------------------------------------------------
def scrape_course(ncourse: str) -> dict | None:
    # 1. Buscar info geral
    url = f"{BASE_URL}/course.asp?ncourse={ncourse}&ack={ACK}&club={CLUB}"
    html = get(url)
    if not html:
        return None

    campo = parse_course(html, ncourse)
    if not campo:
        return None

    # 2. Buscar cada cartão encontrado nos iframes
    for card_id in campo.get("card_ids", []):
        card_url = f"{BASE_URL}/show_card.asp?ncourse={card_id}&inframe=Y&stat=Y&info=Y&ack={ACK}&club={CLUB}"
        card_html = get(card_url)
        if card_html:
            cartao = parse_card(card_html, card_id)
            if cartao:
                campo["cartoes"].append(cartao)

    # Se não havia iframes, tentar descobrir cartões por força bruta (até MAX_CARDS)
    if not campo["card_ids"]:
        for i in range(1, MAX_CARDS + 1):
            card_id = f"{ncourse}-{i}"
            card_url = f"{BASE_URL}/show_card.asp?ncourse={card_id}&inframe=Y&stat=Y&info=Y&ack={ACK}&club={CLUB}"
            card_html = get(card_url)
            if not card_html:
                break
            if "Erro de Parametros" in card_html or "BOF or EOF" in card_html:
                break
            cartao = parse_card(card_html, card_id)
            if cartao:
                campo["cartoes"].append(cartao)

    # Remover campo temporário
    del campo["card_ids"]

    return campo


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
                        n_tees = sum(len(c["tees"]) for c in campo["cartoes"])
                        print(f"  ✓ [{ncourse}] {campo['nome']} — {n_cartoes} cartão(ões), {n_tees} tee(s)")
                    else:
                        print(f"  · [{ncourse}] vazio")
                except Exception as e:
                    print(f"  ✗ [{ncourse}] erro: {e}")
                    failed.append({"ncourse": ncourse, "erro": str(e)})

        if batch_start + CONCURRENCY < len(numbers):
            time.sleep(DELAY_S)

        done = min(batch_start + CONCURRENCY, len(numbers))
        pct = done / len(numbers) * 100
        print(f"\n  [{done}/{len(numbers)} — {pct:.0f}%] — {len(results)} campos encontrados\n")

    results.sort(key=lambda x: x["id"])

    output = {
        "meta": {
            "fonte": "scoring-pt.datagolf.pt",
            "total_campos": len(results),
            "extraido_em": datetime.utcnow().isoformat() + "Z",
            "range_pesquisado": f"{RANGE_FROM}-{RANGE_TO}",
            "falhas": len(failed),
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
