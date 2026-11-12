"""User-contributed protocol for Huawei product 20HZ (达伦吸顶灯).

设备类型: 智能照明 (Lamp), 型号 DL-CLW-1
制造商: 达伦 (DALEN)

核心服务:
   switch.on                    bool RW  开关 (1=开, 0=关)
   brightness.brightness        int  RW  亮度 1-100
   colourMode.mode              enum R   颜色模式(0=彩色,1=单色,2=预置流光,3=自定义流光,4=设备预置模式)
   cct.colorTemperature         int  RW  色温 2000-6000
   lightMode.mode               enum RW  场景推荐
   NightMode.on                 bool RW  小夜灯 (1=开, 0=关)

本适配器暴露:
   1. light    开关、亮度、色温
   2. select   灯光模式
   3. switch   小夜灯

投影说明:
   Profile 要求 colourMode 与 lightMode 同时上报。色温与灯光模式仅在
   colourMode 明确为单色 (1) 或设备预置模式 (4) 时才有效；其余取值
   (流光等) 下两者均不代表当前真实输出，此时返回 None 而非回退到旧值。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext


# ---- 枚举映射 ------------------------------------------------------------

_LIGHT_MODE_OPTIONS = [
    "会客模式", "休闲模式", "观影模式", "用餐模式", "变幻模式",
    "浪漫模式", "工作模式", "睡眠模式", "阅读模式", "清扫模式",
]
_LIGHT_MODE_VALUES = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
_MODE_NAME_TO_VAL = dict(zip(_LIGHT_MODE_OPTIONS, _LIGHT_MODE_VALUES))
_MODE_VAL_TO_NAME = dict(zip(_LIGHT_MODE_VALUES, _LIGHT_MODE_OPTIONS))

# colourMode.mode: 0=彩色 1=单色 2=预置流光 3=自定义流光 4=设备预置模式
_COLOUR_MODE_SINGLE = 1
_COLOUR_MODE_DEVICE_PRESET = 4


# ---- 工具函数 ------------------------------------------------------------

def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, str):
        try:
            return int(round(float(value.strip())))
        except (TypeError, ValueError):
            return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _as_bool(value: Any) -> bool | None:
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


def _colour_mode_int(context: DeviceContext) -> int | None:
    """读取 colourMode 投影闸门；未明确上报时返回 None。"""

    if not context.has_service("colourMode"):
        return None
    return _as_int(context.value("colourMode", "mode"))


# ---- 动作函数 ------------------------------------------------------------

def _device_brightness_to_ha(value: Any) -> int | None:
    value = _as_int(value)
    if value is None:
        return None
    return round(1 + (max(1, min(100, value)) - 1) * 254 / 99)


def _ha_brightness_to_device(value: Any) -> int | None:
    value = _as_int(value)
    if value is None:
        return None
    return round(1 + (max(1, min(255, value)) - 1) * 99 / 254)


async def _turn_on(context: DeviceContext, data: Mapping[str, Any]) -> None:
    await context.async_send_service("switch", {"on": 1})

    brightness = _ha_brightness_to_device(data.get("brightness"))
    if brightness is not None:
        await context.async_send_service(
            "brightness", {"brightness": brightness}
        )

    color_temperature = _as_int(data.get("color_temp_kelvin"))
    if color_temperature is not None:
        await context.async_send_service(
            "cct", {"colorTemperature": max(2000, min(6000, color_temperature))}
        )


async def _turn_off(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service("switch", {"on": 0})


async def _select_light_mode(context: DeviceContext, data: Mapping[str, Any]) -> None:
    val = _MODE_NAME_TO_VAL.get(str(data.get("option")))
    if val is None:
        raise ValueError(f"unsupported light mode: {data.get('option')}")
    await context.async_send_service("lightMode", {"mode": val})


async def _set_night_mode(context: DeviceContext, data: Mapping[str, Any]) -> None:
    is_on = data.get("is_on")
    if is_on is None:
        return
    await context.async_send_service("NightMode", {"on": 1 if is_on else 0})


# ---- 适配器 --------------------------------------------------------------

class Product20HZAdapter:
    """20HZ 达伦吸顶灯适配器。"""

    prod_id = "20HZ"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        if context.profile is None or not all(
            context.has_service(sid) for sid in ("switch", "brightness", "cct")
        ):
            return ()

        def light_state(device: DeviceContext) -> Mapping[str, Any]:
            colour_mode = _colour_mode_int(device)
            return {
                "is_on": _as_bool(device.value("switch", "on")),
                "brightness": _device_brightness_to_ha(
                    device.value("brightness", "brightness")
                ),
                "color_temp_kelvin": (
                    _as_int(device.value("cct", "colorTemperature"))
                    if colour_mode == _COLOUR_MODE_SINGLE
                    else None
                ),
                "color_mode": (
                    "color_temp"
                    if colour_mode == _COLOUR_MODE_SINGLE
                    else "brightness"
                ),
            }

        def light_mode_state(device: DeviceContext) -> Mapping[str, Any]:
            if _colour_mode_int(device) != _COLOUR_MODE_DEVICE_PRESET:
                return {"current_option": None}
            val = _as_int(device.value("lightMode", "mode"))
            return {"current_option": _MODE_VAL_TO_NAME.get(val)}

        def night_mode_state(device: DeviceContext) -> Mapping[str, Any]:
            if not device.has_service("NightMode"):
                return {"is_on": None}
            return {"is_on": _as_bool(device.value("NightMode", "on"))}

        return (
            EntitySpec(
                platform="light",
                key="light",
                name=None,
                state=light_state,
                metadata={
                    "supported_color_modes": {"brightness", "color_temp"},
                    "min_color_temp_kelvin": 2000,
                    "max_color_temp_kelvin": 6000,
                },
                actions={"turn_on": _turn_on, "turn_off": _turn_off},
            ),
            EntitySpec(platform="select", key="light_mode", name="灯光模式",
                       state=light_mode_state,
                       metadata={"options": _LIGHT_MODE_OPTIONS},
                       actions={"select_option": _select_light_mode}),
            EntitySpec(platform="switch", key="night_mode", name="小夜灯",
                       state=night_mode_state,
                       actions={"turn_on": _set_night_mode, "turn_off": _set_night_mode},
                       availability=lambda device: device.has_service("NightMode"),
                       metadata={"icon": "mdi:weather-night"}),
        )


ADAPTER = Product20HZAdapter()
