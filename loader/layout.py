"""Layout dos arquivos de dados abertos do CNPJ (Receita Federal).

Todas as colunas entram como texto: a origem traz datas "00000000", capital
social com vírgula decimal e códigos com zero à esquerda. A tipagem fica nas
views de sql/views.sql, que podem ser recriadas sem recarregar nada.
"""

DICIONARIO = ["codigo", "descricao"]

TABELAS = {
    "empresas": [
        "cnpj_basico", "razao_social", "natureza_juridica", "qualificacao_responsavel",
        "capital_social", "porte_empresa", "ente_federativo_responsavel",
    ],
    "estabelecimentos": [
        "cnpj_basico", "cnpj_ordem", "cnpj_dv", "identificador_matriz_filial",
        "nome_fantasia", "situacao_cadastral", "data_situacao_cadastral",
        "motivo_situacao_cadastral", "nome_cidade_exterior", "pais",
        "data_inicio_atividade", "cnae_fiscal_principal", "cnae_fiscal_secundaria",
        "tipo_logradouro", "logradouro", "numero", "complemento", "bairro", "cep",
        "uf", "municipio", "ddd_1", "telefone_1", "ddd_2", "telefone_2",
        "ddd_fax", "fax", "correio_eletronico", "situacao_especial",
        "data_situacao_especial",
    ],
    "socios": [
        "cnpj_basico", "identificador_socio", "nome_socio_razao_social",
        "cpf_cnpj_socio", "qualificacao_socio", "data_entrada_sociedade", "pais",
        "representante_legal", "nome_do_representante",
        "qualificacao_representante_legal", "faixa_etaria",
    ],
    "simples": [
        "cnpj_basico", "opcao_pelo_simples", "data_opcao_simples",
        "data_exclusao_simples", "opcao_mei", "data_opcao_mei", "data_exclusao_mei",
    ],
    "cnaes": DICIONARIO,
    "motivos": DICIONARIO,
    "municipios": DICIONARIO,
    "naturezas": DICIONARIO,
    "paises": DICIONARIO,
    "qualificacoes": DICIONARIO,
}

INDICES = [
    "CREATE INDEX ON {s}.empresas (cnpj_basico)",
    "CREATE INDEX ON {s}.estabelecimentos (cnpj_basico)",
    "CREATE INDEX ON {s}.estabelecimentos (cnae_fiscal_principal)",
    "CREATE INDEX ON {s}.estabelecimentos (uf, municipio)",
    "CREATE INDEX ON {s}.estabelecimentos (situacao_cadastral)",
    "CREATE INDEX ON {s}.socios (cnpj_basico)",
    "CREATE INDEX ON {s}.simples (cnpj_basico)",
]


def tabela_do_zip(nome: str) -> str | None:
    """'Estabelecimentos3.zip' -> 'estabelecimentos'; desconhecido -> None."""
    base = nome.lower().removesuffix(".zip").rstrip("0123456789")
    return base if base in TABELAS else None
