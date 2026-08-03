"""
App: Digitalizador de Formulários com IA (Gemini) + Excel
----------------------------------------------------------
Captura foto (câmera ou upload) de um ou mais formulários físicos,
usa o Gemini para extrair as perguntas/respostas em JSON e salva
automaticamente como nova linha em uma planilha Excel local.
"""

import json
import os
from datetime import datetime

import pandas as pd
import streamlit as st
from google import genai
from google.genai import types

# ----------------------------------------------------------------------------
# CONFIGURAÇÕES GERAIS
# ----------------------------------------------------------------------------

ARQUIVO_EXCEL = "formularios_extraidos.xlsx"
NOME_ABA = "Respostas"
MODELO_GEMINI = "gemini-2.5-flash-lite"  # modelo atual, com cota gratuita generosa

PROMPT_MAGICO = """
Você é um especialista em digitalização de formulários físicos.
Analise a(s) imagem(ns) deste formulário preenchido (à mão ou digitado).

Tarefa:
1. Identifique cada pergunta/campo do formulário unindo as informações de todas as imagens enviadas.
2. Transforme cada pergunta em uma CHAVE de JSON, em snake_case, sem acentos,
   curta e descritiva (ex: "Nome completo:" -> "nome_completo").
3. O VALOR de cada chave deve ser exatamente a resposta preenchida no formulário.
4. Se um campo estiver ilegível, vazio ou não preenchido, use "" (string vazia).
5. Não invente informações que não estão na imagem.
6. Responda APENAS com um objeto JSON válido (um único nível, chave: valor),
   sem markdown, sem ```json, sem comentários e sem texto antes ou depois.
"""

# ----------------------------------------------------------------------------
# CLIENTE GEMINI E ESTADO DA SESSÃO
# ----------------------------------------------------------------------------

def obter_cliente_gemini() -> genai.Client:
    """
    Busca a chave de forma segura para não quebrar o site caso o Secrets não exista.
    """
    api_key = None
    
    # 1. Tenta buscar no cofre da nuvem (Streamlit Secrets)
    try:
        if "GEMINI_API_KEY" in st.secrets:
            api_key = st.secrets["GEMINI_API_KEY"]
    except Exception:
        pass
        
    # 2. Se não achou na nuvem, tenta buscar localmente
    if not api_key:
        api_key = os.environ.get("GEMINI_API_KEY")
        
    if not api_key:
        st.error("Chave GEMINI_API_KEY não encontrada. Configure-a em 'Settings > Secrets' no Streamlit Cloud.")
        st.stop()
        
    return genai.Client(api_key=api_key)


def extrair_dados_formulario(lista_imagens: list) -> dict:
    client = obter_cliente_gemini()

    conteudo_envio = [PROMPT_MAGICO]
    for img_bytes, mime_type in lista_imagens:
        conteudo_envio.append(types.Part.from_bytes(data=img_bytes, mime_type=mime_type))

    response = client.models.generate_content(
        model=MODELO_GEMINI,
        contents=conteudo_envio,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            max_output_tokens=8192,
            temperature=0.1,
        ),
    )

    texto = (response.text or "").strip()

    if texto.startswith("```"):
        texto = texto.strip("`").strip()
        if texto.lower().startswith("json"):
            texto = texto[4:].strip()

    try:
        dados = json.loads(texto)
        if not isinstance(dados, dict):
            raise ValueError("A resposta da IA não é um objeto JSON simples.")
    except (json.JSONDecodeError, ValueError):
        dados = {
            "erro_leitura": "Não foi possível interpretar a resposta da IA como JSON.",
            "resposta_bruta": texto[:500],
        }

    return dados


# ----------------------------------------------------------------------------
# CAMADA DE DADOS (EXCEL)
# ----------------------------------------------------------------------------

def garantir_planilha_existe():
    if not os.path.exists(ARQUIVO_EXCEL):
        df_inicial = pd.DataFrame(columns=["id", "data_hora"])
        df_inicial.to_excel(ARQUIVO_EXCEL, sheet_name=NOME_ABA, index=False)


def salvar_novo_registro(dados: dict) -> pd.DataFrame:
    garantir_planilha_existe()
    df = pd.read_excel(ARQUIVO_EXCEL, sheet_name=NOME_ABA)
    novo_id = int(df["id"].max()) + 1 if not df.empty and df["id"].notna().any() else 1

    nova_linha = {
        "id": novo_id,
        "data_hora": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        **dados,
    }

    df_novo = pd.DataFrame([nova_linha])
    df_final = pd.concat([df, df_novo], ignore_index=True)
    df_final.to_excel(ARQUIVO_EXCEL, sheet_name=NOME_ABA, index=False)
    return df_final


# ----------------------------------------------------------------------------
# INTERFACE STREAMLIT
# ----------------------------------------------------------------------------

st.set_page_config(page_title="Digitalizador de Formulários", page_icon="📄", layout="centered")

st.title("📄 Digitalizador de Formulários com IA")
st.caption("Tire uma foto ou envie arquivo(s) do formulário.")

garantir_planilha_existe()

# Memória para armazenar as fotos tiradas pela câmera
if "fotos_camera" not in st.session_state:
    st.session_state["fotos_camera"] = []

aba_camera, aba_upload = st.tabs(["📷 Usar câmera", "📁 Enviar arquivo(s)"])

with aba_camera:
    foto = st.camera_input("Tire uma foto do formulário")
    
    if foto is not None:
        if st.button("📸 Guardar esta foto"):
            st.session_state["fotos_camera"].append((foto.getvalue(), foto.type or "image/jpeg"))
            st.success("Foto salva na memória! Tire a próxima foto acima ou clique em extrair.")
            
    if st.session_state["fotos_camera"]:
        st.write(f"**Fotos prontas na memória:** {len(st.session_state['fotos_camera'])}")
        if st.button("🗑️ Limpar fotos da câmera"):
            st.session_state["fotos_camera"] = []
            st.rerun()

# Junta as fotos da câmera com as fotos enviadas por upload
imagens_para_processar = list(st.session_state["fotos_camera"])

with aba_upload:
    arquivos = st.file_uploader(
        "Selecione a(s) imagem(ns) do formulário",
        type=["png", "jpg", "jpeg", "webp"],
        accept_multiple_files=True,
    )
    if arquivos:
        for arquivo in arquivos:
            imagens_para_processar.append((arquivo.getvalue(), arquivo.type or "image/jpeg"))

if imagens_para_processar:
    st.info(f"{len(imagens_para_processar)} imagem(ns) pronta(s) para leitura no total.")

    cols = st.columns(len(imagens_para_processar))
    for idx, (img_bytes, _) in enumerate(imagens_para_processar):
        with cols[idx]:
            st.image(img_bytes, use_container_width=True)

    if st.button("🔎 Extrair dados com IA", type="primary"):
        with st.spinner("Lendo o formulário com o Gemini..."):
            dados_extraidos = extrair_dados_formulario(imagens_para_processar)

        st.session_state["dados_extraidos"] = dados_extraidos

if "dados_extraidos" in st.session_state:
    st.subheader("Dados extraídos")
    dados = st.session_state["dados_extraidos"]

    if "erro_leitura" in dados:
        st.warning(dados["erro_leitura"])
        st.text_area("Resposta bruta da IA", dados.get("resposta_bruta", ""), height=150)
    else:
        st.json(dados)

        col1, col2 = st.columns(2)
        with col1:
            if st.button("✅ Salvar na planilha", type="primary"):
                df_atualizado = salvar_novo_registro(dados)
                st.success(f"Registro salvo! Total de linhas na planilha: {len(df_atualizado)}")
                # Limpa a memória após salvar
                del st.session_state["dados_extraidos"]
                st.session_state["fotos_camera"] = []
                st.rerun()
        with col2:
            if st.button("❌ Descartar"):
                del st.session_state["dados_extraidos"]
                st.session_state["fotos_camera"] = []
                st.rerun()

st.divider()

with st.expander("📊 Ver planilha atual"):
    if os.path.exists(ARQUIVO_EXCEL):
        df_visualizacao = pd.read_excel(ARQUIVO_EXCEL, sheet_name=NOME_ABA)
        st.dataframe(df_visualizacao, use_container_width=True)
        with open(ARQUIVO_EXCEL, "rb") as f:
            st.download_button(
                "⬇️ Baixar planilha (.xlsx)",
                data=f,
                file_name=ARQUIVO_EXCEL,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
