from unittest.mock import MagicMock, patch

from app.services import mesh_client


def _fake_embeddings_response(vectors: list[list[float]]) -> MagicMock:
    response = MagicMock()
    response.data = [MagicMock(embedding=vector) for vector in vectors]
    return response


def test_embed_calls_mesh_with_configured_model_and_returns_vector():
    mesh_client._client.cache_clear()

    with patch("app.services.mesh_client.OpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_client.embeddings.create.return_value = _fake_embeddings_response([[0.1, 0.2, 0.3]])
        mock_openai_cls.return_value = mock_client

        result = mesh_client.embed("agentic AI course")

        assert result == [0.1, 0.2, 0.3]
        mock_client.embeddings.create.assert_called_once()
        _, kwargs = mock_client.embeddings.create.call_args
        assert kwargs["input"] == ["agentic AI course"]

    mesh_client._client.cache_clear()


def test_embed_many_preserves_order_for_multiple_inputs():
    mesh_client._client.cache_clear()

    with patch("app.services.mesh_client.OpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_client.embeddings.create.return_value = _fake_embeddings_response([[1.0], [2.0]])
        mock_openai_cls.return_value = mock_client

        result = mesh_client.embed_many(["first", "second"])

        assert result == [[1.0], [2.0]]

    mesh_client._client.cache_clear()
