
# Localizador de Acervos — versão web

## O que é
Aplicação Streamlit para pesquisar uma lista de títulos em diferentes catálogos.

### Conectores nesta versão
- UFSC — Pergamum: usa o Web Service Pergamum e tenta consultar `ws_consultas_completo`.
- UDESC — Pergamum: usa o Web Service público documentado no WSDL.
- National Library of Korea: usa a Open API oficial; requer chave de API.
- BNDigital: gera consulta direta auditável no portal; o conector automático OAI/portal ainda deve ser validado contra o endpoint público atual.

## Rodar no computador
1. Instale Python 3.11+.
2. Abra o terminal nesta pasta.
3. Rode:
   `pip install -r requirements.txt`
4. Rode:
   `streamlit run app.py`
5. Abra o endereço mostrado pelo Streamlit no navegador.

## Publicar para acesso pelo navegador
A opção simples é colocar esta pasta em um repositório GitHub e publicar em um serviço compatível com Streamlit.
O aplicativo não precisa de domínio próprio.

## Observação importante
A National Library of Korea exige uma chave de API oficial.
Os Web Services Pergamum são públicos, mas os parâmetros de busca podem variar por instalação; por isso a aplicação mostra erro em vez de inventar dados quando a instalação rejeitar uma consulta.
