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

"""Role-scoped tool composition: blackboard + read-only map tools + orchestrated specialists."""

from scout_crew.tools.blackboard_tool import tools_for_role as _blackboard_tools_for_role
from scout_crew.tools.map_tool import map_tools_for_role
from scout_crew.tools.specialist_tools import specialist_tools_for_orchestration


def tools_for_role(role: str) -> list:
    """Blackboard tools (role ACL) + read-only map tools for every role."""
    return _blackboard_tools_for_role(role) + map_tools_for_role(role)


def orchestrated_manager_tools() -> list:
    """Manager tools in orchestrated mode: blackboard + map + per-specialist tools."""
    return tools_for_role("manager") + specialist_tools_for_orchestration()


__all__ = ["orchestrated_manager_tools", "specialist_tools_for_orchestration", "tools_for_role"]