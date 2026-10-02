"""
Visualizador de camadas vetoriais (Shapefile, GeoPackage, KML/KMZ, GeoJSON)
Rodar com:  streamlit run app.py
"""
import tempfile
import zipfile
from pathlib import Path

import folium
import geopandas as gpd
import pandas as pd
import pyogrio
import streamlit as st
from folium.features import GeoJsonPopup, GeoJsonTooltip
from streamlit_folium import st_folium

import auth

st.set_page_config(page_title="Visualizador de Camadas", page_icon="🗺️", layout="wide")

# Login obrigatório: nada abaixo desta linha roda sem autenticação
auth.exigir_login()

EXTENSOES_PRINCIPAIS = (".shp", ".gpkg", ".kml", ".geojson", ".json")
MAX_FEICOES_MAPA = 20000


# ----------------------------------------------------------------------------
# Leitura
# ----------------------------------------------------------------------------
def salvar_uploads(arquivos, pasta: Path) -> Path:
    """Salva os uploads em disco e devolve o caminho do arquivo principal."""
    for f in arquivos:
        destino = pasta / f.name
        destino.write_bytes(f.getbuffer())
        if destino.suffix.lower() in (".zip", ".kmz"):
            with zipfile.ZipFile(destino) as z:
                z.extractall(pasta)
            if destino.suffix.lower() == ".kmz":
                continue

    candidatos = [
        p for p in pasta.rglob("*")
        if p.suffix.lower() in EXTENSOES_PRINCIPAIS and not p.name.startswith("._")
    ]
    if not candidatos:
        raise ValueError(
            "Nenhum arquivo principal encontrado (.shp, .gpkg, .kml, .geojson). "
            "Para shapefile, envie .shp + .shx + .dbf (+ .prj) ou um .zip."
        )
    # prioridade: ordem de EXTENSOES_PRINCIPAIS
    candidatos.sort(key=lambda p: EXTENSOES_PRINCIPAIS.index(p.suffix.lower()))
    return candidatos[0]


def listar_camadas(caminho: Path) -> list[str]:
    try:
        return [c[0] for c in pyogrio.list_layers(str(caminho))]
    except Exception:
        return []


@st.cache_data(show_spinner="Lendo camada...")
def ler_camada(caminho: str, camada: str | None) -> gpd.GeoDataFrame:
    gdf = pyogrio.read_dataframe(caminho, layer=camada, force_2d=True)
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
    if gdf.crs is None:
        gdf = gdf.set_crs(4326)  # KML é sempre 4326; demais: assume WGS84
    return gdf


# ----------------------------------------------------------------------------
# Utilidades
# ----------------------------------------------------------------------------
def preparar_para_json(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Converte colunas não serializáveis (datas, etc.) em texto."""
    gdf = gdf.copy()
    for col in gdf.columns:
        if col == gdf.geometry.name:
            continue
        if pd.api.types.is_datetime64_any_dtype(gdf[col]):
            gdf[col] = gdf[col].astype(str)
        elif gdf[col].dtype == "object":
            gdf[col] = gdf[col].apply(lambda v: v if v is None or isinstance(v, (str, int, float, bool)) else str(v))
    return gdf


def estatisticas(gdf: gpd.GeoDataFrame) -> dict:
    tipos = ", ".join(sorted(gdf.geom_type.unique()))
    info = {
        "Feições": f"{len(gdf):,}".replace(",", "."),
        "Geometria": tipos,
        "CRS": gdf.crs.to_string() if gdf.crs else "—",
    }
    try:
        utm = gdf.estimate_utm_crs()
        proj = gdf.to_crs(utm)
        if proj.geom_type.str.contains("Polygon").any():
            ha = proj.area.sum() / 10_000
            info["Área total (ha)"] = f"{ha:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        elif proj.geom_type.str.contains("Line").any():
            km = proj.length.sum() / 1000
            info["Comprimento (km)"] = f"{km:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        pass
    return info


def montar_mapa(gdf: gpd.GeoDataFrame, colunas_popup: list[str]) -> folium.Map:
    m = folium.Map(location=[-15, -50], zoom_start=4, tiles=None, control_scale=True)
    folium.TileLayer("OpenStreetMap", name="OpenStreetMap").add_to(m)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri World Imagery",
        name="Satélite (Esri)",
    ).add_to(m)

    kwargs = {}
    if colunas_popup:
        kwargs["tooltip"] = GeoJsonTooltip(fields=colunas_popup[:4], sticky=True)
        kwargs["popup"] = GeoJsonPopup(fields=colunas_popup[:30], max_width=350)

    folium.GeoJson(
        gdf.__geo_interface__,
        name="Camada",
        style_function=lambda _: {"color": "#e8590c", "weight": 2, "fillOpacity": 0.25},
        highlight_function=lambda _: {"weight": 4, "fillOpacity": 0.5},
        marker=folium.CircleMarker(radius=5, fill=True),
        **kwargs,
    ).add_to(m)

    minx, miny, maxx, maxy = gdf.total_bounds
    m.fit_bounds([[miny, minx], [maxy, maxx]])
    folium.LayerControl().add_to(m)
    return m


# ----------------------------------------------------------------------------
# Interface
# ----------------------------------------------------------------------------
st.title("🗺️ Visualizador de Camadas")
st.caption("Envie um Shapefile, GeoPackage, KML/KMZ ou GeoJSON para ver o mapa e a tabela de atributos.")

auth.botao_logout()

with st.sidebar:
    st.header("Arquivo")
    uploads = st.file_uploader(
        "Selecione o(s) arquivo(s)",
        type=["shp", "shx", "dbf", "prj", "cpg", "qmd", "gpkg", "kml", "kmz", "geojson", "json", "zip"],
        accept_multiple_files=True,
        help="Shapefile: envie todos os arquivos juntos (.shp, .shx, .dbf, .prj) ou um .zip.",
    )

if not uploads:
    st.info("👈 Envie um arquivo na barra lateral para começar.")
    st.stop()

with tempfile.TemporaryDirectory() as tmp:
    pasta = Path(tmp)
    try:
        principal = salvar_uploads(uploads, pasta)
    except Exception as e:
        st.error(str(e))
        st.stop()

    camadas = listar_camadas(principal)
    camada = None
    with st.sidebar:
        if len(camadas) > 1:
            camada = st.selectbox("Camada", camadas)
        elif camadas:
            camada = camadas[0]
            st.caption(f"Camada: **{camada}**")

    try:
        gdf = ler_camada(str(principal), camada)
    except Exception as e:
        st.error(f"Não foi possível ler o arquivo: {e}")
        st.stop()

if gdf.empty:
    st.warning("A camada não possui geometrias válidas.")
    st.stop()

# métricas
info = estatisticas(gdf)
cols = st.columns(len(info))
for c, (k, v) in zip(cols, info.items()):
    c.metric(k, v)

atributos = [c for c in gdf.columns if c != gdf.geometry.name]

# filtros (sidebar)
with st.sidebar:
    st.header("Tabela / Filtros")
    mostrar = st.multiselect("Colunas visíveis", atributos, default=atributos)
    busca = st.text_input("Buscar texto em qualquer coluna")

filtrado = gdf
if busca:
    mascara = gdf[atributos].astype(str).apply(lambda s: s.str.contains(busca, case=False, na=False)).any(axis=1)
    filtrado = gdf[mascara]

aba_mapa, aba_tabela = st.tabs(["🗺️ Mapa", "📋 Tabela de atributos"])

with aba_mapa:
    if filtrado.empty:
        st.warning("Nenhuma feição encontrada com o filtro atual.")
    else:
        g = preparar_para_json(filtrado.to_crs(4326))
        if len(g) > MAX_FEICOES_MAPA:
            st.warning(f"Camada grande: exibindo apenas as primeiras {MAX_FEICOES_MAPA:,} feições no mapa.".replace(",", "."))
            g = g.head(MAX_FEICOES_MAPA)
        mapa = montar_mapa(g, [c for c in mostrar if c in g.columns])
        st_folium(mapa, height=600, use_container_width=True, returned_objects=[])

with aba_tabela:
    st.write(f"**{len(filtrado)}** de {len(gdf)} feições")
    st.dataframe(
        pd.DataFrame(filtrado[mostrar]) if mostrar else pd.DataFrame(index=filtrado.index),
        use_container_width=True,
        height=550,
    )
    c1, c2 = st.columns(2)
    csv = pd.DataFrame(filtrado[atributos]).to_csv(index=False).encode("utf-8-sig")
    c1.download_button("⬇️ Baixar tabela (CSV)", csv, "atributos.csv", "text/csv")
    geojson = preparar_para_json(filtrado.to_crs(4326)).to_json().encode("utf-8")
    c2.download_button("⬇️ Baixar camada (GeoJSON)", geojson, "camada.geojson", "application/geo+json")
