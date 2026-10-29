import os
import re
import requests

from collections import defaultdict
from threading import Lock
from time import monotonic

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


app = FastAPI(title="Tributo360 API")

# Segurança: consultas desabilitadas por padrão
CONSULTAS_HABILITADAS = (
    os.getenv("CONSULTAS_HABILITADAS", "false").lower() == "true"
)

# Limite provisório por IP
LIMITE_CONSULTAS = 3
JANELA_SEGUNDOS = 3600

historico_consultas = defaultdict(list)
controle_lock = Lock()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://ericaroque.github.io"],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

DATABRICKS_HOST = (
    "https://dbc-d54bfe5c-282f.cloud.databricks.com"
)

JOB_ID = 487951552436515


class NotaFiscal(BaseModel):
    chave_acesso: str
    turnstile_token: str


@app.get("/health")
def health():
    return {"status": "online"}


@app.post("/consultar-nota")
def consultar_nota(
    nota: NotaFiscal,
    request: Request
):

    # 1. Bloquear consultas pagas por padrão
    if not CONSULTAS_HABILITADAS:
        raise HTTPException(
            status_code=503,
            detail="Consultas temporariamente desabilitadas."
        )

    # 2. Validar a chave da nota fiscal
    chave = nota.chave_acesso.strip()

    if not re.fullmatch(r"\d{44}", chave):
        raise HTTPException(
            status_code=400,
            detail="Chave inválida."
        )

    # 3. Exigir token do Cloudflare
    if not nota.turnstile_token.strip():
        raise HTTPException(
            status_code=400,
            detail="Token de segurança não informado."
        )

    # 4. Validar Turnstile no servidor
    try:
        verificacao = requests.post(
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
            data={
                "secret": os.environ["TURNSTILE_SECRET_KEY"],
                "response": nota.turnstile_token
            },
            timeout=10
        )

        verificacao.raise_for_status()
        resultado_turnstile = verificacao.json()

    except (requests.RequestException, ValueError):
        raise HTTPException(
            status_code=503,
            detail="Falha na verificação de segurança."
        )

    if (
        resultado_turnstile.get("success") is not True
        or resultado_turnstile.get("hostname")
        != "ericaroque.github.io"
    ):
        raise HTTPException(
            status_code=403,
            detail="Verificação de segurança inválida."
        )

    # 5. Limite provisório por IP
    ip = request.client.host if request.client else "desconhecido"
    agora = monotonic()

    with controle_lock:
        historico_consultas[ip] = [
            instante
            for instante in historico_consultas[ip]
            if agora - instante < JANELA_SEGUNDOS
        ]

        if len(historico_consultas[ip]) >= LIMITE_CONSULTAS:
            raise HTTPException(
                status_code=429,
                detail="Limite de 3 consultas por hora atingido."
            )

        historico_consultas[ip].append(agora)

    # 6. Acionar Databricks
    token = os.environ["DATABRICKS_TOKEN"]

    try:
        response = requests.post(
            f"{DATABRICKS_HOST}/api/2.2/jobs/run-now",
            headers={
                "Authorization": f"Bearer {token}"
            },
            json={
                "job_id": JOB_ID,
                "job_parameters": {
                    "chave_acesso": chave
                }
            },
            timeout=30
        )

        response.raise_for_status()

        return {
            "status": "submitted",
            "run_id": response.json()["run_id"]
        }

    except requests.RequestException:
        raise HTTPException(
            status_code=502,
            detail="Falha ao acionar o Databricks."
        )
