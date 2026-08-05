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


def _fake_chat_response(content: str) -> MagicMock:
    response = MagicMock()
    response.choices = [MagicMock(message=MagicMock(content=content))]
    return response


def test_chat_returns_message_content_and_uses_configured_model():
    mesh_client._client.cache_clear()

    with patch("app.services.mesh_client.OpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _fake_chat_response("hello back")
        mock_openai_cls.return_value = mock_client

        result = mesh_client.chat([{"role": "user", "content": "hi"}])

        assert result == "hello back"
        _, kwargs = mock_client.chat.completions.create.call_args
        assert kwargs["model"] == mesh_client.settings.mesh_chat_model
        assert "response_format" not in kwargs

    mesh_client._client.cache_clear()


def test_chat_json_mode_sets_response_format():
    mesh_client._client.cache_clear()

    with patch("app.services.mesh_client.OpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _fake_chat_response('{"a": 1}')
        mock_openai_cls.return_value = mock_client

        mesh_client.chat([{"role": "user", "content": "hi"}], json_mode=True)

        _, kwargs = mock_client.chat.completions.create.call_args
        assert kwargs["response_format"] == {"type": "json_object"}

    mesh_client._client.cache_clear()
