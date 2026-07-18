from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Also exports provider API keys into os.environ, where pydantic-ai's model
# providers look for them.
load_dotenv()


class Settings(BaseSettings):
    agent_model: str = Field(
        default="",
        description="Explicit pydantic-ai model string, e.g. openai:gpt-5.2",
    )
    openai_api_key: str = ""
    anthropic_api_key: str = ""

    db_path: str = Field(default="tasklet.db", description="SQLite database file")
    redis_url: str = Field(
        default="",
        description="Switch the channel layer to Redis pub/sub, e.g. redis://localhost:6379",
    )
    cors_origins: list[str] = ["http://localhost:5173"]
    send_completion: bool = Field(
        default=False,
        description="Emit chanx completion signals (used by the test communicator)",
    )

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def resolved_model(self) -> str:
        if self.agent_model:
            return self.agent_model
        if self.openai_api_key:
            return "openai:gpt-5.2"
        if self.anthropic_api_key:
            return "anthropic:claude-sonnet-4-6"
        return "test"


settings = Settings()
