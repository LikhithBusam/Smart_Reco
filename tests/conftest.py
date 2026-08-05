from unittest.mock import AsyncMock, MagicMock


def make_mock_db() -> MagicMock:
    """add_all()/add() are sync on a real AsyncSession; commit/flush/execute are async.
    execute()'s return value (a Result) is sync itself (.scalars().all()/.first()) —
    AsyncMock auto-creates AsyncMock children, so it's forced to plain MagicMock here."""
    db = MagicMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock())
    return db


class FakeSessionCtx:
    def __init__(self, db: MagicMock):
        self._db = db

    async def __aenter__(self):
        return self._db

    async def __aexit__(self, *exc):
        return False
