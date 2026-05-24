"""MySQL connection configuration."""
from __future__ import annotations

from dataclasses import dataclass
import os
from urllib.parse import parse_qsl, urlparse


@dataclass(frozen=True)
class MySQLConfig:
    host: str
    port: int
    database: str
    username: str
    password: str
    charset: str = "utf8mb4"

    @classmethod
    def from_jdbc_url(
        cls,
        jdbc_url: str,
        username: str,
        password: str,
        database: str = "openstockagent",
    ) -> "MySQLConfig":
        url = jdbc_url.removeprefix("jdbc:")
        parsed = urlparse(url)
        query = dict(parse_qsl(parsed.query))
        parsed_database = parsed.path.strip("/") or database
        return cls(
            host=parsed.hostname or "127.0.0.1",
            port=parsed.port or 3306,
            database=parsed_database,
            username=username,
            password=password,
            charset=query.get("characterEncoding", "utf8mb4"),
        )

    @classmethod
    def from_env(cls) -> "MySQLConfig":
        return cls.from_jdbc_url(
            os.getenv("OPENSTOCKAGENT_MYSQL_URL", "jdbc:mysql://127.0.0.1:13306/openstockagent"),
            username=os.getenv("OPENSTOCKAGENT_MYSQL_USER", "root"),
            password=os.getenv("OPENSTOCKAGENT_MYSQL_PASSWORD", "123456"),
            database=os.getenv("OPENSTOCKAGENT_MYSQL_DATABASE", "openstockagent"),
        )

    def to_connection_kwargs(self) -> dict:
        return {
            "host": self.host,
            "port": self.port,
            "user": self.username,
            "password": self.password,
            "database": self.database,
            "charset": self.charset,
            "autocommit": False,
        }
