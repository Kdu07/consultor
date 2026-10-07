"""
Builder do system prompt.

Lê a parte fixa de docs/system_prompt_consultor_otimizado.md (acima do marcador
=== CONTEXTO DINÂMICO ===) e injeta o contexto dinâmico montado a partir do banco.
"""
import logging
import re
from pathlib import Path

from sqlmodel import Session, select

from ..database import engine
from ..models.alvo import AlvoAtivo, AlvoClasse
from ..models.config_rebalanceamento import ConfigRebalanceamento
from ..models.estrategia import EstrategiaInvestimento, PlanoFuturo, StatusPlano
from ..models.perfil_risco import PerfilRisco

logger = logging.getLogger(__name__)

_SP_PATH = Path(__file__).parent.parent.parent / "docs" / "system_prompt_consultor_otimizado.md"
_MARKER = "=== CONTEXTO DINÂMICO ==="
# O marcador só conta sozinho na linha — ver _fixed_part.
_RE_MARKER = re.compile(rf"^{re.escape(_MARKER)}[ \t]*$", re.MULTILINE)


# Cache em memória — reconstruído a cada chamada (sessão nova pode ter perfil atualizado)
# Para esta escala (single-user) reconstruir é trivial.


def _fixed_part() -> str:
    """
    Retorna a parte fixa do system prompt (tudo antes do marcador).

    O marcador conta só sozinho na linha: o próprio .md o cita na nota "Como usar" da
    linha 3. Um `find` simples parava ali — de 06/2026 a 10/2026 o modelo recebeu só 101
    caracteres de parte fixa, sem persona, guardrails nem princípios das tools.
    """
    text = _SP_PATH.read_text(encoding="utf-8")
    achado = _RE_MARKER.search(text)
    if achado is None:
        logger.warning("Marcador '%s' não encontrado em system_prompt_consultor_otimizado.md", _MARKER)
        return text.strip()
    return text[:achado.start()].strip()


def _build_dynamic(session: Session) -> str:
    """Monta o bloco de contexto dinâmico a partir do banco."""
    lines: list[str] = []

    # --- Perfil de risco ---
    perfil = session.exec(select(PerfilRisco)).first()
    perfil_texto = perfil.texto.strip() if perfil and perfil.texto.strip() else "(perfil de risco não definido)"
    obs_livres = perfil.observacoes_livres.strip() if perfil and perfil.observacoes_livres.strip() else "—"

    # --- Alvos por classe ---
    alvos_classe = session.exec(select(AlvoClasse)).all()
    if alvos_classe:
        alvos_classe_txt = "\n".join(
            f"- {a.classe.value}: **{a.percentual:.0f}%**" + (f" — {a.notas}" if a.notas else "")
            for a in sorted(alvos_classe, key=lambda x: -x.percentual)
        )
    else:
        alvos_classe_txt = "(alvos por classe não definidos)"

    # --- Alvos por ativo ---
    alvos_ativo = session.exec(select(AlvoAtivo)).all()
    if alvos_ativo:
        alvos_ativo_txt = "\n".join(
            f"- {a.identificador}: **{a.percentual:.1f}%**" + (f" — {a.notas}" if a.notas else "")
            for a in sorted(alvos_ativo, key=lambda x: -x.percentual)
        )
    else:
        alvos_ativo_txt = "(alvos por ativo não definidos — a definir)"

    # --- Config de rebalanceamento ---
    cfg = session.exec(select(ConfigRebalanceamento)).first()
    if cfg:
        config_txt = (
            f"- Regra 5/25: {cfg.banda_absoluta_pp:.0f} p.p. absolutos "
            f"OU {cfg.banda_relativa_pct:.0f}% relativos ao alvo (o que vier primeiro)\n"
            f"- Cadência: avaliar a cada {cfg.cadencia_dias} dias\n"
            f"- Piso de irrelevância: R$ {cfg.piso_reais:.0f} ou {cfg.piso_percentual:.1f}% da carteira"
        )
    else:
        config_txt = "(configuração de rebalanceamento não definida)"

    lines.append("*(contexto específico do usuário, montado em runtime a partir do banco)*\n")
    lines.append("## Perfil de risco do investidor\n")
    lines.append(perfil_texto)
    lines.append("\n## Alocação-alvo\n")
    lines.append("**Por classe:**")
    lines.append(alvos_classe_txt)
    lines.append("\n**Por ativo:**")
    lines.append(alvos_ativo_txt)
    lines.append("\n## Bandas de rebalanceamento configuradas\n")
    lines.append(config_txt)
    lines.append("\n## Observações do usuário\n")
    lines.append(obs_livres)

    # --- Tese da estratégia ---
    estrategia = session.exec(select(EstrategiaInvestimento)).first()
    tese_txt = estrategia.tese.strip() if estrategia and estrategia.tese.strip() else "(tese de investimento não definida ainda)"
    version_txt = f" (v{estrategia.version})" if estrategia else ""
    lines.append(f"\n## Tese da estratégia{version_txt}\n")
    lines.append(tese_txt)

    # --- Planos futuros ativos ---
    planos = (
        session.exec(
            select(PlanoFuturo).where(PlanoFuturo.status == StatusPlano.ATIVO)
        ).all()
        if estrategia else []
    )
    if planos:
        planos_lines = []
        for p in planos:
            linha = f"- [id={p.id}] {p.descricao}"
            if p.gatilho:
                linha += f" | gatilho: {p.gatilho}"
            if p.horizonte:
                linha += f" | horizonte: {p.horizonte}"
            planos_lines.append(linha)
        lines.append("\n## Planos futuros\n")
        lines.append("\n".join(planos_lines))
    else:
        lines.append("\n## Planos futuros\n")
        lines.append("(nenhum plano futuro registrado)")

    return "\n".join(lines)


def build_system_prompt() -> str:
    """
    Monta o system prompt completo:
      [parte fixa do arquivo .md]
      === CONTEXTO DINÂMICO ===
      [contexto dinâmico do banco]
    """
    fixed = _fixed_part()
    with Session(engine) as session:
        dynamic = _build_dynamic(session)

    prompt = f"{fixed}\n\n{_MARKER}\n{dynamic}"
    logger.debug("system_prompt: %d chars (%d fixed + %d dynamic)", len(prompt), len(fixed), len(dynamic))
    return prompt


def build_system_blocks() -> list[dict]:
    """
    O mesmo prompt de build_system_prompt, em dois blocos para o cache de prompt da API.

    A parte fixa (~6 mil tokens, igual em toda chamada) leva o `cache_control`; o contexto
    dinâmico (perfil, alvos, tese, planos — muda quando o dono edita) fica depois do ponto
    de cache. As tools vêm antes do system no prefixo e entram no cache junto. Cada
    iteração do loop reenvia tudo: sem cache, a parte fixa seria cobrada inteira a cada
    chamada.
    """
    fixed = _fixed_part()
    with Session(engine) as session:
        dynamic = _build_dynamic(session)
    return [
        {"type": "text", "text": fixed, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": f"{_MARKER}\n{dynamic}"},
    ]
