from ingester.config import load_config


def test_load_example_config() -> None:
    config = load_config("config.example.yaml")

    assert config.qdrant.host == "localhost"
    assert config.embedding.backend == "local"
    assert config.embedding.local.batch_size == 32
    assert config.sqlite.path == "./data/index.db"
    assert config.qdrant.port == 6333
    assert config.qdrant.collection == "file_index"
    assert config.llm.backend == "api"
    assert config.scheduler.watch_interval_seconds == 300
    assert len(config.watched_dirs) > 0
