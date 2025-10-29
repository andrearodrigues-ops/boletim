import os, re, io, hashlib, sqlite3, logging, requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone
from jinja2 import Template

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

MS_URL = os.getenv("MS_URL", "https://www.gov.br/saude/pt-br/centrais-de-conteudo/publicacoes/boletins/epidemiologicos/ultimos")
DB_PATH = os.getenv("DB_PATH", "boletins.db")
CHECK_LIMIT = int(os.getenv("CHECK_LIMIT", "20"))

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "NONE").upper()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY", "")
REPORT_TO_EMAIL = os.getenv("REPORT_TO_EMAIL", "")
REPORT_FROM_EMAIL = os.getenv("REPORT_FROM_EMAIL", "noreply@domain.com")

def db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS boletins(
        id TEXT PRIMARY KEY,
        titulo TEXT,
        url TEXT,
        publicado_em TEXT,
        sha TEXT,
        inserido_em TEXT
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS envios(
        id TEXT PRIMARY KEY,
        boletim_id TEXT,
        canal TEXT,
        status TEXT,
        criado_em TEXT
    )""")
    conn.commit()
    return conn, cur

def fetch_list():
    logging.info("Baixando lista: %s", MS_URL)
    html = requests.get(MS_URL, timeout=30).text
    soup = BeautifulSoup(html, "html.parser")
    cards = []
    for h2 in soup.select("h2")[:CHECK_LIMIT]:
        a = h2.find("a")
        if not a:
            continue
        titulo = h2.get_text(strip=True)
        url = a["href"]
        # tenta achar “publicado DD/MM/AAAA HHhMM” no bloco seguinte
        bloco = ""
        sib = h2.find_next()
        if sib:
            bloco = sib.get_text(" ", strip=True)
        m = re.search(r"publicado\s+(\d{2}/\d{2}/\d{4})\s+(\d{2}h\d{2})", bloco)
        publicado_em = None
        if m:
            dt = datetime.strptime(m.group(1)+" "+m.group(2).replace("h", ":"), "%d/%m/%Y %H:%M")
            publicado_em = dt.isoformat()
        cards.append({"titulo": titulo, "url": url, "publicado_em": publicado_em})
    logging.info("Itens encontrados: %d", len(cards))
    return cards

def is_new(cur, item):
    sha = hashlib.sha256((item["titulo"] + item["url"]).encode()).hexdigest()
    item["sha"] = sha
    cur.execute("SELECT 1 FROM boletins WHERE id=?", (sha,))
    return cur.fetchone() is None

def save_item(conn, cur, item):
    cur.execute("INSERT OR IGNORE INTO boletins VALUES (?,?,?,?,?,?)", (
        item["sha"], item["titulo"], item["url"], item["publicado_em"], item["sha"],
        datetime.now(timezone.utc).isoformat()
    ))
    conn.commit()

def find_pdf_and_text(page_url, max_pages=6):
    logging.info("Abrindo página do boletim: %s", page_url)
    html = requests.get(page_url, timeout=60).text
    soup = BeautifulSoup(html, "html.parser")
    pdf_link = None
    for a in soup.select("a"):
        href = a.get("href", "")
        if href.lower().endswith(".pdf") or a.get_text(strip=True).lower() == "arquivo":
            pdf_link = href if href.startswith("http") else "https://www.gov.br" + href
            break
    text = None
    if pdf_link:
        logging.info("Baixando PDF: %s", pdf_link)
        pdf_bytes = requests.get(pdf_link, timeout=120).content
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(pdf_bytes))
            chunks = []
            for page in reader.pages[:max_pages]:
                chunks.append(page.extract_text() or "")
            text = "\n".join(chunks)
        except Exception as e:
            logging.warning("Falha ao extrair texto do PDF: %s", e)
    return pdf_link, text

def summarize(title, text):
    if not text:
        return f"{title}: resumo indisponível (PDF sem texto extraível ou ausente)."
    prompt = f'''
Você é editor científico para médicos e gestores do SUS. Resuma o boletim em até 8 bullets, com:
(1) tema/escopo; (2) período e fonte dos dados; (3) 3–5 achados quantitativos;
(4) recomendações/implicações assistenciais e de vigilância; (5) limitações;
(6) o que acompanhar nas próximas semanas.
Use números e taxas quando existirem. Evite jargão.
Título: {title}
Texto:
{text[:10000]}
'''
    if LLM_PROVIDER == "OPENAI" and OPENAI_API_KEY:
        try:
            url = "https://api.openai.com/v1/chat/completions"
            headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
            payload = {
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
                "max_tokens": 500
            }
            resp = requests.post(url, headers=headers, json=payload, timeout=90)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()
        except Exception as e:
            logging.warning("Falha na chamada OpenAI, usando fallback: %s", e)
    # Fallback
    return (prompt[:1500] + "...")

def render_email(titulo, publicado_em, link_pdf, link_page, resumo):
    def render_email_batch(itens):
    """
    itens: lista de dicts com chaves:
      - titulo, publicado_em, link_pdf, link_page, resumo
    Gera um único HTML com índice + seções.
    """
    # HTML minimalista (se quiser, pode migrar para Jinja depois)
    parts = []
    # Índice
    toc = ["<ol>"]
    for i, it in enumerate(itens, start=1):
        anchor = f"sec{i}"
        toc.append(f'<li><a href="#{anchor}">{it["titulo"]}</a></li>')
    toc.append("</ol>")
    parts.append("<h1>Boletins Epidemiológicos – Resumo</h1>")
    parts.append(f"<p>Novidades nesta execução: <b>{len(itens)}</b></p>")
    parts.append("\n".join(toc))

    # Seções
    for i, it in enumerate(itens, start=1):
        anchor = f"sec{i}"
        link = it["link_pdf"] or it["link_page"]
        parts.append(f'''
        <hr/>
        <h2 id="{anchor}">{it["titulo"]}</h2>
        <p style="color:#6b7280;font-size:12px">
          Publicado em: {it.get("publicado_em") or "—"} ·
          <a href="{link}" target="_blank" rel="noopener">Documento</a>
        </p>
        <pre style="white-space:pre-wrap;font:14px/1.5 system-ui">{it["resumo"]}</pre>
        <p><a href="{link}" target="_blank" rel="noopener" 
              style="display:inline-block;padding:10px 16px;border-radius:10px;background:#111827;color:#fff;text-decoration:none">
              Abrir documento
           </a></p>
        ''')
    parts.append('<p style="color:#6b7280;font-size:12px">Resumo automatizado para fins informativos. Consulte sempre o documento oficial.</p>')
    return "\n".join(parts)

    # carrega template do repositório
    tpl_path = os.path.join("templates", "email.html.j2")
    if os.path.exists(tpl_path):
        with open(tpl_path, "r", encoding="utf-8") as f:
            tpl = Template(f.read())
        return tpl.render(titulo=titulo, publicado_em=publicado_em, link_pdf=link_pdf, link_page=link_page, resumo=resumo)
    # fallback simples
    safe_link = link_pdf or link_page
    return f"<h2>{titulo}</h2><p><a href='{safe_link}'>Documento</a></p><pre>{resumo}</pre>"

def send_email(subject, html_body):
    if not SENDGRID_API_KEY or not REPORT_TO_EMAIL:
        logging.info("SENDGRID_API_KEY/REPORT_TO_EMAIL ausentes. Pulando envio de e-mail.")
        return "skipped"
    resp = requests.post(
        "https://api.sendgrid.com/v3/mail/send",
        headers={"Authorization": f"Bearer {SENDGRID_API_KEY}", "Content-Type": "application/json"},
        json={
            "personalizations": [{"to": [{"email": REPORT_TO_EMAIL}]}],
            "from": {"email": REPORT_FROM_EMAIL},
            "subject": subject,
            "content": [{"type": "text/html", "value": html_body}]
        },
        timeout=60
    )
    if resp.status_code >= 300:
        logging.error("Erro SendGrid: %s %s", resp.status_code, resp.text)
        return "error"
    return "sent"

def log_envio(conn, cur, boletim_id, canal, status):
    cur.execute("INSERT OR REPLACE INTO envios VALUES (?,?,?,?,?)", (
        hashlib.sha256(f"{boletim_id}-{canal}".encode()).hexdigest(),
        boletim_id, canal, status, datetime.now(timezone.utc).isoformat()
    ))
    conn.commit()

def main():
    conn, cur = db()

    # 1) Detectar novidades
    novos = []
    for item in fetch_list():
        if is_new(cur, item):
            novos.append(item)

    if not novos:
        logging.info("Nenhuma novidade. Nada será enviado.")
        return

    logging.info("Novos boletins detectados: %d", len(novos))

    # 2) Persistir no banco (para não repetir no próximo run)
    for item in novos:
        save_item(conn, cur, item)

    # 3) Enriquecer + Resumir (cada um)
    lote = []
    for item in novos:
        pdf_link, text = find_pdf_and_text(item["url"])
        resumo = summarize(item["titulo"], text)
        lote.append({
            "titulo": item["titulo"],
            "publicado_em": item.get("publicado_em"),
            "link_pdf": pdf_link,
            "link_page": item["url"],
            "resumo": resumo,
        })

    # 4) Montar um único e-mail com tudo
    html_body = render_email_batch(lote)

    # 5) Assunto amigável (contagem + data)
    hoje = datetime.now(timezone.utc).strftime("%d/%m/%Y")
    subject = f"[MS] {len(lote)} boletim(ns) novo(s) – {hoje}"

    # 6) Enviar 1 e-mail
    status = send_email(subject=subject, html_body=html_body)
    logging.info("Envio consolidado: %s", status)



if __name__ == "__main__":
    main()
