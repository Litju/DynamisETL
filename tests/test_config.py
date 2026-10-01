import pytest
from sqlalchemy.engine import make_url

from dynamis.config import (
    ENV_DATABASE_NAME,
    ENV_MIGRATION_POSTGRES_URL,
    ENV_POSTGRES_URL,
    ConfigurationError,
    resolved_environ,
)


def test_database_name_override_targets_pooled_and_direct_urls():
    values = resolved_environ(
        {
            ENV_DATABASE_NAME: "dynamis_sample",
            ENV_POSTGRES_URL: "postgresql://ep-example-pooler.us-east-1.aws.neon.tech/neondb?sslmode=require",
            "DATABASE_URL_UNPOOLED": "postgresql://ep-example.us-east-1.aws.neon.tech/neondb?sslmode=require",
        }
    )

    assert make_url(values[ENV_POSTGRES_URL]).database == "dynamis_sample"
    assert make_url(values[ENV_MIGRATION_POSTGRES_URL]).database == "dynamis_sample"
    assert make_url(values[ENV_POSTGRES_URL]).host == "ep-example-pooler.us-east-1.aws.neon.tech"
    assert make_url(values[ENV_MIGRATION_POSTGRES_URL]).host == "ep-example.us-east-1.aws.neon.tech"


def test_database_name_override_rejects_invalid_identifier():
    with pytest.raises(ConfigurationError, match="DYNAMIS_DATABASE_NAME"):
        resolved_environ({ENV_DATABASE_NAME: "dynamis-sample"})
