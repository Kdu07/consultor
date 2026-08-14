"""
TesouroProvider — preço diário oficial do Tesouro Direto (PLANO §6.7).
Fonte: Tesouro Transparente (dados abertos do Tesouro Nacional / B3).
Endpoint: https://www.tesourodireto.com.br/json/br/com/b3/tesouro/bond/detail/BondDetailList.json
Preço de fim de dia (não tick ao vivo) — adequado à cadência mensal.
"""
import logging
import re
import unicodedata
from datetime import datetime, timezone
from typing import Optional

import httpx

from .base import Quote

logger = logging.getLogger(__name__)

_URL = "https://www.tesourodireto.com.br/json/br/com/b3/tesouro/bond/detail/BondDetailList.json"


def _chave(nome: str) -> tuple[str, str]:
    """
    Nome do título → (tipo, ano). É assim que o casamento acontece (gap G4):
    'Tesouro IPCA+ 2029' e 'TESOURO IPCA 2029' caem na mesma chave ('tesouro ipca', '2029'),
    enquanto 'Tesouro IPCA+ com Juros Semestrais 2029' continua sendo outro título.

    O nome vem do parser do extrato XLSX, que o monta a partir da sigla (LFT/LTN/NTNB-P)
    e do vencimento exato — não há mais heurística de texto livre no meio do caminho.
    """
    n = unicodedata.normalize("NFKD", nome or "")
    n = "".join(c for c in n if not unicodedata.combining(c))
    n = n.lower().replace("+", " ")
    m = re.search(r"\b(\d{4})\b", n)
    ano = m.group(1) if m else ""
    tipo = re.sub(r"\b\d{4}\b", " ", n)
    tipo = re.sub(r"[^a-z ]", " ", tipo)
    tipo = re.sub(r"\s+", " ", tipo).strip()
    return tipo, ano


class TesouroProvider:
    source = "tesouro"
    _cache: dict[str, dict] = {}                    # nome uppercase → dados brutos
    _por_chave: dict[tuple[str, str], dict] = {}    # (tipo, ano) → dados brutos
    _fetched_at: Optional[datetime] = None

    def _fetch_all(self) -> bool:
        try:
            with httpx.Client(timeout=12.0) as client:
                resp = client.get(_URL, headers={"User-Agent": "consultor-app/0.1"})
                resp.raise_for_status()
                data = resp.json()

            titulos = (
                data.get("response", {})
                    .get("TrsrBdTradgList", [])
            )
            if not titulos:
                logger.warning("TesouroProvider: lista vazia na resposta.")
                return False

            self._cache.clear()
            self._por_chave.clear()
            for item in titulos:
                bond = item.get("TrsrBd", {})
                nm = bond.get("nm", "")           # ex.: "Tesouro IPCA+ 2035"
                if not nm:
                    continue
                self._cache[nm.upper().strip()] = bond
                self._por_chave[_chave(nm)] = bond

            self._fetched_at = datetime.now(timezone.utc)
            logger.info("TesouroProvider: %d títulos carregados.", len(self._cache))
            return True
        except Exception as e:
            logger.warning("TesouroProvider: falha ao buscar dados — %s", e)
            return False

    def _find(self, ticker: str) -> Optional[dict]:
        """
        Casamento por (tipo, ano) — determinístico. Cai para nome exato e depois para
        busca parcial, que ainda atende quem digita 'IPCA 2029' no chat.
        """
        key = ticker.upper().strip()
        if key in self._cache:
            return self._cache[key]

        tipo, ano = _chave(ticker)
        if ano:
            achado = self._por_chave.get((tipo, ano))
            if achado:
                return achado

        for k, v in self._cache.items():
            if key in k:
                return v

        if ano:
            # último recurso: mesmo ano e tipos compatíveis por prefixo
            for (t, a), v in self._por_chave.items():
                if a == ano and (t.startswith(tipo) or tipo.startswith(t)):
                    return v
        return None

    def quote(self, ticker: str) -> Optional[Quote]:
        if not self._cache:
            if not self._fetch_all():
                return None

        bond = self._find(ticker)
        if not bond:
            # Não é erro fatal: o chamador cai para o valor do extrato. Acontece com
            # título fora de negociação, que some da lista pública do Tesouro.
            logger.warning(
                "TesouroProvider: '%s' não está na lista do Tesouro Direto — "
                "a posição vai valer pelo saldo do extrato.", ticker,
            )
            return None

        try:
            price = float(bond.get("untrInvstmtVal", 0) or 0)
            if price <= 0:
                # Tenta preço unitário bruto
                price = float(bond.get("anulInvstmtRate", 0) or 0)
            if price <= 0:
                logger.warning("TesouroProvider: preço zero para '%s'", ticker)
                return None

            dt_str = bond.get("qtnDtTm", "")
            try:
                as_of = datetime.strptime(dt_str[:10], "%Y-%m-%d")
            except Exception:
                as_of = self._fetched_at or datetime.now(timezone.utc)

            nome = bond.get("nm", ticker)
            q = Quote(
                ticker=ticker.upper(),
                price=round(price, 2),
                source=self.source,
                as_of=as_of,
                nome=nome,
            )
            logger.info(
                "tesouro: %s = R$ %.2f (pregão %s)",
                nome, q.price, as_of.strftime("%Y-%m-%d"),
            )
            return q
        except Exception as e:
            logger.warning("TesouroProvider: erro ao parsear '%s' — %s", ticker, e)
            return None

    def enrich(self, ticker: str) -> Optional[Quote]:
        return self.quote(ticker)

    def list_titulos(self) -> list[str]:
        """Retorna lista de nomes dos títulos disponíveis."""
        if not self._cache:
            self._fetch_all()
        return list(self._cache.keys())
