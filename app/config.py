from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Anthropic
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-6"

    # Brapi (produção — deixar vazio durante validação em modo yfinance)
    brapi_token: str = ""

    # Banco
    database_url: str = "sqlite:///data/carteira.db"

    # Loop do agente
    agent_max_iters: int = 6

    # Cache de cotações
    quote_cache_ttl_seconds: int = 900  # 15 min

    # Provider ativo de RV: "yfinance" ou "brapi"
    # Mude para "brapi" quando contratar o plano e preencher BRAPI_TOKEN
    price_provider: str = "yfinance"


@lru_cache
def get_settings() -> Settings:
    return Settings()
