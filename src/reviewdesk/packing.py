"""Stable greedy packing, without splitting or truncation."""
import hashlib
import json
from collections.abc import Sequence

from .contracts import Bundle, Limits, SafeDocument

VERSION = "prompt-1"


def canonical(documents: Sequence[SafeDocument]) -> bytes:
    return json.dumps([d.model_dump(exclude={"content_hash"}) for d in documents],
                      sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()


def pack_documents(documents: Sequence[SafeDocument], limits: Limits) -> list[Bundle]:
    bundles: list[Bundle] = []
    group: list[SafeDocument] = []
    for doc in sorted(documents, key=lambda d: d.path):
        candidate = group + [doc]
        too_large = (len(candidate) > limits.max_bundle_files
                     or sum(len(d.patch.splitlines()) for d in candidate) > limits.max_bundle_patch_lines
                     or len(canonical(candidate)) > limits.max_bundle_code_bytes
                     or len(canonical(candidate)) + 4096 > limits.max_http_body_bytes)
        if too_large:
            if group:
                bundles.append(_bundle(group))
                group = []
            if (len(canonical([doc])) > limits.max_bundle_code_bytes
                    or len(doc.patch.splitlines()) > limits.max_bundle_patch_lines
                    or len(canonical([doc])) + 4096 > limits.max_http_body_bytes):
                raise ValueError("Single file exceeds bundle limit: " + doc.path)
        group.append(doc)
    if group:
        bundles.append(_bundle(group))
    return bundles


def _bundle(docs: list[SafeDocument]) -> Bundle:
    data = canonical(docs)
    return Bundle(id=hashlib.sha256(VERSION.encode() + data).hexdigest(),
                  documents=list(docs), payload_bytes=len(data))
