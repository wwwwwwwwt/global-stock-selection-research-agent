from openstockagent.database.mysql import MySQLConfig


def test_mysql_config_parses_jdbc_url_with_default_database():
    config = MySQLConfig.from_jdbc_url(
        "jdbc:mysql://127.0.0.1:13306/",
        username="root",
        password="123456",
        database="openstockagent",
    )

    assert config.host == "127.0.0.1"
    assert config.port == 13306
    assert config.database == "openstockagent"
    assert config.username == "root"
    assert config.password == "123456"


def test_mysql_config_uses_database_from_jdbc_path():
    config = MySQLConfig.from_jdbc_url(
        "jdbc:mysql://127.0.0.1:13306/stock_agent",
        username="root",
        password="123456",
    )

    assert config.database == "stock_agent"
