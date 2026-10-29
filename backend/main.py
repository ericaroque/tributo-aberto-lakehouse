
import os
import re
import requests

from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from collections import defaultdict
from time import monotonic
from threading import Lock

app = FastAPI(title="Tributo360 API")

LIMITE_CONSULTAS = 3
JANELA_SEGUNDOS = 3600

historico_consultas = defaultdict(list)
controle_lock = Lock()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://ericaroque.github.io"
    ],
    allow_methods=["POST", "GET"],
    allow_headers=["Content-Type", "X-Access-Key"],
)

DATABRICKS_HOST = (
    "https://dbc-d54bfe5c-282f.cloud.databricks.com"
)

JOB_ID = 487951552436515


class NotaFiscal(BaseModel):
    chave_acesso: str


@app.get("/health")
def health():
    return {"status": "online"}


@app.post("/consultar-nota")
def consultar_nota(
    nota: NotaFiscal,
    request: Request,
    x_access_key: str | None = Header(default=None)
):
    # Controle inicial de acesso para testes privados
    access_key = os.environ["TRIBUTO360_ACCESS_KEY"]

    if x_access_key != access_key:
        raise HTTPException(
            status_code=401,
            detail="Acesso não autorizado"
        )

    chave = nota.chave_acesso.strip()

    if not re.fullmatch(r"\d{44}", chave):
        raise HTTPException(
            status_code=400,
            detail="Chave inválida"
        )
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
            detail="Falha ao acionar o Databricks"
        )
