"""One bounded HTTP attempt. No implicit retries or redirect forwarding."""
import json

import httpx

from .contracts import ApprovedPayload, ModelReply, Settings, Usage


class TransportError(Exception):
    def __init__(self, code: str, ambiguous: bool = False, retry_after: int = 0):
        self.code = code
        self.ambiguous = ambiguous
        self.retry_after = retry_after
        super().__init__(code)


async def call_model(payload: ApprovedPayload, config: Settings) -> ModelReply:
    if not isinstance(payload, ApprovedPayload):
        raise TypeError("Only approved payloads may reach transport")
    headers = {"Content-Type": "application/json"}
    if config.api_key:
        headers["Authorization"] = "Bearer " + config.api_key.get_secret_value()
    try:
        async with httpx.AsyncClient(timeout=config.timeout_seconds, follow_redirects=False,
                                     verify=True, trust_env=False) as client:
            async with client.stream("POST", payload.endpoint, headers=headers, content=payload.body) as response:
                status = response.status_code
                retry_after = response.headers.get("retry-after", "")
                if status == 429:
                    raise TransportError("rate_limited", retry_after=min(int(retry_after), 30)
                                         if retry_after.isdigit() else 0)
                if status in (401, 403):
                    raise TransportError("authentication")
                if 300 <= status < 400:
                    raise TransportError("redirect_denied")
                if status >= 500:
                    raise TransportError("server_uncertain", ambiguous=True)
                if status == 400 and config.schema_mode != "text":
                    raise TransportError("schema_mode_unsupported_use_text")
                if status >= 400:
                    raise TransportError("http_rejected")
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > 524288:
                        raise TransportError("response_too_large")
        obj = json.loads(data)
        choice = obj["choices"][0]
        text = choice["message"]["content"]
        if not isinstance(text, str):
            raise ValueError()
        raw = obj.get("usage")
        if raw is None:
            usage = Usage()
        else:
            a, b = raw.get("prompt_tokens"), raw.get("completion_tokens")
            valid = type(a) is int and type(b) is int and a >= 0 and b >= 0
            usage = Usage(input_tokens=a if valid else None, output_tokens=b if valid else None,
                          complete=valid, source="provider" if valid else "invalid")
        request_id = obj.get("id")
        return ModelReply(text=text, usage=usage,
                          request_id=request_id if isinstance(request_id, str) else None,
                          finish_reason=choice.get("finish_reason"))
    except TransportError:
        raise
    except (httpx.TimeoutException, httpx.TransportError):
        raise TransportError("delivery_uncertain", ambiguous=True) from None
    except (ValueError, KeyError, IndexError, TypeError, json.JSONDecodeError):
        raise TransportError("invalid_provider_response") from None
