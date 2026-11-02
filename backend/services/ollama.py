
import logging
import httpx

from backend.config import OLLAMA_URL

logger = logging.getLogger(__name__)

# Timeout configuration
CONNECT_TIMEOUT = 15.0
READ_TIMEOUT = 420.0
WRITE_TIMEOUT = 60.0
POOL_TIMEOUT = 15.0

# Initial CPU-friendly generation configuration
GENERATION_OPTIONS = {
    "temperature": 0,
    "num_predict": 2200,
    "num_ctx": 4096,
}


def get_timeout():
    return httpx.Timeout(
        connect=CONNECT_TIMEOUT,
        read=READ_TIMEOUT,
        write=WRITE_TIMEOUT,
        pool=POOL_TIMEOUT,
    )


class OllamaProvider:

    def __init__(self, model: str):
        self.model = model
        self.base_url = OLLAMA_URL.rstrip("/")

    async def available(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(
                    f"{self.base_url}/api/tags"
                )
                response.raise_for_status()

                models = response.json().get("models", [])
                available_models = [
                    item.get("name", "") for item in models
                ]

                return any(
                    name == self.model
                    or name == f"{self.model}:latest"
                    for name in available_models
                )

        except (httpx.HTTPError, ValueError):
            logger.exception("Ollama availability check failed")
            return False

    async def _generate(
        self,
        prompt: str,
        system: str = "",
        json_mode: bool = False,
    ) -> str:

        payload = {
            "model": self.model,
            "prompt": prompt,
            "system": system,
            "stream": False,
            "think": False,
            "options": GENERATION_OPTIONS,
        }

        if json_mode:
            payload["format"] = "json"

        logger.info(
            "Sending generation request | Model: %s | JSON mode: %s",
            self.model,
            json_mode,
        )

        try:
            async with httpx.AsyncClient(
                timeout=get_timeout()
            ) as client:

                response = await client.post(
                    f"{self.base_url}/api/generate",
                    json=payload,
                )
                response.raise_for_status()

                result = response.json()
                generated_text = result.get("response", "")
                thinking = result.get("thinking", "")

                logger.info(
                    "Ollama metadata | Done: %s | Reason: %s | "
                    "Response chars: %s | Thinking chars: %s | "
                    "Eval tokens: %s | Prompt tokens: %s",
                    result.get("done"),
                    result.get("done_reason"),
                    len(generated_text),
                    len(thinking),
                    result.get("eval_count"),
                    result.get("prompt_eval_count"),
                )

                if not isinstance(generated_text, str):
                    raise ValueError(
                        "Ollama response field is not a string"
                    )

                if not generated_text.strip():
                    raise ValueError(
                        "Ollama returned an empty response. "
                        f"Thinking chars: {len(thinking)}. "
                        f"Done reason: {result.get('done_reason')}."
                    )

                logger.info(
                    "Generation successful | Characters: %s",
                    len(generated_text),
                )

                return generated_text

        except httpx.TimeoutException as exc:
            logger.exception("Ollama request timed out")
            raise RuntimeError(
                f"Ollama timed out after {READ_TIMEOUT} seconds"
            ) from exc

        except httpx.HTTPStatusError as exc:
            logger.exception("Ollama returned HTTP error")
            raise RuntimeError(
                f"Ollama HTTP {exc.response.status_code}: "
                f"{exc.response.text[:1000]}"
            ) from exc

        except httpx.RequestError as exc:
            logger.exception("Ollama connection failed")
            raise RuntimeError(
                f"Ollama connection error: {str(exc)}"
            ) from exc

    async def generate(
        self,
        prompt: str,
        system: str = "",
    ) -> str:
        return await self._generate(
            prompt=prompt,
            system=system,
            json_mode=True,
        )

    async def generate_text(
        self,
        prompt: str,
        system: str = "",
    ) -> str:
        return await self._generate(
            prompt=prompt,
            system=system,
            json_mode=False,
        )
