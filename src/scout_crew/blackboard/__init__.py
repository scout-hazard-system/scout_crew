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

"""Multi-machine categorized blackboard shared memory for Scout Crew."""

from scout_crew.blackboard.client import BlackboardClient
from scout_crew.blackboard.store import CATEGORIES, ROLE_ACL

__all__ = ["BlackboardClient", "CATEGORIES", "ROLE_ACL"]
