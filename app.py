import io
import re
import unicodedata
from urllib.parse import quote_plus

import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup
from zeep import Client
from zeep.exceptions import Fault, TransportError

st.set_page_config(page_title="Localizador de Acervos", page_icon="📚", layout="wide")

SOURCES = {
    "UFSC — Pergamum": "https://pergamum.ufsc.br",
    "UDESC — Pergamum": "https://pergamumweb.udesc.br",
    "BNDigital": "https://bndigital.bn.gov.br",
    "National Library of Korea": "https://www.nl.go.kr/EN/main/index.do",
}

DEFAULT_TITLES = """Dom Casmurro
Mulherzinhas
As veias abertas da América Latina"""

def norm(text):
    text = str(text or "").strip().lower()
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c))

def clean(value):
    if value is None:
        return ""
    value = BeautifulSoup(str(value), "html.parser").get_text(" ", strip=True)
    return re.sub(r"\s+", " ", value).strip()

def result_row(query, source, status, title="", author="", year="", isbn="", classification="", link="", note=""):
    return {
        "Título pesquisado": query,
        "Acervo": source,
        "Resultado": status,
        "Título encontrado": title,
        "Autor": author,
        "Ano": year,
        "ISBN": isbn,
        "Classificação": classification,
        "Link": link,
        "Observação": note,
    }

def classify_title_match(query, title):
    q, t = norm(query), norm(title)
    if not q or not t:
        return False
    if q == t:
        return True
    if q in t or t in q:
        return True
    q_words = {w for w in re.findall(r"\w+", q) if len(w) > 2}
    t_words = {w for w in re.findall(r"\w+", t) if len(w) > 2}
    if not q_words:
        return False
    return len(q_words & t_words) / len(q_words) >= 0.75

def parse_html_records(raw, query, base_url):
    soup = BeautifulSoup(raw, "html.parser")
    text = clean(soup.get_text(" ", strip=True))
    if not text:
        return []
    records = []
    # Pergamum installations vary in markup. We look for links to /acervo/<id>
    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        if "/acervo/" not in href:
            continue
        title = clean(a.get_text(" ", strip=True))
        if not title:
            continue
        link = href if href.startswith("http") else base_url.rstrip("/") + "/" + href.lstrip("/")
        records.append({
            "title": title,
            "author": "",
            "year": "",
            "isbn": "",
            "classification": "",
            "link": link,
        })
    # Deduplicate
    out, seen = [], set()
    for r in records:
        key = (norm(r["title"]), r["link"])
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out[:20]

def pergamum_search(source, base_url, query):
    """
    Uses the public Pergamum SOAP service when available.
    We deliberately do not convert connection/parsing failures into "Não encontrado".
    """
    wsdl = base_url.rstrip("/") + "/pergamum/web_service/servidor_ws.php?WSDL"
    client = Client(wsdl=wsdl)

    # Public Pergamum installations expose ws_consultas with these fields.
    # "TITULO" is the catalog title field in common Pergamum deployments.
    params = {
        "coluna1": "TITULO",
        "ordenacao": "TITULO",
        "data_ini": 0,
        "biblioteca": "",
        "tipo_obra": "",
        "termo1": query,
        "colecao": "",
    }

    try:
        response = client.service.ws_consultas(**params)
    except TypeError:
        # Some installations are stricter about positional RPC arguments.
        response = client.service.ws_consultas(
            params["coluna1"], params["ordenacao"], params["data_ini"],
            params["biblioteca"], params["tipo_obra"], params["termo1"], params["colecao"]
        )

    raw = clean(response)
    if not raw:
        return [], "Consulta realizada, mas o serviço retornou uma resposta vazia."

    records = parse_html_records(raw, query, base_url)

    # If the SOAP response itself contains the query/title but no /acervo links,
    # expose it as "Possível" rather than "Não encontrado".
    if not records:
        if norm(query) in norm(raw):
            return [{
                "title": query,
                "author": "",
                "year": "",
                "isbn": "",
                "classification": "",
                "link": base_url,
            }], "O Pergamum respondeu, mas o formato do resultado precisa ser interpretado."
        return [], "Consulta realizada; nenhum registro foi extraído do retorno do Pergamum."

    return records, "Consulta Pergamum realizada com sucesso."

def search_pergamum(source, base_url, query):
    try:
        records, note = pergamum_search(source, base_url, query)
        rows = []
        for r in records:
            status = "Encontrado" if classify_title_match(query, r["title"]) else "Possível"
            rows.append(result_row(
                query, source, status, r["title"], r["author"], r["year"],
                r["isbn"], r["classification"], r["link"], note
            ))
        if rows:
            return rows
        return [result_row(query, source, "Não encontrado", note=note)]
    except (requests.RequestException, TransportError, Fault, Exception) as exc:
        msg = f"{type(exc).__name__}: {str(exc)[:400]}"
        return [result_row(query, source, "Erro", note=f"Falha técnica — {msg}")]

def search_korea(query, api_key):
    if not api_key:
        return [result_row(query, "National Library of Korea", "Configuração necessária",
                           note="Informe a chave Open API da National Library of Korea.")]
    url = "https://www.nl.go.kr/NL/search/openApi/search.do"
    params = {
        "key": api_key,
        "apiType": "xml",
        "srchTarget": "title",
        "kwd": query,
        "pageSize": 10,
        "pageNum": 1,
    }
    try:
        r = requests.get(url, params=params, timeout=30)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "xml")
        items = soup.find_all(["item", "doc"])
        if not items:
            return [result_row(query, "National Library of Korea", "Não encontrado",
                               note="Consulta realizada pela Open API; nenhum registro retornado.")]
        rows = []
        for item in items:
            title = clean(item.find("title").get_text()) if item.find("title") else query
            author = clean(item.find("author").get_text()) if item.find("author") else ""
            year = clean(item.find("publish_year").get_text()) if item.find("publish_year") else ""
            link = clean(item.find("link").get_text()) if item.find("link") else ""
            status = "Encontrado" if classify_title_match(query, title) else "Possível"
            rows.append(result_row(query, "National Library of Korea", status,
                                   title, author, year, "", "", link,
                                   "Consulta realizada pela Open API."))
        return rows
    except Exception as exc:
        return [result_row(query, "National Library of Korea", "Erro",
                           note=f"Falha técnica — {type(exc).__name__}: {str(exc)[:400]}")]

def search_bndigital(query):
    link = "https://bndigital.bn.gov.br/search/?q=" + quote_plus(query)
    return [result_row(query, "BNDigital", "Consulta manual",
                       link=link,
                       note="O conector automático da BNDigital ainda não foi ativado. O link abre a busca oficial.")]

st.title("📚 Localizador de Acervos")
st.caption("Versão de testes dos conectores — erros técnicos não são tratados como ausência no acervo.")

with st.sidebar:
    st.header("Configuração")
    selected = st.multiselect(
        "Acervos",
        list(SOURCES.keys()),
        default=["UFSC — Pergamum"],
    )

    korea_key = st.text_input(
        "Chave Open API — National Library of Korea",
        type="password",
        help="Necessária somente para consultar a Open API da National Library of Korea.",
    )

    st.divider()
    st.subheader("Endpoints Pergamum")
    ufsc_url = st.text_input("UFSC", "https://pergamum.ufsc.br")
    udesc_url = st.text_input("UDESC", "https://pergamumweb.udesc.br")

st.header("1. Títulos para pesquisar")
mode = st.radio("Como inserir os títulos", ["Colar lista", "Enviar CSV/Excel"], horizontal=True)

titles = []
if mode == "Colar lista":
    raw_titles = st.text_area("Um título por linha", DEFAULT_TITLES, height=180)
    titles = [x.strip() for x in raw_titles.splitlines() if x.strip()]
else:
    uploaded = st.file_uploader("Envie um CSV ou Excel", type=["csv", "xlsx", "xls"])
    if uploaded:
        if uploaded.name.lower().endswith(".csv"):
            df = pd.read_csv(uploaded)
        else:
            df = pd.read_excel(uploaded)
        col = st.selectbox("Coluna que contém os títulos", list(df.columns))
        titles = [str(x).strip() for x in df[col].dropna().tolist() if str(x).strip()]

st.header("2. Pesquisa")
if st.button("🔎 Pesquisar acervos", type="primary", use_container_width=True):
    if not titles:
        st.warning("Informe pelo menos um título.")
        st.stop()
    if not selected:
        st.warning("Selecione pelo menos um acervo.")
        st.stop()

    rows = []
    progress = st.progress(0)
    total = len(titles) * len(selected)
    done = 0

    for title in titles:
        for source in selected:
            if source == "UFSC — Pergamum":
                rows.extend(search_pergamum(source, ufsc_url, title))
            elif source == "UDESC — Pergamum":
                rows.extend(search_pergamum(source, udesc_url, title))
            elif source == "National Library of Korea":
                rows.extend(search_korea(title, korea_key))
            elif source == "BNDigital":
                rows.extend(search_bndigital(title))
            done += 1
            progress.progress(done / total)

    df_results = pd.DataFrame(rows)

    st.header("3. Resultados")
    c1, c2, c3 = st.columns(3)
    c1.metric("Títulos", len(titles))
    c2.metric("Verificações", len(titles) * len(selected))
    c3.metric("Encontrados", int((df_results["Resultado"] == "Encontrado").sum()))

    st.dataframe(df_results, use_container_width=True, hide_index=True)

    excel = io.BytesIO()
    with pd.ExcelWriter(excel, engine="openpyxl") as writer:
        df_results.to_excel(writer, index=False, sheet_name="Resultados")
    st.download_button(
        "📥 Baixar resultados em Excel",
        data=excel.getvalue(),
        file_name="resultados_acervos.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    erros = df_results[df_results["Resultado"].isin(["Erro", "Configuração necessária"])]
    if not erros.empty:
        st.warning(
            "Há conectores com erro/configuração pendente. Esses registros NÃO foram classificados como 'Não encontrado'."
        )
