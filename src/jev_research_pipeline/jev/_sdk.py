# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false
# Why: typesafe-sdk 0.7.1 declares JSONContent/JSONValue with string-forward-ref
# TypeAliasType, which pyright 1.1.414 resolves to Unknown, so every system_one() call is
# "partially unknown". This module is the single typed boundary around that call; the rest
# of the package sees only JevState and SystemOneResponse. Remove the directive when the
# SDK's aliases resolve (re-check on any typesafe-sdk bump).
"""Typed boundary over AsyncTypeSafeClient.system_one."""

from collections.abc import Mapping

import httpx2
from pydantic import JsonValue
from typesafe_sdk import AsyncTypeSafeClient, Choice, Noul, RetryPolicy, Score, SystemOneResponse

type JevState = dict[str, JsonValue]
"""Named JSON fields (vendor guidance: prefer named fields when state has several parts)."""


class SystemOne:
    def __init__(
        self,
        http_client: httpx2.AsyncClient,
        *,
        api_key: str,
        model: str,
        retry: RetryPolicy,
        timeout_s: float,
    ) -> None:
        self._client = AsyncTypeSafeClient(
            api_key=api_key, model=model, retry=retry, timeout=timeout_s, http_client=http_client
        )
        self._model = model

    async def ask(
        self, state: JevState, questions: Mapping[str, Noul | Score | Choice]
    ) -> SystemOneResponse:
        return await self._client.system_one(state, questions, model=self._model)

    async def aclose(self) -> None:
        await self._client.aclose()
