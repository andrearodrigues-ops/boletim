import os, re, io, hashlib, sqlite3, requests, logging
from bs4 import BeautifulSoup
from datetime import datetime, timezone
from jinja2 import Template

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

MS_URL = os.getenv("MS_URL")
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
REPORT_TO_EMAIL = os.getenv("REPORT_TO_EMAIL")
REPORT_FROM_EMAIL = os.getenv("REPORT_FROM_EMAIL", "noreply@domain.com")
CHECK_LIMIT = int(os.getenv("CHECK_LIMIT", "20"))

def fetch_list():
    html = requests.get(MS_URL, timeout=30).text
    soup = BeautifulSoup(html, "html.parser")
    boletins = []
    for h2 in soup.select("h2")[:CHECK_LIMIT]:
        a = h2.find("a")
        if not a: continue
        titulo = a.get_text(strip=True)
        url = a["href"]
        boletins.append((titulo, url))
    return boletins

def send_email(subject, body):
    if not SENDGRID_API_KEY or not REPORT_TO_EMAIL:
        logging.warning("Chave SendGrid ou e-mail ausente.")
        return
    r = requests.post("https://api.sendgrid.com/v3/mail/send",
        headers={"Authorization": f"Bearer {SENDGRID_API_KEY}", "Content-Type": "application/json"},
        json={
            "personalizations": [{"to": [{"email": REPORT_TO_EMAIL}]}],
            "from": {"email": REPORT_FROM_EMAIL},
            "subject": subject,
            "content": [{"type": "text/html", "value": body}]
        })
    if r.status_code >= 300:
        logging.error("Erro ao enviar e-mail: %s", r.text)
    else:
        logging.info("E-mail enviado com sucesso.")

def main():
    boletins = fetch_list()
    if not boletins:
        logging.info("Nenhum boletim encontrado.")
        return
    titulo, link = boletins[0]
    corpo = f"<h2>Novo boletim detectado</h2><p>{titulo}</p><p><a href='{link}'>Acessar</a></p>"
    send_email(f"[MS] {titulo}", corpo)

if __name__ == "__main__":
    main()
