"""
Staging do extrato enviado pela UI.

O XLSX é binário e não pode trafegar pelo chat (guardrail 1 do PLANO_XLSX): o arquivo é
parseado no servidor por POST /extrato/upload e o PREVIEW fica aqui, em memória, até o
agente pedir via importar_extrato().

É um singleton de processo — o serviço é local e single-user (PLANO §4). Reiniciar o
servidor limpa o staging: a tool então orienta o usuário a subir o arquivo de novo.

O binário NÃO é guardado (contém nome, CPF e conta) — só o preview já estruturado.
Nenhuma escrita em banco acontece aqui: gravar continua exclusivo de gravar_posicoes,
depois do "sim" do usuário.
"""
import logging
import threading
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_state: Optional[dict] = None


def set_preview(preview: dict, arquivo: str) -> dict:
    """Guarda o preview do último extrato enviado, substituindo o anterior."""
    global _state
    with _lock:
        _state = {
            "preview": preview,
            "arquivo": arquivo,
            "recebido_em": datetime.now(timezone.utc).isoformat(),
        }
        logger.info(
            "extrato_staging: preview de '%s' armazenado (%d posicoes)",
            arquivo, len(preview.get("posicoes", [])),
        )
        return _state


def get() -> Optional[dict]:
    """Retorna {preview, arquivo, recebido_em} ou None se nada foi enviado."""
    with _lock:
        return _state


def clear() -> None:
    global _state
    with _lock:
        _state = None
        logger.info("extrato_staging: preview descartado")
