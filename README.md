# ⛳ Campos de Golfe Portugal

Dataset completo e interface web dos campos de golfe nacionais registados na **Federação Portuguesa de Golfe (FPG)**.

---

## 📦 Ficheiros

| Ficheiro | Tamanho | Descrição |
|---|---|---|
| `index.html` | ~1 MB | App web — duplo clique para abrir, zero instalação |
| `stats.html` | ~15 KB | Dashboard de estatísticas de utilização |
| `campos-golfe-portugal.json` | ~576 KB | Dataset completo em JSON |
| `scrape-campos-golfe.py` | ~19 KB | Script Python para extrair/atualizar o dataset |

> O `index.html` tem as imagens e o JSON **embutidos** — funciona como ficheiro único, sem dependências externas.

---

## 🚀 Como usar

**Abrir a app:** duplo clique em `index.html` — abre directamente no browser.

**Ver estatísticas:** abrir `stats.html` **no mesmo browser** onde se usa o `index.html`. Os dados são guardados em `localStorage`.

**Atualizar o dataset:**
```bash
pip install requests beautifulsoup4
python scrape-campos-golfe.py
```
Após correr o scraper, é necessário regenerar o `index.html` com o novo JSON (ver secção abaixo).

---

## 📊 Dataset — Estatísticas

| Métrica | Valor |
|---|---|
| **Total de campos** | 90 |
| **Com cartões completos** | 89 |
| **Com coordenadas GPS** | 31 |
| **Total de tees registados** | 530 |
| **Total de buracos registados** | 1 044 |
| **Distritos cobertos** | 19 |
| **Extraído em** | 2026-03-19 |

### Distribuição por distrito (top 5)
| Distrito | Campos |
|---|---|
| Faro (Algarve) | 33 |
| Lisboa | 15 |
| Setúbal | 8 |
| Porto | 7 |
| Santarém | 3 |

### Tees registados por cor
| Cor | Ocorrências |
|---|---|
| ⬜ Branco | 116 |
| 🟡 Amarelo | 108 |
| 🔴 Vermelho | 107 |
| 🔵 Azul | 61 |
| 🟣 Roxo | 58 |
| 🟢 Verde | 57 |
| ⚫ Preto | 23 |

---

## 🗂️ Estrutura do JSON

```json
{
  "meta": {
    "fonte": "scoring-pt.datagolf.pt",
    "total_campos": 90,
    "extraido_em": "2026-03-19T16:53:54Z"
  },
  "campos": [
    {
      "id": 25,
      "codigo": "025",
      "nome": "Estoril - Blue Course",
      "cidade": "Estoril",
      "distrito": "Lisboa",
      "telefone": "214 680 176",
      "email": "geral@golfestoril.com",
      "website": "www.palacioestorilhotel.com",
      "data_abertura": "1/1/1929",
      "profissional": "Miguel Nunes Pedro, ...",
      "coordenadas": { "lat": 38.72168, "lon": -9.396744 },
      "facilidades": ["Driving Range", "Putting Green", "Hotel", "..."],
      "cartoes": [
        {
          "card_id": "025-2",
          "nome": "Estoril Blue Course",
          "arquitecto": "Mackenzie Ross",
          "tees": [
            {
              "cor": "Amarelo",
              "metros_total": 4662,
              "par_total": 68,
              "cr_homens": 64.6,
              "slope_homens": 113,
              "cr_senhoras": 69.8,
              "slope_senhoras": 117
            }
          ],
          "buracos": [
            {
              "buraco": 1, "par": 4, "si": 3,
              "metros": { "Branco": 358, "Amarelo": 351, "Azul": 338 }
            }
          ]
        }
      ]
    }
  ]
}
```

---

## 🔄 Atualizar o dataset e regenerar o index.html

### 1. Correr o scraper
```bash
pip install requests beautifulsoup4
python scrape-campos-golfe.py
# → gera campos-golfe-portugal.json actualizado
```

### 2. Regenerar o index.html
O `index.html` tem o JSON embutido em base64. Para o actualizar com novos dados, é necessário re-executar o script de geração do HTML (disponível no repositório do projecto) ou substituir manualmente o array `CAMPOS` no início do bloco `<script>`.

### Parâmetros do scraper
```python
RANGE_FROM  = 1      # código de campo inicial
RANGE_TO    = 350    # código de campo final
CONCURRENCY = 5      # pedidos em paralelo
DELAY_S     = 0.3    # pausa entre lotes (segundos)
OUTPUT      = "campos-golfe-portugal.json"
```

> ⚠️ **Nota sobre a chave ACK:** O parâmetro `ack=8428ACK987` foi retirado do URL público da FPG. Se o scraper começar a devolver erros, verifica se a chave foi actualizada na página da FPG.

---

## 📈 Estatísticas de utilização (`stats.html`)

O `index.html` regista automaticamente em `localStorage`:

| Dado | Detalhe |
|---|---|
| Acessos | Total de pageviews com data/hora |
| Browser & OS | Chrome, Firefox, Edge, Safari · Windows, macOS, iOS, Android |
| Dispositivo | Mobile, Tablet, Desktop |
| Idioma | Locale do browser |
| Campos consultados | Ranking dos campos mais vistos |
| Pesquisas | Termos mais pesquisados |
| Filtros usados | Distritos e facilidades mais filtradas |
| Handicaps calculados | Contador total |

O dashboard (`stats.html`) tem exportação para **JSON** e **CSV** e auto-actualiza a cada 5 segundos.

> Os dados ficam guardados apenas no browser onde a app é utilizada. Para estatísticas multi-utilizador seria necessário um servidor.

---

## 🔗 Links úteis

- [Portal FPG](https://portal.fpg.pt)
- [Campos Nacionais FPG](https://portal.fpg.pt/campos/listagem-campos-nacionais-golfe/)
- [Campos Classificados WHS™](https://portal.fpg.pt/handicaps-course-rating/campos-classificados-whs/)
- [Cálculo de Handicap de Campo](https://portal.fpg.pt/handicaps-course-rating/calculo-de-handicap-de-campo/)
- [Sistema WHS™](https://www.whs.com)

---

## 📝 Notas técnicas

**Fonte dos dados:** `scoring-pt.datagolf.pt` — sistema DataGolf da FPG. Todos os dados são propriedade da Federação Portuguesa de Golfe. Este dataset destina-se a uso pessoal e desenvolvimento.

**Encoding:** O servidor serve UTF-8 mas declara latin-1 no Content-Type. O scraper força `r.encoding = "utf-8"` para leitura correcta.

**Múltiplos cartões:** Alguns campos têm até 4 cartões (layouts de 9 buracos separados, combinações de 27 buracos, etc.).

**GPS:** 31 campos têm coordenadas extraídas do embed Google Maps. Os restantes 59 podem ser geocodificados via Nominatim/OpenStreetMap.
