"""
Autenticação simples para apps Streamlit.

- Senhas guardadas como hash PBKDF2-SHA256 (nunca em texto puro).
- Usuários definidos em st.secrets["usuarios"] (recomendado em produção).
  Se não existir, usa os 2 usuários de TESTE abaixo.
"""
import hashlib
import hmac
import time

import streamlit as st

# ---------------------------------------------------------------------------
# Usuários de TESTE (troque/remova em produção usando st.secrets)
#   admin   / admin123
#   usuario / usuario123
# ---------------------------------------------------------------------------
USUARIOS_TESTE = {
    "admin": {
        "nome": "Administrador",
        "senha_hash": "pbkdf2_sha256$200000$36c596449e8e12a2e808de20126b296c$9aa3ed3b5e6b7dcee8d29c04119ab356b8e2ca79a738a904fe2d765a22c01114",
    },
    "usuario": {
        "nome": "Usuário Teste",
        "senha_hash": "pbkdf2_sha256$200000$c8ef1571eb5c9181330659caf833e8e3$2ec3bdf95015e58ee988b085f74d1db69d5930fb0002a96eb59e657e500a0c30",
    },
}

MAX_TENTATIVAS = 5
BLOQUEIO_SEG = 60


def gerar_hash(senha: str, iteracoes: int = 200_000) -> str:
    import os

    salt = os.urandom(16).hex()
    dk = hashlib.pbkdf2_hmac("sha256", senha.encode(), bytes.fromhex(salt), iteracoes).hex()
    return f"pbkdf2_sha256${iteracoes}${salt}${dk}"


def _verificar_senha(senha: str, hash_guardado: str) -> bool:
    try:
        _, iteracoes, salt, esperado = hash_guardado.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", senha.encode(), bytes.fromhex(salt), int(iteracoes)).hex()
        return hmac.compare_digest(dk, esperado)
    except Exception:
        return False


def _carregar_usuarios() -> dict:
    try:
        if "usuarios" in st.secrets:
            return {k: dict(v) for k, v in st.secrets["usuarios"].items()}
    except Exception:
        pass
    return USUARIOS_TESTE


def _autenticar(usuario: str, senha: str) -> dict | None:
    usuarios = _carregar_usuarios()
    dados = usuarios.get(usuario.strip().lower())
    # Se o usuário não existe, ainda faz um cálculo de hash (evita revelar quais usuários existem pelo tempo de resposta)
    hash_ref = dados["senha_hash"] if dados else USUARIOS_TESTE["admin"]["senha_hash"]
    ok = _verificar_senha(senha, hash_ref)
    if dados and ok:
        return {"usuario": usuario.strip().lower(), "nome": dados.get("nome", usuario)}
    return None


def exigir_login() -> dict:
    """Mostra a tela de login e interrompe o app até autenticar. Devolve os dados do usuário."""
    if st.session_state.get("auth_user"):
        return st.session_state["auth_user"]

    # Bloqueio temporário após muitas tentativas
    bloqueado_ate = st.session_state.get("auth_bloqueado_ate", 0)
    restante = int(bloqueado_ate - time.time())

    _, centro, _ = st.columns([1, 1.2, 1])
    with centro:
        st.title("🔐 Acesso restrito")
        st.caption("Entre com seu usuário e senha para continuar.")

        if restante > 0:
            st.error(f"Muitas tentativas. Aguarde {restante}s e tente novamente.")
            time.sleep(1)
            st.rerun()

        with st.form("login"):
            usuario = st.text_input("Usuário")
            senha = st.text_input("Senha", type="password")
            entrar = st.form_submit_button("Entrar", use_container_width=True)

        if entrar:
            dados = _autenticar(usuario, senha)
            if dados:
                st.session_state["auth_user"] = dados
                st.session_state["auth_falhas"] = 0
                st.rerun()
            else:
                falhas = st.session_state.get("auth_falhas", 0) + 1
                st.session_state["auth_falhas"] = falhas
                if falhas >= MAX_TENTATIVAS:
                    st.session_state["auth_bloqueado_ate"] = time.time() + BLOQUEIO_SEG
                    st.session_state["auth_falhas"] = 0
                    st.rerun()
                st.error(f"Usuário ou senha inválidos. ({falhas}/{MAX_TENTATIVAS})")

        if _carregar_usuarios() is USUARIOS_TESTE:
            st.info("**Modo teste** — usuários: `admin` / `admin123` e `usuario` / `usuario123`")

    st.stop()


def botao_logout():
    """Mostra o nome do usuário e o botão Sair na barra lateral."""
    user = st.session_state.get("auth_user")
    if not user:
        return
    with st.sidebar:
        st.markdown(f"👤 **{user['nome']}**")
        if st.button("Sair", use_container_width=True):
            for k in ("auth_user", "auth_falhas", "auth_bloqueado_ate"):
                st.session_state.pop(k, None)
            st.rerun()
        st.divider()
