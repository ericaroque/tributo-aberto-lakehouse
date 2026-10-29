
import os
import re
import requests

from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Tributo360 API")

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
