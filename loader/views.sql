-- Views tipadas sobre as tabelas cruas. Recriadas a cada carga ({schema} é substituído).

CREATE OR REPLACE FUNCTION {schema}.data_rfb(t text) RETURNS date
LANGUAGE sql IMMUTABLE AS $$
  SELECT CASE WHEN t ~ '^\d{8}$' AND t <> '00000000' THEN to_date(t, 'YYYYMMDD') END
$$;

CREATE OR REPLACE VIEW {schema}.v_estabelecimentos AS
SELECT
  e.cnpj_basico || e.cnpj_ordem || e.cnpj_dv            AS cnpj,
  e.cnpj_basico,
  e.identificador_matriz_filial = '1'                    AS matriz,
  emp.razao_social,
  e.nome_fantasia,
  e.situacao_cadastral,
  CASE ltrim(e.situacao_cadastral, '0') WHEN '1' THEN 'NULA' WHEN '2' THEN 'ATIVA'
       WHEN '3' THEN 'SUSPENSA' WHEN '4' THEN 'INAPTA' WHEN '8' THEN 'BAIXADA'
       ELSE e.situacao_cadastral END                     AS situacao_descricao,
  {schema}.data_rfb(e.data_situacao_cadastral)           AS data_situacao_cadastral,
  {schema}.data_rfb(e.data_inicio_atividade)             AS data_inicio_atividade,
  e.cnae_fiscal_principal,
  c.descricao                                            AS cnae_descricao,
  string_to_array(NULLIF(e.cnae_fiscal_secundaria, ''), ',') AS cnaes_secundarios,
  e.tipo_logradouro, e.logradouro, e.numero, e.complemento, e.bairro, e.cep,
  e.uf,
  m.descricao                                            AS municipio,
  NULLIF(e.ddd_1 || e.telefone_1, '')                    AS telefone_1,
  NULLIF(e.ddd_2 || e.telefone_2, '')                    AS telefone_2,
  lower(NULLIF(e.correio_eletronico, ''))                AS email,
  emp.natureza_juridica,
  NULLIF(replace(emp.capital_social, ',', '.'), '')::numeric AS capital_social,
  emp.porte_empresa
FROM {schema}.estabelecimentos e
LEFT JOIN {schema}.empresas   emp ON emp.cnpj_basico = e.cnpj_basico
LEFT JOIN {schema}.cnaes      c   ON c.codigo = e.cnae_fiscal_principal
LEFT JOIN {schema}.municipios m   ON m.codigo = e.municipio;

CREATE OR REPLACE VIEW {schema}.v_socios AS
SELECT s.cnpj_basico, s.identificador_socio, s.nome_socio_razao_social,
       s.cpf_cnpj_socio, q.descricao AS qualificacao,
       {schema}.data_rfb(s.data_entrada_sociedade) AS data_entrada_sociedade,
       s.faixa_etaria
FROM {schema}.socios s
LEFT JOIN {schema}.qualificacoes q ON q.codigo = s.qualificacao_socio;
