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

Junto do preview viaja o `bruto` (ExtratoParsed.to_dict): o extrato inteiro como o
parser leu, incluindo o que o preview não mostra (movimentações). Ele nunca vai para o
modelo — serve para gravar_posicoes arquivar o mês em ExtratoImportado, já que o XLSX
foi descartado logo depois do parse.
"""
import logging
import threading
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_state: Optional[dict] = None


def set_preview(preview: dict, arquivo: str, bruto: Optional[dict] = None) -> dict:
    """
    Guarda o preview do último extrato enviado, substituindo o anterior.

    `bruto` é o ExtratoParsed.to_dict completo, para arquivamento. Opcional: gravação
    manual e testes montam o staging só com o preview.
    """
    global _state
    with _lock:
        _state = {
            "preview": preview,
            "bruto": bruto,
            "arquivo": arquivo,
            "recebido_em": datetime.now(timezone.utc).isoformat(),
        }
        logger.info(
            "extrato_staging: preview de '%s' armazenado (%d posicoes)",
            arquivo, len(preview.get("posicoes", [])),
        )
        return _state


def get() -> Optional[dict]:
    """Retorna {preview, bruto, arquivo, recebido_em} ou None se nada foi enviado."""
    with _lock:
        return _state


def clear() -> None:
    global _state
    with _lock:
        _state = None
        logger.info("extrato_staging: preview descartado")
