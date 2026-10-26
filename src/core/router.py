import asyncio
from dataclasses import dataclass


class RetryableProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProviderResult:
    text: str
    provider: str


class DemoProvider:
    """Deterministic local provider used to exercise routing without API credentials."""

    def __init__(self, name: str, *, fail: bool = False) -> None:
        self.name = name
        self.fail = fail

    async def complete(self, prompt: str, max_output_chars: int) -> ProviderResult:
        await asyncio.sleep(0)
        if self.fail:
            raise RetryableProviderError(f"{self.name} is temporarily unavailable")
        text = f"Demo response from {self.name}: {prompt}"[:max_output_chars]
        return ProviderResult(text=text, provider=self.name)


class ProviderRouter:
    def __init__(self, providers: list[DemoProvider]) -> None:
        if not providers:
            raise ValueError("at least one provider is required")
        if len({provider.name for provider in providers}) != len(providers):
            raise ValueError("provider names must be unique")
        self.providers = providers

    async def complete(
        self, prompt: str, preferred_provider: str | None, max_output_chars: int
    ) -> tuple[ProviderResult, int]:
        ordered = self.providers
        if preferred_provider:
            match = next(
                (p for p in self.providers if p.name == preferred_provider), None
            )
            if not match:
                raise ValueError(f"unknown provider '{preferred_provider}'")
            ordered = [match] + [p for p in self.providers if p is not match]

        retryable_failures = 0
        for provider in ordered:
            try:
                return (
                    await provider.complete(prompt, max_output_chars),
                    retryable_failures,
                )
            except RetryableProviderError:
                retryable_failures += 1
        raise RetryableProviderError("all demo providers are unavailable")
