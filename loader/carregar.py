"""Espelha os dados abertos do CNPJ da Receita Federal num Postgres.

Fluxo de uma carga:
  1. lista os meses publicados no compartilhamento público da Receita (WebDAV);
  2. se o mês mais recente já foi carregado, sai sem fazer nada (rodar todo dia é seguro);
  3. baixa cada .zip, decodifica de latin-1 e faz COPY num schema temporário;
  4. cria índices e views, e troca o schema de produção numa transação só.

Quem consulta nunca vê base pela metade: até o passo 4 o schema antigo segue intacto.

Uso:
  python carregar.py              # mês mais recente, se ainda não carregado
  python carregar.py --mes 2026-09
  python carregar.py --forcar     # recarrega mesmo se o mês já consta
  python carregar.py --listar     # só mostra os meses publicados
  python carregar.py --so-dicionarios   # carga pequena para testar a instalação
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import psycopg

from layout import INDICES, TABELAS, tabela_do_zip

sys.stdout.reconfigure(encoding="utf-8")

BASE_URL = os.environ.get("RFB_WEBDAV_URL", "https://arquivos.receitafederal.gov.br/public.php/webdav/")
SHARE_TOKEN = os.environ.get("RFB_SHARE_TOKEN", "YggdBLfdninEJX9")
SCHEMA = os.environ.get("CNPJ_SCHEMA", "receita_federal")
SCHEMA_CARGA = f"{SCHEMA}_carga"
SCHEMA_CONTROLE = f"{SCHEMA}_controle"
DIR_DADOS = Path(os.environ.get("CNPJ_DIR_DADOS", "./dados"))
MANTER_ZIPS = os.environ.get("CNPJ_MANTER_ZIPS", "false").lower() == "true"
DICIONARIOS = {"cnaes", "motivos", "municipios", "naturezas", "paises", "qualificacoes"}
VIEWS_SQL = Path(__file__).with_name("views.sql")


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _req(url: str, method: str = "GET", headers: dict | None = None) -> urllib.request.Request:
    auth = base64.b64encode(f"{SHARE_TOKEN}:".encode()).decode()
    return urllib.request.Request(url, method=method, headers={"Authorization": f"Basic {auth}", **(headers or {})})


def listar(caminho: str = "") -> list[tuple[str, int]]:
    """PROPFIND Depth 1 -> [(nome, bytes)] dos filhos do caminho."""
    req = _req(BASE_URL + caminho, "PROPFIND", {"Depth": "1"})
    with urllib.request.urlopen(req, timeout=60) as r:
        arvore = ET.fromstring(r.read())
    ns = {"d": "DAV:"}
    itens = []
    for resp in arvore.findall("d:response", ns):
        href = resp.findtext("d:href", "", ns).rstrip("/")
        nome = href.rsplit("/", 1)[-1]
        tam = resp.findtext(".//d:getcontentlength", "0", ns)
        if nome and nome != caminho.strip("/"):
            itens.append((nome, int(tam or 0)))
    return itens


def meses_publicados() -> list[str]:
    return sorted(n for n, _ in listar() if re.fullmatch(r"\d{4}-\d{2}", n))


def baixar(mes: str, nome: str, tamanho: int, tentativas: int = 5) -> Path:
    destino = DIR_DADOS / mes / nome
    destino.parent.mkdir(parents=True, exist_ok=True)
    if destino.exists() and destino.stat().st_size == tamanho:
        return destino
    for n in range(1, tentativas + 1):
        ja = destino.stat().st_size if destino.exists() else 0
        hdr = {"Range": f"bytes={ja}-"} if ja else {}
        try:
            with urllib.request.urlopen(_req(f"{BASE_URL}{mes}/{nome}", headers=hdr), timeout=120) as r, \
                    open(destino, "ab" if ja and r.status == 206 else "wb") as f:
                while bloco := r.read(1 << 20):
                    f.write(bloco)
            if destino.stat().st_size == tamanho:
                return destino
            raise IOError(f"tamanho {destino.stat().st_size} != {tamanho}")
        except Exception as e:  # rede da Receita oscila; retoma do byte onde parou
            log(f"  {nome}: tentativa {n}/{tentativas} falhou ({e})")
            time.sleep(10 * n)
    raise RuntimeError(f"não consegui baixar {nome}")


def copiar_zip(cur: psycopg.Cursor, tabela: str, arquivo: Path) -> int:
    colunas = TABELAS[tabela]
    sql = (f"COPY {SCHEMA_CARGA}.{tabela} ({', '.join(colunas)}) FROM STDIN "
           "WITH (FORMAT csv, DELIMITER ';', QUOTE '\"', ENCODING 'UTF8')")
    with zipfile.ZipFile(arquivo) as z, cur.copy(sql) as copy:
        for membro in z.namelist():
            # A origem é latin-1. Decodificar aqui evita acento gravado em dupla codificação.
            with io.TextIOWrapper(z.open(membro), encoding="latin-1", newline="") as txt:
                while bloco := txt.read(1 << 22):
                    copy.write(bloco.replace("\x00", ""))
    return cur.rowcount


def preparar(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA_CONTROLE}")
        cur.execute(f"""CREATE TABLE IF NOT EXISTS {SCHEMA_CONTROLE}.cargas (
            mes text PRIMARY KEY, iniciada_em timestamptz NOT NULL DEFAULT now(),
            concluida_em timestamptz, linhas jsonb)""")
        cur.execute(f"DROP SCHEMA IF EXISTS {SCHEMA_CARGA} CASCADE")
        cur.execute(f"CREATE SCHEMA {SCHEMA_CARGA}")
        for tabela, colunas in TABELAS.items():
            cols = ", ".join(f"{c} text" for c in colunas)
            cur.execute(f"CREATE UNLOGGED TABLE {SCHEMA_CARGA}.{tabela} ({cols})")
    conn.commit()


def ja_carregado(conn: psycopg.Connection, mes: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass(%s)", (f"{SCHEMA_CONTROLE}.cargas",))
        if cur.fetchone()[0] is None:
            return False
        cur.execute(f"SELECT 1 FROM {SCHEMA_CONTROLE}.cargas WHERE mes=%s AND concluida_em IS NOT NULL", (mes,))
        return cur.fetchone() is not None


def publicar(conn: psycopg.Connection, mes: str, linhas: dict) -> None:
    with conn.cursor() as cur:
        log("criando índices")
        for tabela in TABELAS:
            cur.execute(f"ALTER TABLE {SCHEMA_CARGA}.{tabela} SET LOGGED")
        for ddl in INDICES:
            cur.execute(ddl.format(s=SCHEMA_CARGA))
        conn.commit()
        log("trocando o schema de produção")
        cur.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
        cur.execute(f"ALTER SCHEMA {SCHEMA_CARGA} RENAME TO {SCHEMA}")
        cur.execute(VIEWS_SQL.read_text(encoding="utf-8").replace("{schema}", SCHEMA))
        cur.execute(f"""INSERT INTO {SCHEMA_CONTROLE}.cargas (mes, concluida_em, linhas)
                        VALUES (%s, now(), %s)
                        ON CONFLICT (mes) DO UPDATE SET concluida_em=now(), linhas=EXCLUDED.linhas""",
                    (mes, json.dumps(linhas)))
    conn.commit()
    with conn.cursor() as cur:
        for tabela in TABELAS:
            cur.execute(f"ANALYZE {SCHEMA}.{tabela}")
    conn.commit()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mes")
    ap.add_argument("--forcar", action="store_true")
    ap.add_argument("--listar", action="store_true")
    ap.add_argument("--so-dicionarios", action="store_true")
    a = ap.parse_args()

    meses = meses_publicados()
    if a.listar:
        print("\n".join(meses))
        return 0
    mes = a.mes or meses[-1]
    if mes not in meses:
        log(f"mês {mes} não publicado. Disponíveis: {', '.join(meses[-6:])}")
        return 2

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        log("defina DATABASE_URL (veja .env.example)")
        return 2
    with psycopg.connect(dsn) as conn:
        if ja_carregado(conn, mes) and not (a.forcar or a.so_dicionarios):
            log(f"{mes} já carregado; nada a fazer")
            return 0
        arquivos = [(n, t) for n, t in listar(mes + "/") if tabela_do_zip(n)]
        if a.so_dicionarios:
            arquivos = [(n, t) for n, t in arquivos if tabela_do_zip(n) in DICIONARIOS]
        total = sum(t for _, t in arquivos)
        log(f"mês {mes}: {len(arquivos)} arquivos, {total / 1e9:.1f} GB compactados")

        preparar(conn)
        linhas: dict[str, int] = {}
        for nome, tamanho in sorted(arquivos, key=lambda x: x[1]):
            tabela = tabela_do_zip(nome)
            log(f"{nome} ({tamanho / 1e6:.0f} MB) -> {tabela}")
            caminho = baixar(mes, nome, tamanho)
            with conn.cursor() as cur:
                n = copiar_zip(cur, tabela, caminho)
            conn.commit()
            linhas[tabela] = linhas.get(tabela, 0) + n
            log(f"  {n:,} linhas")
            if not MANTER_ZIPS:
                caminho.unlink()

        if a.so_dicionarios:
            log(f"teste ok, schema {SCHEMA_CARGA} mantido para conferência: {linhas}")
            return 0
        publicar(conn, mes, linhas)
    log(f"concluído: {json.dumps(linhas)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
