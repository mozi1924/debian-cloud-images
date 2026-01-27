# SPDX-License-Identifier: GPL-2.0-or-later

from __future__ import annotations

type JSONVal = None | bool | str | float | int | JSONArray | JSONObject
type JSONArray = list[JSONVal]
type JSONObject = dict[str, JSONVal]
