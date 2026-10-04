# Copyright 2026 Scout Project Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Strip model reasoning ("<think>...</think>") from user-facing output.

Qwen3-family models emit a reasoning block; some fine-tunes (e.g. the hermes
tag) drop the opening tag and emit only "...</think>answer". Set
SCOUT_SHOW_REASONING=1 to keep the raw text for debugging.
"""

from __future__ import annotations

import os
import re

_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_CLOSE = re.compile(r"</think>", re.IGNORECASE)


def strip_reasoning(text: str) -> str:
    if os.getenv("SCOUT_SHOW_REASONING", "0") in {"1", "true", "True", "yes"}:
        return text
    out = _BLOCK.sub("", text)
    # Unpaired closing tag: everything before it was reasoning.
    parts = _CLOSE.split(out)
    if len(parts) > 1:
        out = parts[-1]
    return out.strip()
