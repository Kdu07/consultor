"""
TesouroProvider — preço diário oficial do Tesouro Direto (PLANO §6.7).
Fonte: Tesouro Transparente (dados abertos do Tesouro Nacional / B3).
Endpoint: https://www.tesourodireto.com.br/json/br/com/b3/tesouro/bond/detail/BondDetailList.json
Preço de fim de dia (não tick ao vivo) — adequado à cadência mensal.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx

from .base import Quote

logger = logging.getLogger(__name__)

_URL = "https://www.tesourodireto.com.br/json/br/com/b3/tesouro/bond/detail/BondDetailList.json"

# Mapeamento de nomes parciais (uppercase) → ticker normalizado interno
# O usuário pode referir "Tesouro IPCA+ 2035" ou "TESOURO IPCA+ 2035"
_ALIAS: dict[str, str] = {}  # populado dinamicamente no primeiro fetch


class TesouroProvider:
    source = "tesouro"
    _cache: dict[str, dict] = {}   # ticker normalizado → dados brutos
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
            for item in titulos:
                bond = item.get("TrsrBd", {})
                nm = bond.get("nm", "")           # ex.: "Tesouro IPCA+ 2035"
                key = nm.upper().strip()
                self._cache[key] = bond
                # Também indexa por nome simplificado
                _ALIAS[key] = key

            self._fetched_at = datetime.now(timezone.utc)
            logger.info("TesouroProvider: %d títulos carregados.", len(self._cache))
            return True
        except Exception as e:
            logger.warning("TesouroProvider: falha ao buscar dados — %s", e)
            return False

    def _find(self, ticker: str) -> Optional[dict]:
        """Busca tolerante: aceita nome completo ou parcial (case-insensitive)."""
        key = ticker.upper().strip()
        if key in self._cache:
            return self._cache[key]
        # busca parcial
        for k, v in self._cache.items():
            if key in k:
                return v
        return None

    def quote(self, ticker: str) -> Optional[Quote]:
        if not self._cache:
            if not self._fetch_all():
                return None

        bond = self._find(ticker)
        if not bond:
            logger.warning("TesouroProvider: título não encontrado para '%s'", ticker)
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
