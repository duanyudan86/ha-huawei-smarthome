"""Basic adapter for Huawei product 113L (汇泰龙智能指纹锁).

Profile: https://smarthome-drcn.dbankcdn.com/device/guide/113L/113L.json
型号 HiMate-SL0-HN，厂商汇泰龙，Wi-Fi 智能门锁。

本适配器只接入 Profile 中语义明确的基础能力：门锁/门状态、电量、
低电量、供电状态、告警、门锁事件和门铃设置。用户/钥匙管理、临时密码、
公钥、唤醒和 OTA 属于安全或管理操作，不投影为 HA 实体。

适配依据公开 Profile，未经真实设备验证。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext


_LOCK_STATUS_SID = "lockStatus"
_LOCK_STATUS_FIELD = "status"
_DOOR_STATUS_FIELD = "doorStatus"
_EVENT_SID = "lockEvent"
_ALARM_SID = "lockAlarm"
_BATTERY_SID = "battery"
_DOORBELL_SID = "doorbell"

_OPEN_DOOR_STATUSES = frozenset({1, 3})

_DOORBELL_FIELDS = (
    ("bell", "门铃音色"),
    ("tone", "门铃音调"),
    ("volume", "门铃音量"),
)

def _number(value: Any) -> int | float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else number


def _bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        if value.casefold() in {"1", "true", "on"}:
            return True
        if value.casefold() in {"0", "false", "off"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return None


def _field(
    profile: Mapping[str, Any], sid: str, name: str
) -> Mapping[str, Any] | None:
    services = profile.get("services", ())
    if not isinstance(services, list):
        return None
    for service in services:
        if not isinstance(service, Mapping) or service.get("serviceId") != sid:
            continue
        characteristics = service.get("characteristics", ())
        if not isinstance(characteristics, list):
            return None
        for characteristic in characteristics:
            if (
                isinstance(characteristic, Mapping)
                and characteristic.get("characteristicName") == name
            ):
                return characteristic
    return None


def _enum_value(value: Any) -> int | float | str | None:
    number = _number(value)
    return number if number is not None else value if isinstance(value, str) else None


def _enum_label(field: Mapping[str, Any], value: Any) -> str | None:
    normalized = _enum_value(value)
    for option in field.get("enumList", ()):
        if not isinstance(option, Mapping):
            continue
        if normalized != _enum_value(option.get("enumVal")):
            continue
        label = option.get("descCh") or option.get("descEn")
        if label:
            return str(label)
    return None


def _enum_options(field: Mapping[str, Any]) -> list[tuple[str, int | float | str]]:
    options: list[tuple[str, int | float | str]] = []
    for option in field.get("enumList", ()):
        if not isinstance(option, Mapping):
            continue
        label = option.get("descCh") or option.get("descEn")
        value = _enum_value(option.get("enumVal"))
        if label and value is not None:
            options.append((str(label), value))
    return options


def _event_type(
    profile: Mapping[str, Any], data: Mapping[str, Any], event: Any
) -> str:
    event_field = _field(profile, _EVENT_SID, "event") or {}
    event_label = _enum_label(event_field, event) or "未知事件"
    if _number(event) not in {1, 2, 3}:
        return event_label

    type_label = _enum_label(
        _field(profile, _EVENT_SID, "type") or {}, data.get("type")
    )
    user_id = data.get("userID")
    if type_label is None or user_id is None:
        return event_label
    return f"{type_label}（用户ID: {user_id}）"


def _lock_event_types(profile: Mapping[str, Any]) -> list[str]:
    event_field = _field(profile, _EVENT_SID, "event") or {}
    type_field = _field(profile, _EVENT_SID, "type") or {}
    user_field = _field(profile, _EVENT_SID, "userID") or {}
    values: list[str] = []

    for label, _ in _enum_options(event_field):
        if label != "无效事件":
            values.append(label)

    user_min = _number(user_field.get("min"))
    user_max = _number(user_field.get("max"))
    if user_min is None or user_max is None:
        return list(dict.fromkeys(values))

    for type_label, _ in _enum_options(type_field):
        for user_id in range(int(user_min), int(user_max) + 1):
            values.append(f"{type_label}（用户ID: {user_id}）")
    return list(dict.fromkeys(values))


def _alarm_event_types(profile: Mapping[str, Any]) -> list[str]:
    return [
        label
        for label, _ in _enum_options(_field(profile, _ALARM_SID, "alarm") or {})
    ]


def _enum_sensor(
    sid: str,
    field_name: str,
    profile_field: Mapping[str, Any],
    key: str,
    name: str,
) -> EntitySpec:
    def state(device: DeviceContext) -> Mapping[str, Any]:
        raw = device.value(sid, field_name)
        return {"native_value": _enum_label(profile_field, raw)}

    return EntitySpec(
        platform="sensor",
        key=key,
        name=name,
        state=state,
    )


def _enum_select(
    sid: str,
    field_name: str,
    profile_field: Mapping[str, Any],
    key: str,
    name: str,
) -> EntitySpec | None:
    options = _enum_options(profile_field)
    if not options:
        return None
    values = dict(options)

    def state(device: DeviceContext) -> Mapping[str, Any]:
        return {
            "current_option": _enum_label(
                profile_field, device.value(sid, field_name)
            )
        }

    async def select_option(
        device: DeviceContext, data: Mapping[str, Any]
    ) -> None:
        option = str(data.get("option", ""))
        if option not in values:
            raise ValueError(f"unsupported 113L {field_name} option: {option}")
        await device.async_send_service(sid, {field_name: values[option]})

    return EntitySpec(
        platform="select",
        key=key,
        name=name,
        state=state,
        metadata={"options": [label for label, _ in options]},
        actions={"select_option": select_option},
    )


def _lock_event_decoder(
    device: DeviceContext,
    sid: str,
    data: Mapping[str, Any],
    timestamp: str | None,
) -> list[tuple[str, Mapping[str, Any]]]:
    if sid != _EVENT_SID:
        return []
    profile = device.profile or {}
    event = _number(data.get("event"))
    event_field = _field(profile, _EVENT_SID, "event") or {}
    event_label = _enum_label(event_field, event)
    if event is None or event_label in {None, "无效事件"}:
        return []
    payload: dict[str, Any] = {
        "event": event_label,
        "source": _EVENT_SID,
        "type": _enum_label(
            _field(profile, _EVENT_SID, "type") or {}, data.get("type")
        ),
        "id": data.get("id"),
        "user_id": data.get("userID"),
        "level": _enum_label(
            _field(profile, _EVENT_SID, "level") or {}, data.get("level")
        ),
    }
    if timestamp is not None:
        payload["reported_at"] = timestamp
        payload["event_id"] = f"{timestamp}:{event}:{data.get('userID')}:{data.get('id')}"
    return [
        (
            _event_type(profile, data, event),
            {key: value for key, value in payload.items() if value is not None},
        )
    ]


def _alarm_event_decoder(
    device: DeviceContext,
    sid: str,
    data: Mapping[str, Any],
    timestamp: str | None,
) -> list[tuple[str, Mapping[str, Any]]]:
    if sid != _ALARM_SID:
        return []
    profile = device.profile or {}
    alarm = _number(data.get("alarm"))
    alarm_label = _enum_label(
        _field(profile, _ALARM_SID, "alarm") or {}, alarm
    )
    if alarm is None or alarm_label is None:
        return []
    payload: dict[str, Any] = {
        "alarm": alarm_label,
        "source": _ALARM_SID,
        "type": _enum_label(
            _field(profile, _ALARM_SID, "type") or {}, data.get("type")
        ),
        "id": data.get("id"),
        "user_id": data.get("userID"),
        "level": _enum_label(
            _field(profile, _ALARM_SID, "level") or {}, data.get("level")
        ),
    }
    if timestamp is not None:
        payload["reported_at"] = timestamp
        payload["event_id"] = f"{timestamp}:{alarm}:{data.get('userID')}:{data.get('id')}"
    return [
        (
            alarm_label,
            {key: value for key, value in payload.items() if value is not None},
        )
    ]


class Product113LAdapter:
    """汇泰龙智能指纹锁的基础状态、告警、事件和门铃设置。"""

    prod_id = "113L"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        profile = context.profile
        if profile is None:
            return ()

        status_field = _field(profile, _LOCK_STATUS_SID, _LOCK_STATUS_FIELD)
        if status_field is None:
            return ()

        def door_state(device: DeviceContext) -> Mapping[str, Any]:
            status = _number(device.value(_LOCK_STATUS_SID, _DOOR_STATUS_FIELD))
            if status is None:
                return {"is_on": None}
            return {"is_on": status in _OPEN_DOOR_STATUSES}

        entities: list[EntitySpec] = [
            _enum_sensor(
                _LOCK_STATUS_SID,
                _LOCK_STATUS_FIELD,
                status_field,
                "lock_status",
                "门锁状态",
            ),
        ]

        door_field = _field(profile, _LOCK_STATUS_SID, _DOOR_STATUS_FIELD)
        if door_field is not None:
            entities.extend(
                (
                    EntitySpec(
                        platform="binary_sensor",
                        key="door",
                        name="门",
                        state=door_state,
                        metadata={"device_class": "door"},
                    ),
                    _enum_sensor(
                        _LOCK_STATUS_SID,
                        _DOOR_STATUS_FIELD,
                        door_field,
                        "door_status",
                        "门状态",
                    ),
                )
            )

        battery_field = _field(profile, _BATTERY_SID, "level")
        if battery_field is not None:

            def battery_state(device: DeviceContext) -> Mapping[str, Any]:
                return {
                    "native_value": _number(
                        device.value(_BATTERY_SID, "level")
                    )
                }

            entities.append(
                EntitySpec(
                    platform="sensor",
                    key="battery",
                    name="门锁电量",
                    state=battery_state,
                    metadata={
                        "device_class": "battery",
                        "unit": "%",
                        "state_class": "measurement",
                    },
                )
            )

        low_battery_field = _field(profile, _BATTERY_SID, "lowBattery")
        if low_battery_field is not None:
            entities.append(
                EntitySpec(
                    platform="binary_sensor",
                    key="low_battery",
                    name="低电量",
                    state=lambda device: {
                        "is_on": _bool(
                            device.value(_BATTERY_SID, "lowBattery")
                        )
                    },
                    metadata={"device_class": "battery"},
                )
            )

        emergency_field = _field(profile, _BATTERY_SID, "emergentBattery")
        if emergency_field is not None:
            entities.append(
                _enum_sensor(
                    _BATTERY_SID,
                    "emergentBattery",
                    emergency_field,
                    "power_source",
                    "供电状态",
                )
            )

        if _field(profile, _EVENT_SID, "event") is not None:
            entities.append(
                EntitySpec(
                    platform="event",
                    key="lock_event",
                    name="门锁事件",
                    state=lambda _device: {},
                    metadata={
                        "event_types": _lock_event_types(profile),
                        "icon": "mdi:door-open",
                    },
                    event_decoder=_lock_event_decoder,
                )
            )

        if _field(profile, _ALARM_SID, "alarm") is not None:
            entities.append(
                EntitySpec(
                    platform="event",
                    key="lock_alarm_event",
                    name="门锁警告事件",
                    state=lambda _device: {},
                    metadata={
                        "event_types": _alarm_event_types(profile),
                        "icon": "mdi:alarm-light",
                    },
                    event_decoder=_alarm_event_decoder,
                )
            )

        for field_name, name in _DOORBELL_FIELDS:
            profile_field = _field(profile, _DOORBELL_SID, field_name)
            if profile_field is None:
                continue
            spec = _enum_select(
                _DOORBELL_SID,
                field_name,
                profile_field,
                f"doorbell_{field_name}",
                name,
            )
            if spec is not None:
                entities.append(spec)

        return tuple(entities)


ADAPTER = Product113LAdapter()
