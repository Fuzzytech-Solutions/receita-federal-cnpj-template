# Espelho do CNPJ da Receita Federal (template)

Baixa todo mês os [dados abertos do CNPJ](https://www.gov.br/receitafederal/pt-br/assuntos/orientacao-tributaria/cadastros/consultas/dados-publicos-cnpj)
e mantém uma cópia consultável num Postgres: empresas, estabelecimentos, sócios,
Simples/MEI e os dicionários (CNAE, municípios, naturezas etc.).

Use o botão **Use this template** do GitHub para criar o seu repositório.

## O que vem pronto

| Peça | O que faz |
|---|---|
| `postgres` (compose) | Banco Postgres 16 já ajustado para carga pesada |
| `loader/` | Script Python que lista, baixa, carrega e publica o mês |
| `airflow/` (opcional) | Airflow que roda o loader todo dia às 03h |

A Receita publica uma vez por mês. O agendamento é diário porque o loader sai em
segundos quando o mês mais recente já está no banco: a carga pesada só acontece
no dia em que sai o mês novo, sem você precisar adivinhar a data.

## Requisitos

- Docker e Docker Compose
- ~40 GB livres para o banco e ~7 GB temporários para os `.zip`
- Uma carga completa leva de 2 a 6 horas, conforme disco e rede

## Passo a passo

```bash
git clone https://github.com/<voce>/<seu-repo>.git && cd <seu-repo>
cp .env.example .env            # troque as duas senhas
docker compose up -d postgres
docker compose build loader

# 1) teste rápido (segundos): carrega só os dicionários
docker compose run --rm loader --so-dicionarios

# 2) carga completa do mês mais recente
docker compose run --rm loader
```

Agendado pelo Airflow (em vez do passo 2):

```bash
docker compose --profile airflow up -d
# http://localhost:8080  (usuário e senha do .env) -> ative a DAG cnpj_receita_federal
```

Sem Airflow, um cron no servidor resolve igual:

```cron
0 3 * * * cd /caminho/do/repo && docker compose run --rm loader >> carga.log 2>&1
```

### Opções do loader

| Comando | Efeito |
|---|---|
| `--listar` | mostra os meses publicados |
| `--mes 2026-08` | carrega um mês específico |
| `--forcar` | recarrega mesmo se o mês já consta |
| `--so-dicionarios` | carga de teste, não mexe no schema de produção |

Para usar um Postgres que você já tem, aponte `DATABASE_URL` no `.env` para ele e
não suba o serviço `postgres`.

## Como a carga funciona

1. Lista as pastas `AAAA-MM` no compartilhamento público da Receita (WebDAV).
2. Se o mês já está em `receita_federal_controle.cargas`, para.
3. Baixa cada `.zip` (retoma do ponto onde parou se a conexão cair), decodifica
   de **latin-1** e faz `COPY` em `receita_federal_carga`.
4. Cria índices e troca `receita_federal_carga` → `receita_federal` numa transação.
   Quem consulta nunca vê base pela metade; se algo falhar, o mês anterior fica intacto.

## O que fica no banco

Schema `receita_federal`:

- Tabelas cruas, todas as colunas como `text`, idênticas ao layout da Receita:
  `empresas`, `estabelecimentos`, `socios`, `simples`, `cnaes`, `motivos`,
  `municipios`, `naturezas`, `paises`, `qualificacoes`.
- `v_estabelecimentos`: CNPJ completo, razão social, situação por extenso, datas
  como `date`, CNAE e município com descrição, telefones com DDD, capital `numeric`.
- `v_socios`: sócios com qualificação por extenso.

```sql
-- revendas de carro ativas por UF
SELECT uf, count(*)
FROM receita_federal.v_estabelecimentos
WHERE situacao_descricao = 'ATIVA'
  AND cnae_fiscal_principal IN ('4511101', '4511102')
GROUP BY uf ORDER BY 2 DESC;
```

## Armadilhas dos dados da Receita

- **CNPJ não é empresa.** `cnpj_basico` (8 dígitos) é a empresa; cada linha de
  `estabelecimentos` é matriz ou filial.
- **CNAE secundário é texto separado por vírgula.** Use `cnaes_secundarios` da view
  (array) ou `~ '(^|,)4511102(,|$)'`; nunca `LIKE '%4511102%'`.
- **Telefone vem com 8 dígitos**, sem o nono dígito do celular. Número local
  começando em 6–9 é celular: acrescente o `9`.
- **Datas `00000000`** viram `NULL` na view.
- A base traz **todas as situações** (ativa, baixada, inapta...). Filtre por
  `situacao_descricao = 'ATIVA'` quando precisar.

## Se a Receita mudar o endereço

A fonte fica em `RFB_WEBDAV_URL` e `RFB_SHARE_TOKEN` no `.env`. O token é o final
do link público de compartilhamento (`.../index.php/s/<token>`). Troque ali; o
código não muda.

## Licença

MIT. Os dados são públicos, publicados pela Receita Federal do Brasil.
