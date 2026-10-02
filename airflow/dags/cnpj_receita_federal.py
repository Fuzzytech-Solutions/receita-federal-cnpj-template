"""Espelho mensal do CNPJ da Receita Federal.

Roda todo dia às 03h. O loader sai em segundos quando o mês mais recente já
está no banco, então a carga pesada acontece só no dia em que a Receita publica.
"""
import os

import pendulum
from airflow import DAG
from airflow.providers.docker.operators.docker import DockerOperator
from docker.types import Mount

REPASSAR = ["DATABASE_URL", "CNPJ_SCHEMA", "CNPJ_MANTER_ZIPS", "RFB_WEBDAV_URL", "RFB_SHARE_TOKEN"]

with DAG(
    dag_id="cnpj_receita_federal",
    schedule="0 3 * * *",
    start_date=pendulum.datetime(2026, 1, 1, tz="America/Sao_Paulo"),
    catchup=False,
    max_active_runs=1,
    tags=["receita-federal", "cnpj"],
) as dag:
    DockerOperator(
        task_id="carregar_mes_mais_recente",
        image=os.environ.get("CNPJ_LOADER_IMAGE", "cnpj-loader:latest"),
        environment={k: os.environ.get(k, "") for k in REPASSAR},
        network_mode=os.environ.get("CNPJ_DOCKER_NETWORK", "bridge"),
        mounts=[Mount(target="/dados", source=os.environ["CNPJ_DADOS_HOST"], type="bind")]
        if os.environ.get("CNPJ_DADOS_HOST") else [],
        mem_limit="2g",
        docker_url="unix://var/run/docker.sock",
        auto_remove="success",
        mount_tmp_dir=False,
        execution_timeout=pendulum.duration(hours=12),
    )
