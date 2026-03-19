# ⛳ Campos de Golfe Portugal — Dataset & Ferramentas

Projeto de extração e consulta de todos os campos de golfe nacionais registados na **Federação Portuguesa de Golfe (FPG)**.

---

## 📦 Ficheiros

| Ficheiro | Descrição |
|---|---|
| `campos-golfe-portugal.json` | Dataset completo com todos os campos |
| `scrape-campos-golfe.py` | Script Python para extrair/atualizar o JSON |
| `campos-golfe-portugal.jsx` | App React para consultar cartões de campo |

---

## 📊 Estatísticas do Dataset (extraído em 2026-03-19)

| Métrica | Valor |
|---|---|
| **Total de campos** | 90 |
| **Com cartões de campo** | 89 |
| **Com coordenadas GPS** | 31 |
| **Total de tees registados** | 530 |
| **Total de buracos registados** | 1 044 |
| **Distritos cobertos** | 19 |

### Distribuição por distrito (top 5)
| Distrito | Campos |
|---|---|
| Faro (Algarve) | 33 |
| Lisboa | 15 |
| Setúbal | 8 |
| Porto | 7 |
| Santarém | 3 |

### Tees por cor
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
    "extraido_em": "2026-03-19T16:53:54Z",
    "range_pesquisado": "1-350",
    "falhas": 0
  },
  "campos": [
    {
      "id": 25,
      "codigo": "025",
      "nome": "Estoril - Blue Course",
      "proprietario": "Estoril Plage, S.A.",
      "morada": "Avenida da República",
      "cidade": "Estoril",
      "cod_postal": "2765-273 Estoril",
      "telefone": "214 680 176",
      "fax": null,
      "email": "geral@golfestoril.com",
      "distrito": "Lisboa",
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
              "bgcolor": "#ffff00",
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
              "buraco": 1,
              "par": 4,
              "si": 3,
              "metros": {
                "Branco": 358,
                "Amarelo": 351,
                "Azul": 338,
                "Vermelho": 322,
                "Roxo": 176
              }
            }
          ]
        }
      ],
      "url": "https://scoring-pt.datagolf.pt/scripts/course.asp?ncourse=025&ack=8428ACK987&club=ALL"
    }
  ]
}
```

---

## 🔄 Atualizar o dataset

### Pré-requisitos
```bash
pip install requests beautifulsoup4
```

### Correr o scraper
```bash
python scrape-campos-golfe.py
```

O script itera os códigos `001` a `350`, faz pedidos concorrentes (5 em paralelo com pausa de 300ms entre lotes) e para cada campo:

1. Extrai info geral de `course.asp` — nome, contactos, facilidades, coordenadas GPS
2. Detecta automaticamente os cartões via iframes (`show_card.asp`)
3. Para cada cartão extrai slope, course rating (homens e senhoras), par e metros buraco a buraco

### Parâmetros configuráveis (topo do script)
```python
RANGE_FROM  = 1      # código de campo inicial
RANGE_TO    = 350    # código de campo final (aumentar se necessário)
CONCURRENCY = 5      # pedidos em paralelo
DELAY_S     = 0.3    # pausa entre lotes (segundos)
OUTPUT      = "campos-golfe-portugal.json"
```

> ⚠️ **Nota sobre a chave ACK:** O parâmetro `ack=8428ACK987` foi retirado do URL público da FPG. Se o scraper começar a devolver erros de autenticação, verifica se a chave foi atualizada consultando a página da FPG.

---

## ⚛️ App React (`campos-golfe-portugal.jsx`)

Interface web para consultar os campos com três funcionalidades:

- **Cartão de Campo** — seleciona região e campo, visualiza slope/CR por tee com indicador de dificuldade
- **Lista de Campos** — tabela filtrável por região e pesquisa por nome
- **Handicap de Campo** — calculadora WHS™ com fórmula completa

### Como usar na tua app
```tsx
import data from "./campos-golfe-portugal.json";

const campos = data.campos;

// Aceder ao slope de um tee específico
const campo = campos.find(c => c.codigo === "025");
const cartao = campo.cartoes[1]; // Blue Course completo
const teeAmarelo = cartao.tees.find(t => t.cor === "Amarelo");

console.log(teeAmarelo.slope_homens);  // 113
console.log(teeAmarelo.cr_homens);     // 64.6

// Calcular Handicap de Campo (fórmula WHS™)
function calcCourseHandicap(handicapIndex, slope, cr, par) {
  return Math.round((handicapIndex * slope / 113) + (cr - par));
}
```

---

## 🗺️ Coordenadas GPS

31 dos 90 campos têm coordenadas extraídas do embed Google Maps presente na página da FPG. Os restantes 59 podem ser geocodificados usando a API gratuita do **Nominatim (OpenStreetMap)**:

```python
import requests, time

def geocode(nome, cidade):
    r = requests.get("https://nominatim.openstreetmap.org/search", params={
        "q": f"{nome} golf {cidade} Portugal",
        "format": "json", "limit": 1
    }, headers={"User-Agent": "GolfPT/1.0"})
    results = r.json()
    if results:
        return float(results[0]["lat"]), float(results[0]["lon"])
    return None, None

# Usar com delay para respeitar rate limit do Nominatim (1 req/s)
lat, lon = geocode("Estoril Golf", "Estoril")
time.sleep(1)
```

---

## 📝 Notas técnicas

### Encoding
O servidor `scoring-pt.datagolf.pt` serve UTF-8 real, mas alguns campos do primeiro scrape foram lidos com `latin-1` por engano, resultando em acentos corrompidos (ex: `ProprietÃ¡rio`). O scraper atual usa `r.encoding = "utf-8"` explicitamente para garantir leitura correta.

### Múltiplos cartões
Alguns campos têm mais do que um cartão (até 4), normalmente correspondendo a:
- Diferentes layouts (ex: 9 buracos frente / 9 buracos trás separados)
- Versões masculina e feminina com tees distintos
- Campo com 27 buracos organizado em combinações de 9

### Campos sem cartão
1 campo (`id=1`, Sports Clube da Penha Longa) não tem cartão acessível — a página existe mas não contém iframes com show_card.

### Fonte dos dados
Todos os dados são propriedade da **Federação Portuguesa de Golfe** e do sistema **DataGolf**. Este dataset destina-se a uso pessoal e desenvolvimento. Para uso comercial, consulta a FPG.

---

## 🔗 Links úteis

- [Portal FPG](https://portal.fpg.pt)
- [Campos Nacionais FPG](https://portal.fpg.pt/campos/listagem-campos-nacionais-golfe/)
- [Campos Classificados WHS™](https://portal.fpg.pt/handicaps-course-rating/campos-classificados-whs/)
- [Cálculo de Handicap de Campo](https://portal.fpg.pt/handicaps-course-rating/calculo-de-handicap-de-campo/)
- [Sistema WHS™](https://www.whs.com)
