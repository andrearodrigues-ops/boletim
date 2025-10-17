# Monitor de Boletins Epidemiológicos – Automação com GitHub Actions

Este projeto monitora automaticamente a página de boletins epidemiológicos do Ministério da Saúde e envia resumos com IA por e-mail (e opcionalmente WhatsApp).

## 💡 Como funciona
1. O robô acessa a página oficial do MS:
   https://www.gov.br/saude/pt-br/centrais-de-conteudo/publicacoes/boletins/epidemiologicos/ultimos
2. Detecta novos boletins.
3. Extrai texto do PDF (quando disponível).
4. Gera resumo com IA.
5. Envia resumo por **e-mail** (SendGrid) e/ou **WhatsApp** (Cloud API).

## 🧠 O que você precisa fazer

### 1️⃣ Criar um repositório no GitHub
- Vá para https://github.com/new e crie um repositório (público ou privado).
- Faça upload de todos os arquivos deste `.zip`.

### 2️⃣ Criar *Secrets* no GitHub
No seu repositório:
> Settings → Secrets and variables → Actions → New repository secret

Adicione:

- `SENDGRID_API_KEY`
- `REPORT_TO_EMAIL`
- `REPORT_FROM_EMAIL`
- *(Opcional)* `OPENAI_API_KEY` (para resumos com IA)
- *(Opcional)* `WPP_TOKEN`, `WPP_PHONE_ID`, `REPORT_TO_WPP`, `WPP_TEMPLATE_NAME`, `WPP_TEMPLATE_LANG` (para WhatsApp)

### 3️⃣ Ajustar horário de execução
O arquivo `.github/workflows/monitor.yml` executa o robô **2× por dia** (03:00 e 15:00 UTC, ou seja, 00:00 e 12:00 no Brasil).
Você pode editar o `cron:` dentro dele, por exemplo:
```
0 11,23 * * *   # 08:00 e 20:00 (horário de Brasília)
```

### 4️⃣ Testar manualmente
- Vá até a aba **Actions** no seu repositório.
- Clique em **Monitor MS Boletins → Run workflow**.

Se houver boletim novo, você receberá um e-mail com o resumo.

---

## ⚙️ Personalizações
- **E-mail template:** `templates/email.html.j2`
- **Prompt de resumo IA:** função `summarize()` em `app.py`
- **Número de boletins checados:** variável `CHECK_LIMIT` no workflow

---

📅 Gerado automaticamente em 17/10/2025.
