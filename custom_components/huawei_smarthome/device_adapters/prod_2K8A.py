"""User-contributed protocol for Huawei product 2K8A (霍尼韦尔空气净化器 KJ1000F-P22W).

产品: 霍尼韦尔空气净化器 KJ1000F-P22W
厂商: 霍尼韦尔 (霍威空气净化技术江苏有限公司, 鸿蒙智联认证机型)
型号: KJ1000F-P22W (deviceTypeId 013, 空气净化器)

本适配器遵循项目规范：单品协议行为全部硬编码在本文件内，
**不跨产品复用**。2K8A 的档位定义与 720 系（2S2Q/170W）不同：
gear 枚举值是 0~3，但语义是 **1~4 挡**（enumVal 与挡位序号差 1），
且没有 0 挡/无风；模式只有 手动/自动/睡眠 三档，没有节能。
故各自独立实现。

=====================================================================
Profile 服务一览（含未映射项）
=====================================================================
  switch.on              bool RW 电源开关            -> fan on/off
  mode.mode              enum RW 0=手动 1=自动 2=睡眠 -> fan preset_mode
  fan.gear               enum RW 0=1挡 1=2挡 2=3挡 3=4挡 -> fan percentage/preset
  UVSwitch.on            bool RW 紫外线(除菌)        -> switch uv
  childLockSwitch.on     bool RW 童锁                -> switch child_lock
  setting.settime        enum RW 0=关闭 1=2h 2=4h 3=8h 4=12h -> select 定时关机
  setting.remainingtime  int  R  定时剩余分钟        -> sensor (diagnostic)
  pm25.current           int  R  0~? μg/m³          -> sensor pm25
  tvoc.level             enum R  0=好 1=中 2=差      -> sensor tvoc_level
  filterElement2.leftPercentage int R 0~100 % HiSiv滤芯余量 -> sensor
  filterElement2.leftTime       int R 剩余小时        -> sensor (diagnostic)
  filterElement2.alarm          bool R                -> binary_sensor 滤芯告警
  filterElement2.reset          enum RW 1=耗材复位     -> button 滤芯复位
  filterElement2.filterType/name/id  静态元数据        不映射

  update.*  netInfo.*    OTA/网络                    不映射（见下）

=====================================================================
档位与百分比
=====================================================================
gear 只有 4 个有效挡（1~4 挡），线性映射 25/50/75/100%，
写入时反算最近挡位。preset_modes 同时提供：
  * 模式：手动 / 自动 / 睡眠（mode.mode）
  * 挡位：风速:1挡 … 风速:4挡（按 Profile descCh 原文，
    注意 descCh 的 "1挡" 对应 enumVal 0，**不能**从标签反解数字，
    必须查 enumList 映射——这是与 720 系最大的差异）。

Profile 对 mode 的说明提到"设备和手机端不显示手动模式"，但枚举里
声明了 0=手动 且 RW，保留为 preset 供自动化使用。

=====================================================================
报文类型
=====================================================================
沿用 2MZN/2S2Q 的实测教训：enumList 的 enumVal 一律是**字符串**，
真机只接受数值，所有写命令经 _coerce() 按 characteristicType 数值化。
_enum_value() 只按 enumVal 精确匹配，不做文本回退。

=====================================================================
为什么不映射 update.* / netInfo.*
=====================================================================
2S2Q 真机实测该类字段长期 unknown，本机型沿用同样结论不创建；
若真机验证确会上报，可按 2S2Q 的方式补回。

=====================================================================
真机验证记录（2026-11-21，KJ1000F-P22W，固件 1.0.0.1270）
=====================================================================
[x] 状态读取：开关/档位(1挡)/PM2.5/TVOC 等级/滤芯余量 37%/滤芯余时
    1487h/定时关机 全部与智慧生活 App 一致。
[x] **gear 与挡位序号差 1 已确认**：set_preset_mode "风速:2挡"
    下发 gear=1，真机进 2 挡（HA 侧 percentage 50）。
[x] 模式切换：set_preset_mode "自动" 正常。**设备行为：手动改风速
    会退出自动模式进入"手动"**——自动化里要回自动需显式设 "自动"。
[ ] UV、童锁、定时关机、滤芯复位未逐项实测（与已验证的 bool/enum
    写路径同型，风险低）。
[ ] 滤芯余量上报频率、reset 写入后清零行为未验证。
[ ] setting.remainingtime 更新频率未验证（当前读到 0）。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext

# --- 模式（mode.mode） -----------------------------------------------
_MODE_OPTIONS = (
    (0, "手动"),
    (1, "自动"),
    (2, "睡眠"),
)
_MODE_BY_LABEL = {label: raw for raw, label in _MODE_OPTIONS}
_MODE_BY_RAW = {str(raw): label for raw, label in _MODE_OPTIONS}

# --- 定时关机（setting.settime）：标签取自 Profile，这里只留兜底 ------
_TIMER_FALLBACK_LABELS = {0: "关闭", 1: "2小时", 2: "4小时", 3: "8小时", 4: "12小时"}

# --- TVOC 等级短标签（descCh 带阈值文本，剥掉后展示） -----------------
_TVOC_LABELS = {0: "好", 1: "中", 2: "差"}

# gear 4 挡线性映射百分比
_GEAR_COUNT = 4
_GEAR_STEP_PERCENT = 100 // _GEAR_COUNT  # 25


# ---------------------------------------------------------------------
# 取值解码
# ---------------------------------------------------------------------
def _bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        if value.strip().casefold() in {"1", "true", "on"}:
            return True
        if value.strip().casefold() in {"0", "false", "off"}:
            return False
        return None
    if isinstance(value, (int, float)):
        return bool(value)
    return None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    number = _number(value)
    return None if number is None else int(round(number))


# ---------------------------------------------------------------------
# Profile 读取与报文编码
# ---------------------------------------------------------------------
def _field(
    profile: Mapping[str, Any] | None,
    sid: str,
    name: str,
) -> Mapping[str, Any] | None:
    if not isinstance(profile, Mapping):
        return None
    for service in profile.get("services", ()):
        if not isinstance(service, Mapping) or service.get("serviceId") != sid:
            continue
        for field in service.get("characteristics", ()):
            if (
                isinstance(field, Mapping)
                and field.get("characteristicName") == name
            ):
                return field
        return None
    return None


def _is_writable(field: Mapping[str, Any] | None) -> bool:
    if not isinstance(field, Mapping):
        return False
    return "W" in str(field.get("method") or "")


def _coerce(value: Any, field: Mapping[str, Any] | None) -> Any:
    if not isinstance(field, Mapping):
        return value
    data_type = str(field.get("characteristicType") or "").casefold()
    if data_type in {"bool", "int", "integer", "enum"}:
        number = _number(value)
        if number is None:
            return value
        return int(number) if number.is_integer() else number
    if data_type in {"float", "double", "number"}:
        number = _number(value)
        return value if number is None else number
    return value


def _enum_value(
    field: Mapping[str, Any] | None,
    wanted: Any,
    fallback: Any,
) -> Any:
    raw: Any = fallback
    if isinstance(field, Mapping):
        for option in field.get("enumList", ()):
            if not isinstance(option, Mapping):
                continue
            candidate = option.get("enumVal")
            if candidate is None:
                continue
            if str(candidate) == str(wanted):
                raw = candidate
                break
    return _coerce(raw, field)


def _enum_label(field: Mapping[str, Any] | None, value: Any) -> str | None:
    if not isinstance(field, Mapping) or value is None:
        return None
    for option in field.get("enumList", ()):
        if not isinstance(option, Mapping):
            continue
        if str(option.get("enumVal")) != str(value):
            continue
        label = option.get("descCh") or option.get("descEn")
        if isinstance(label, str) and label.strip():
            return label.strip()
    return None


def _enum_options(
    field: Mapping[str, Any] | None,
) -> list[tuple[int, str]]:
    """(enumVal int, descCh label) pairs declared by the Profile."""
    out: list[tuple[int, str]] = []
    if not isinstance(field, Mapping):
        return out
    for option in field.get("enumList", ()):
        if not isinstance(option, Mapping):
            continue
        raw = _int(option.get("enumVal"))
        if raw is None:
            continue
        label = option.get("descCh") or option.get("descEn") or str(raw)
        out.append((raw, str(label).strip()))
    return out


# ---------------------------------------------------------------------
# 档位 <-> 百分比（gear 0~3 == 1~4 挡）
# ---------------------------------------------------------------------
def _percentage_from_gear(gear: Any) -> int | None:
    value = _int(gear)
    if value is None:
        return None
    value = min(max(value, 0), _GEAR_COUNT - 1)
    return int((value + 1) * _GEAR_STEP_PERCENT)


def _gear_from_percentage(percentage: Any) -> int | None:
    number = _number(percentage)
    if number is None:
        return None
    number = min(max(number, 1.0), 100.0)
    gear = round(number / _GEAR_STEP_PERCENT) - 1
    return int(min(max(gear, 0), _GEAR_COUNT - 1))


# ---------------------------------------------------------------------
# 实体构造
# ---------------------------------------------------------------------
def _make_switch(
    context: DeviceContext,
    sid: str,
    field_name: str,
    key: str,
    name: str,
) -> EntitySpec:
    field = _field(context.profile, sid, field_name)
    on_value = _enum_value(field, 1, 1)
    off_value = _enum_value(field, 0, 0)

    async def turn_on(device: DeviceContext, _data: Mapping[str, Any]) -> None:
        await device.async_send_service(sid, {field_name: on_value})

    async def turn_off(device: DeviceContext, _data: Mapping[str, Any]) -> None:
        await device.async_send_service(sid, {field_name: off_value})

    return EntitySpec(
        platform="switch",
        key=key,
        name=name,
        state=lambda device: {"is_on": _bool(device.value(sid, field_name))},
        actions={"turn_on": turn_on, "turn_off": turn_off},
    )


def _make_profile_select(
    context: DeviceContext,
    sid: str,
    field_name: str,
    key: str,
    name: str,
    fallback_labels: Mapping[int, str] | None = None,
) -> EntitySpec | None:
    field = _field(context.profile, sid, field_name)
    if field is None or not _is_writable(field):
        return None
    options: list[tuple[int, str]] = _enum_options(field)
    if not options and fallback_labels:
        options = sorted(fallback_labels.items())
    if not options:
        return None
    labels = tuple(label for _, label in options)
    by_label = {label: raw for raw, label in options}
    by_raw = {str(raw): label for raw, label in options}

    def state(device: DeviceContext) -> Mapping[str, Any]:
        raw = _int(device.value(sid, field_name))
        if raw is None:
            return {"current_option": None}
        return {"current_option": by_raw.get(str(raw))}

    async def select(device: DeviceContext, data: Mapping[str, Any]) -> None:
        wanted = str(data.get("option"))
        raw = by_label.get(wanted)
        if raw is None:
            raise ValueError(f"unsupported option for {sid}.{field_name}: {wanted}")
        await device.async_send_service(sid, {field_name: _coerce(raw, field)})

    return EntitySpec(
        platform="select",
        key=key,
        name=name,
        state=state,
        metadata={"options": labels},
        actions={"select_option": select},
    )


def _make_sensor(
    sid: str,
    field_name: str,
    key: str,
    name: str,
    *,
    unit: str | None = None,
    device_class: str | None = None,
    state_class: str | None = None,
    entity_category: str | None = None,
    decode: Any = None,
) -> EntitySpec:
    decoder = decode or (lambda value: _number(value))

    def state(device: DeviceContext) -> Mapping[str, Any]:
        return {"native_value": decoder(device.value(sid, field_name))}

    metadata: dict[str, Any] = {}
    if unit is not None:
        metadata["unit"] = unit
    if device_class is not None:
        metadata["device_class"] = device_class
    if state_class is not None:
        metadata["state_class"] = state_class
    if entity_category is not None:
        metadata["entity_category"] = entity_category

    return EntitySpec(
        platform="sensor",
        key=key,
        name=name,
        state=state,
        metadata=metadata,
    )


class Product2K8AAdapter:
    """Keep all 2K8A entity and command choices in this file."""

    prod_id = "2K8A"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        profile = context.profile
        if profile is None:
            return ()

        entities: list[EntitySpec] = []

        # --- fan：电源 / 百分比 / 预设模式 -----------------------------
        if context.has_service("switch"):
            gear_field = _field(profile, "fan", "gear")
            mode_field = _field(profile, "mode", "mode")
            power_field = _field(profile, "switch", "on")
            on_value = _enum_value(power_field, 1, 1)
            off_value = _enum_value(power_field, 0, 0)

            # 挡位预设：用 Profile descCh 原文（"1挡".."4挡"），
            # 加 "风速:" 前缀与模式区分；标签->enumVal 走 enumList 映射，
            # 不从标签文字反解数字（本机型 descCh "1挡" 的 enumVal 是 0）。
            gear_options = _enum_options(gear_field) if gear_field else []
            gear_presets = tuple(f"风速:{label}" for _, label in gear_options)
            gear_by_label = {f"风速:{label}": raw for raw, label in gear_options}

            mode_declared = (
                {v for v, _ in _enum_options(mode_field)} if mode_field else set()
            )
            mode_values = tuple(
                raw for raw, _ in _MODE_OPTIONS if raw in mode_declared
            )
            mode_presets = tuple(
                label for raw, label in _MODE_OPTIONS if raw in mode_values
            )
            presets = mode_presets + gear_presets

            def fan_state(device: DeviceContext) -> Mapping[str, Any]:
                gear = device.value("fan", "gear")
                raw_mode = _int(device.value("mode", "mode"))
                return {
                    "is_on": _bool(device.value("switch", "on")),
                    "percentage": _percentage_from_gear(gear),
                    "preset_mode": _MODE_BY_RAW.get(str(raw_mode)),
                }

            async def _apply_percentage(
                device: DeviceContext, percentage: Any
            ) -> None:
                gear = _gear_from_percentage(percentage)
                if gear is None:
                    return
                await device.async_send_service(
                    "fan", {"gear": _enum_value(gear_field, gear, gear)}
                )

            async def _apply_preset(
                device: DeviceContext, preset: Any
            ) -> None:
                wanted = str(preset)
                mode_raw = _MODE_BY_LABEL.get(wanted)
                if mode_raw is not None and mode_raw in mode_values:
                    await device.async_send_service(
                        "mode", {"mode": _enum_value(mode_field, mode_raw, mode_raw)}
                    )
                    return
                if wanted in gear_by_label:
                    gear = gear_by_label[wanted]
                    await device.async_send_service(
                        "fan", {"gear": _enum_value(gear_field, gear, gear)}
                    )
                    return
                raise ValueError(f"unsupported preset_mode: {wanted}")

            async def turn_on(
                device: DeviceContext, data: Mapping[str, Any]
            ) -> None:
                await device.async_send_service("switch", {"on": on_value})
                preset = data.get("preset_mode")
                percentage = data.get("percentage")
                if preset is not None:
                    await _apply_preset(device, preset)
                elif percentage is not None:
                    await _apply_percentage(device, percentage)

            async def turn_off(
                device: DeviceContext, _data: Mapping[str, Any]
            ) -> None:
                await device.async_send_service("switch", {"on": off_value})

            async def set_percentage(
                device: DeviceContext, data: Mapping[str, Any]
            ) -> None:
                await _apply_percentage(device, data.get("percentage"))

            async def set_preset_mode(
                device: DeviceContext, data: Mapping[str, Any]
            ) -> None:
                await _apply_preset(device, data.get("preset_mode"))

            entities.append(
                EntitySpec(
                    platform="fan",
                    key="purifier",
                    name=None,
                    state=fan_state,
                    metadata={
                        "supports_percentage": True,
                        "percentage_step": _GEAR_STEP_PERCENT,
                        "preset_modes": list(presets),
                    },
                    actions={
                        "turn_on": turn_on,
                        "turn_off": turn_off,
                        "set_percentage": set_percentage,
                        "set_preset_mode": set_preset_mode,
                    },
                )
            )

        # --- 布尔开关 -------------------------------------------------
        for sid, field_name, key, name in (
            ("UVSwitch", "on", "uv", "除菌(紫外线)"),
            ("childLockSwitch", "on", "child_lock", "童锁"),
        ):
            field = _field(context.profile, sid, field_name)
            if context.has_service(sid) and _is_writable(field):
                entities.append(_make_switch(context, sid, field_name, key, name))

        # --- select：定时关机 -----------------------------------------
        if context.has_service("setting"):
            spec = _make_profile_select(
                context, "setting", "settime", "timer_off", "定时关机",
                fallback_labels=_TIMER_FALLBACK_LABELS,
            )
            if spec is not None:
                entities.append(spec)
            if _field(profile, "setting", "remainingtime") is not None:
                entities.append(
                    _make_sensor(
                        "setting", "remainingtime", "timer_remaining",
                        "定时剩余时间", unit="min",
                        entity_category="diagnostic", decode=_int,
                    )
                )

        # --- 传感器：环境读数 -----------------------------------------
        if context.has_service("pm25"):
            entities.append(
                _make_sensor(
                    "pm25", "current", "pm25", "室内 PM2.5",
                    unit="µg/m³", device_class="pm25",
                    state_class="measurement", decode=_int,
                )
            )
        if context.has_service("tvoc"):
            tvoc_field = _field(profile, "tvoc", "level")

            def tvoc_state(device: DeviceContext) -> Mapping[str, Any]:
                raw = _int(device.value("tvoc", "level"))
                if raw is None:
                    return {"native_value": None}
                desc = _enum_label(tvoc_field, raw)
                return {
                    "native_value": _TVOC_LABELS.get(raw, desc),
                    "extra_state_attributes": {
                        "raw_level": raw,
                        "profile_description": desc,
                    },
                }

            entities.append(
                EntitySpec(
                    platform="sensor",
                    key="tvoc_level",
                    name="TVOC 等级",
                    state=tvoc_state,
                    metadata={},
                )
            )

        # --- 滤芯耗材（filterElement2, HiSiv 复合滤芯） ---------------
        if context.has_service("filterElement2"):
            if _field(profile, "filterElement2", "leftPercentage") is not None:
                entities.append(
                    _make_sensor(
                        "filterElement2", "leftPercentage",
                        "filter_left_percentage", "滤芯剩余",
                        unit="%", state_class="measurement", decode=_int,
                    )
                )
            if _field(profile, "filterElement2", "leftTime") is not None:
                entities.append(
                    _make_sensor(
                        "filterElement2", "leftTime", "filter_left_time",
                        "滤芯剩余时间", unit="h",
                        state_class="measurement",
                        entity_category="diagnostic", decode=_int,
                    )
                )
            if _field(profile, "filterElement2", "alarm") is not None:
                entities.append(
                    EntitySpec(
                        platform="binary_sensor",
                        key="filter_alarm",
                        name="滤芯告警",
                        state=lambda device: {
                            "is_on": _bool(
                                device.value("filterElement2", "alarm")
                            )
                        },
                        metadata={"device_class": "problem"},
                    )
                )
            reset_field = _field(profile, "filterElement2", "reset")
            if _is_writable(reset_field):
                reset_value = _enum_value(reset_field, 1, 1)

                async def reset_filter(
                    device: DeviceContext, _data: Mapping[str, Any]
                ) -> None:
                    await device.async_send_service(
                        "filterElement2", {"reset": reset_value}
                    )

                entities.append(
                    EntitySpec(
                        platform="button",
                        key="filter_reset",
                        name="滤芯复位",
                        state=lambda device: {},
                        actions={"press": reset_filter},
                    )
                )

        return tuple(entities)


ADAPTER = Product2K8AAdapter()
