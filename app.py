
import os, re, io, csv, unicodedata
from urllib.parse import quote_plus
import requests
import pandas as pd
import streamlit as st
from bs4 import BeautifulSoup

st.set_page_config(page_title="Localizador de Acervos", page_icon="📚", layout="wide")

SOURCES = {
    "UFSC — Pergamum": "ufsc",
    "UDESC — Pergamum": "udesc",
    "BNDigital": "bndigital",
    "National Library of Korea": "korea",
}

DEFAULT_TITLES = [
    "Mulherzinhas",
    "As veias abertas da América Latina",
    "Dom Casmurro",
    "The Great Gatsby",
    "O segundo sexo",
]

def norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii","ignore").decode()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s.lower())).strip()

def similarity(a, b):
    aa, bb = set(norm(a).split()), set(norm(b).split())
    if not aa or not bb: return 0
    return len(aa & bb) / len(aa | bb)

def result(title, source, status, found_title="", author="", year="", isbn="", call_no="", url="", note=""):
    return {
        "Título pesquisado": title, "Acervo": source, "Resultado": status,
        "Título encontrado": found_title, "Autor": author, "Ano": year,
        "ISBN": isbn, "Classificação": call_no, "Link": url, "Observação": note
    }

def korea_search(title, api_key):
    if not api_key:
        return [result(title, "National Library of Korea", "Configuração necessária",
                       note="Informe a chave Open API da National Library of Korea na barra lateral.")]
    url = "https://www.nl.go.kr/NL/search/openApi/search.do"
    params = {"key": api_key, "apiType":"xml", "srchTarget":"title",
              "kwd":title, "pageSize":10, "pageNum":1}
    try:
        r = requests.get(url, params=params, timeout=30)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "xml")
        items = soup.find_all(["item","record","doc"])
        if not items:
            # fallback: generic XML parsing
            titles = soup.find_all(["title_info","title"])
            if not titles:
                return [result(title,"National Library of Korea","Não encontrado")]
            items = titles
        out=[]
        for item in items[:10]:
            def txt(*names):
                for n in names:
                    x=item.find(n)
                    if x and x.get_text(strip=True): return x.get_text(" ",strip=True)
                return ""
            ft=txt("title_info","title")
            au=txt("author_info","author")
            yr=txt("pub_year_info","pub_year")
            isbn=txt("isbn")
            call=txt("call_no","cheonggu")
            ident=txt("id","control_no")
            link=txt("org_link")
            score=similarity(title, ft)
            status="Encontrado" if score>=0.65 else "Possível"
            out.append(result(title,"National Library of Korea",status,ft,au,yr,isbn,call,link,
                              f"Similaridade textual aproximada: {score:.0%}"))
        return out or [result(title,"National Library of Korea","Não encontrado")]
    except Exception as e:
        return [result(title,"National Library of Korea","Erro",note=str(e))]

def pergamum_search(title, source, base_url):
    # Pergamum exposes a SOAP Web Service. The operation ws_consultas_completo
    # is used here; if an installation changes its SOAP conventions, the
    # error is shown rather than inventing a result.
    try:
        import zeep
        ws = base_url.rstrip("/") + "/pergamum/web_service/servidor_ws.php?WSDL"
        client = zeep.Client(wsdl=ws)
        service = client.service
        # The public WSDL documents these fields. Empty optional filters are intentional.
        raw = service.ws_consultas_completo(
            biblioteca="", cod_tipo_obra="", tipo_termos="AND",
            coluna1="titulo", termo1=title,
            operador2="", coluna2="", termo2="",
            operador3="", coluna3="", termo3="",
            comparacao="contém", data_ini=0, data_fin=0,
            cod_idioma="", cod_local="", cod_localizacao=0,
            cod_categoria="", cod_colecao="", exibe_exemplares="S",
            bib_virtual="", cod_pessoa_login=0, modo_ordenar="",
            auxiliar="", campus=""
        )
        text = str(raw or "")
        soup = BeautifulSoup(text, "html.parser")
        visible = soup.get_text(" ", strip=True)
        if not visible:
            visible = re.sub(r"<[^>]+>"," ",text)
        # Try to recover result links/identifiers from the returned HTML.
        links=[]
        for a in soup.find_all("a"):
            href=a.get("href","")
            label=a.get_text(" ",strip=True)
            if href and label:
                links.append((label, href))
        if not visible.strip() or any(x in visible.lower() for x in ["nenhum registro","não encontrado","nao encontrado"]):
            return [result(title,source,"Não encontrado")]
        best_label = ""
        best_url = ""
        best_score = 0
        for label,href in links:
            sc=similarity(title,label)
            if sc>best_score:
                best_score, best_label, best_url=sc,label,href
        if best_label:
            status="Encontrado" if best_score>=0.55 else "Possível"
            return [result(title,source,status,found_title=best_label,url=best_url,
                           note=f"Resultado retornado pelo Web Service Pergamum; similaridade do rótulo: {best_score:.0%}")]
        return [result(title,source,"Possível",found_title=visible[:500],
                       note="O Web Service retornou conteúdo, mas o protótipo não conseguiu estruturar todos os campos.")]
    except Exception as e:
        return [result(title,source,"Erro",
                       note="Não foi possível consultar o Web Service automaticamente: "+str(e))]

def bndigital_search(title):
    # BNDigital's public search is retained as a direct, auditable fallback.
    # The result page is opened by the user; no fabricated bibliographic data.
    url = "https://bndigital.bn.gov.br/search/?q=" + quote_plus(title)
    return [result(title,"BNDigital","Consulta manual",url=url,
                   note="A versão inicial gera a consulta direta. O conector automático OAI/portal será ativado após confirmar o endpoint público atual da BNDigital.")]

st.title("📚 Localizador de Acervos")
st.caption("Protótipo web funcional para busca em múltiplos catálogos, com resultados auditáveis e exportação.")

with st.sidebar:
    st.header("Configuração")
    sources = st.multiselect("Acervos", list(SOURCES), default=list(SOURCES))
    korea_key = st.text_input("Chave Open API — National Library of Korea", type="password",
                              value=os.getenv("NLK_API_KEY",""))
    st.markdown("---")
    st.write("**Endpoints Pergamum**")
    ufsc_url = st.text_input("UFSC", "https://pergamum.ufsc.br")
    udesc_url = st.text_input("UDESC", "https://pergamumweb.udesc.br")
    st.info("A chave da National Library of Korea é obrigatória para usar a API oficial.")

st.subheader("1. Títulos")
input_mode = st.radio("Como inserir?", ["Colar lista", "Enviar Excel"], horizontal=True)
titles=[]
if input_mode=="Colar lista":
    raw=st.text_area("Um título por linha", "\n".join(DEFAULT_TITLES), height=180)
    titles=[x.strip() for x in raw.splitlines() if x.strip()]
else:
    f=st.file_uploader("Excel (.xlsx) ou CSV", type=["xlsx","csv"])
    if f:
        df=pd.read_excel(f) if f.name.lower().endswith("xlsx") else pd.read_csv(f)
        col=st.selectbox("Coluna de títulos", list(df.columns))
        titles=[str(x).strip() for x in df[col].dropna().tolist() if str(x).strip()]

st.subheader("2. Pesquisa")
if st.button("🔎 Pesquisar acervos", type="primary", use_container_width=True):
    if not titles:
        st.warning("Informe pelo menos um título.")
    elif not sources:
        st.warning("Selecione pelo menos um acervo.")
    else:
        all_rows=[]
        progress=st.progress(0)
        total=len(titles)*len(sources); done=0
        for title in titles:
            for src in sources:
                key=SOURCES[src]
                if key=="korea":
                    rows=korea_search(title,korea_key)
                elif key=="ufsc":
                    rows=pergamum_search(title,"UFSC — Pergamum",ufsc_url)
                elif key=="udesc":
                    rows=pergamum_search(title,"UDESC — Pergamum",udesc_url)
                else:
                    rows=bndigital_search(title)
                all_rows.extend(rows)
                done+=1; progress.progress(done/total)
        st.session_state["results"]=pd.DataFrame(all_rows)

if "results" in st.session_state:
    df=st.session_state["results"]
    st.subheader("3. Resultados")
    c1,c2,c3=st.columns(3)
    c1.metric("Títulos", len(titles))
    c2.metric("Verificações", len(df))
    c3.metric("Encontrados", int((df["Resultado"]=="Encontrado").sum()))
    st.dataframe(df, use_container_width=True, hide_index=True)
    out=io.StringIO()
    df.to_csv(out,index=False,sep=";",encoding="utf-8-sig")
    st.download_button("📥 Baixar resultados CSV/Excel", out.getvalue(),
                       "resultados_localizador.csv","text/csv",use_container_width=True)
    st.caption("Os estados 'Possível', 'Consulta manual' e 'Erro' não são equivalentes a ausência no acervo.")
