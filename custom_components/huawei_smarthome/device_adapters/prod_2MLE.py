"""User-contributed protocol for Huawei product 2MLE (IAM 智能净化加湿一体机 U7).

设备类型: 空气净化器 (deviceTypeId 013), 型号 SZM2000-U7
制造商: 艾恩科技集团 (IAM), protocolType=WiFi, uiType=H5

该 Profile 共 20 个服务:
   switch / aromaSwitch / childLockSwitch / lightSwitch / monitoringSwitch
   mode / fan / humidity / pm25 / temperature / cav / weight / ambientLight
   filterElement1 / filterElement2 / faultDetection / machinePara
   timer / netInfo / update

已暴露实体 (19 个):
   电源       switch          switch.on
   童锁       switch(config)  childLockSwitch.on
   氛围灯     switch          lightSwitch.lightSwitch
   监测模式   switch(config)  monitoringSwitch.on
   模式       select          mode.mode (手动 / 自动 / 睡眠 / 节能)
   风速       fan             fan.gear (1~5 档) + fan.autoFanSwitch
   加湿       humidifier      aromaSwitch.on + humidity.target/current
   温度       sensor          temperature.current
   湿度       sensor          humidity.current
   PM2.5      sensor          pm25.current
   户外 PM2.5 sensor          machinePara.oPM25
   空气质量   sensor          machinePara.aqi (优 / 良 / 中 / 差)
   水量       sensor          machinePara.shuiliang
   今日净化量 sensor          machinePara.cavPerDay
   洁净空气总量 sensor        cav.current
   加湿滤网   sensor(诊断)    filterElement1.leftPercentage (+ 剩余小时属性)
   净化滤网   sensor(诊断)    filterElement2.leftPercentage (+ 剩余小时属性)
   故障码     sensor(诊断)    faultDetection.code
   故障       binary_sensor(诊断) faultDetection.status

   分组说明: 「故障」是诊断项，与「故障码」同组；空气质量、户外 PM2.5
   属于用户日常关心的读数，放在主实体区；滤网与故障码属于维护信息，归诊断。

命名说明:
   `aromaSwitch` 在 Profile 里的 descCh 是「加湿开关」，不是香薰开关；
   本设备用它控制加湿功能的开/关，故映射为 humidifier 的 is_on，
   不另做 switch，避免同一开关出现两个实体。

   `monitoringSwitch` 在 Profile 里叫「待机监测模式开关」，App 里叫「监测模式」：
   开启后设备持续监测空气质量并保持微量净化能力，主机屏幕常亮，
   关机后进入监控模式而不是普通待机。实体名沿用 App 的说法。

未暴露的服务与原因:
   weight 洁净颗粒物重量(μg)、cav 之外的累计量:
       与「今日净化量 / 洁净空气量」语义重叠，主界面价值低，不单独做实体。
   ambientLight.level 氛围灯亮度(低/中/强):
       与 lightSwitch 配套，但 Profile 未给出与灯开关的联动语义，
       先只做开关；亮度作为 select 待真机确认后再补。
   machinePara 的 dryFunction / watercurtainSW / holidayMode / DispSw /
       voiceSw / city / timerVal / remainHumi / dryLeftTime:
       属于二级设置或与定时强耦合，按「不塞冗余管理项」的原则暂不暴露。
   timer    与本设备其它产品一致，只读展示尚未实现（本文件暂不做）。
   netInfo  云端实测不上报（data 恒为 {}），不做永远 unknown 的实体。
   update   OTA。

待确认:
   1. humidity.level（Profile 未定义，实测上报 3）含义未知，未使用。
   2. HA 2026.10 的 FanEntity 用 ``speed_count`` 推导 ``percentage_step``，
      框架原先只写 ``_attr_percentage_step``，新版已不生效，滑杆步进退化为
      1%（影响所有带风速的单品）。该问题已在框架层单独修复，见
      ``fix(fan): 用 speed_count 表达档位数``，本适配器无需特殊处理。

真机验证记录 (2026-10-31):
   1. 状态读取: 已实测。PM2.5=9、温度=24、空气质量=优、水量=3%、
      今日净化量=990、洁净空气总量=32285、加湿滤网=73%、净化滤网=89%、
      故障码=正常、模式=睡眠，与云端原始值逐项一致。
   2. 电源: 已实测，开/关均生效。
   3. 氛围灯: 已实测，关/开均生效并回传。
   4. 童锁: 已实测，开/关均生效并回传。
   5. 风速: 已实测，设 60% -> 档位 3；设 20% -> 档位 1。
      下发 ``{"gear": n, "autoFanSwitch": 0}`` 合成一条 payload 可被接受。
   6. 模式: 已实测，自动/睡眠切换生效（改风速会被设备切到"手动"模式，
      属设备侧行为）。
   7. 加湿: 已实测。水箱 3% 时设备拒绝开启（App 同样失败，属设备保护）；
      加水至 29% 后 turn_on 生效，set_humidity 70/55 均生效，turn_off 生效。
   8. workStatus: 实测在电源开、自动模式、风扇 40%、加湿运行中时仍为 0，
      与"是否运转"无关，故不做 binary_sensor。
   9. 监测模式: 已实测。开 -> 关 -> 开 均生效并回传。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .api import EntitySpec
from .context import DeviceContext

_MODE_OPTIONS: tuple[str, ...] = ("手动", "自动", "睡眠", "节能")
_MODE_VALUES: dict[str, int] = {
    "手动": 0,
    "自动": 1,
    "睡眠": 2,
    "节能": 100,
}

_AQI_LABELS: dict[int, str] = {0: "优", 1: "良", 2: "中", 3: "差"}

_FAN_PRESET_AUTO = "自动"
_FAN_PRESET_MANUAL = "手动"
_FAN_PRESETS: tuple[str, ...] = (_FAN_PRESET_AUTO, _FAN_PRESET_MANUAL)
_FAN_MIN_GEAR = 1
_FAN_MAX_GEAR = 5
_FAN_PERCENTAGE_STEP = 20

_FAULT_CODES: dict[int, str] = {
    0: "正常",
    1: "马达风机故障",
    3: "水箱未安装到位",
    4: "运行中水量耗尽",
    5: "水满",
    6: "后盖打开",
    7: "加湿滤网未安装到位",
    8: "净化滤芯需要清洁",
    9: "传感器异常",
    100: "加湿滤网需要清洁",
    102: "静电消杀电场未安装到位",
    103: "开机水量低于 10%",
    104: "开机水量已耗尽",
    105: "水量耗尽，无法切换加湿",
    106: "顶盖打开",
}

_HUMIDITY_MIN = 30
_HUMIDITY_MAX = 80


def _field(
    profile: Mapping[str, Any],
    sid: str,
    name: str,
) -> Mapping[str, Any] | None:
    for service in profile.get("services", ()):
        if not isinstance(service, Mapping) or service.get("serviceId") != sid:
            continue
        for field in service.get("characteristics", ()):
            if isinstance(field, Mapping) and field.get("characteristicName") == name:
                return field
    return None


def _as_bool(value: Any) -> bool | None:
    """严格解析开关量: 只接受 0/1 及等价字符串，其它返回 None。"""

    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        token = value.strip().casefold()
        if token in {"1", "true", "on"}:
            return True
        if token in {"0", "false", "off"}:
            return False
        return None
    if isinstance(value, (int, float)):
        if value == 1:
            return True
        if value == 0:
            return False
        return None
    return None


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    number = _number(value)
    if number is None:
        return None
    return int(round(number))


def _mode_label(value: Any) -> str | None:
    number = _as_int(value)
    if number is None:
        return None
    for label, code in _MODE_VALUES.items():
        if code == number:
            return label
    return None


def _aqi_label(value: Any) -> str | None:
    number = _as_int(value)
    if number is None:
        return None
    return _AQI_LABELS.get(number)


def _fault_label(value: Any) -> str:
    number = _as_int(value)
    if number is None:
        return "未知"
    return _FAULT_CODES.get(number, f"未定义故障码 {number}")


def _gear_percentage(value: Any) -> int | None:
    gear = _as_int(value)
    if gear is None:
        return None
    gear = max(_FAN_MIN_GEAR, min(_FAN_MAX_GEAR, gear))
    return gear * _FAN_PERCENTAGE_STEP


# ---- 写动作 --------------------------------------------------------------

async def _power_on(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service("switch", {"on": 1})


async def _power_off(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service("switch", {"on": 0})


async def _child_lock_on(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service("childLockSwitch", {"on": 1})


async def _child_lock_off(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service("childLockSwitch", {"on": 0})


async def _light_on(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service("lightSwitch", {"lightSwitch": 1})


async def _light_off(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service("lightSwitch", {"lightSwitch": 0})


async def _monitor_on(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service("monitoringSwitch", {"on": 1})


async def _monitor_off(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service("monitoringSwitch", {"on": 0})


async def _select_mode(context: DeviceContext, data: Mapping[str, Any]) -> None:
    value = _MODE_VALUES.get(str(data.get("option")))
    if value is None:
        raise ValueError(f"unsupported 2MLE mode: {data.get('option')}")
    await context.async_send_service("mode", {"mode": value})


async def _humidify_on(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service("aromaSwitch", {"on": 1})


async def _humidify_off(context: DeviceContext, _data: Mapping[str, Any]) -> None:
    await context.async_send_service("aromaSwitch", {"on": 0})


async def _humidify_target(context: DeviceContext, data: Mapping[str, Any]) -> None:
    target = _as_int(data.get("humidity"))
    if target is None:
        raise ValueError("2MLE humidity target is required")
    target = max(_HUMIDITY_MIN, min(_HUMIDITY_MAX, target))
    await context.async_send_service("humidity", {"target": target})


async def _fan_set_percentage(
    context: DeviceContext,
    data: Mapping[str, Any],
) -> None:
    percentage = _number(data.get("percentage"))
    if percentage is None:
        raise ValueError("2MLE fan percentage is required")
    gear = round(percentage / _FAN_PERCENTAGE_STEP)
    gear = max(_FAN_MIN_GEAR, min(_FAN_MAX_GEAR, gear))
    await context.async_send_service(
        "fan",
        {"gear": gear, "autoFanSwitch": 0},
    )


async def _fan_set_preset(context: DeviceContext, data: Mapping[str, Any]) -> None:
    preset = str(data.get("preset_mode"))
    if preset == _FAN_PRESET_AUTO:
        await context.async_send_service("fan", {"autoFanSwitch": 1})
    elif preset == _FAN_PRESET_MANUAL:
        await context.async_send_service("fan", {"autoFanSwitch": 0})
    else:
        raise ValueError(f"unsupported 2MLE fan preset: {preset}")


class Product2MLEAdapter:
    """2MLE IAM 智能净化加湿一体机 U7 适配器。"""

    prod_id = "2MLE"

    def entities(self, context: DeviceContext) -> tuple[EntitySpec, ...]:
        profile = context.profile
        if profile is None:
            return ()

        specs: list[EntitySpec] = []

        # --- 电源 -------------------------------------------------------
        if context.has_service("switch"):
            specs.append(
                EntitySpec(
                    platform="switch",
                    key="power",
                    name="电源",
                    state=lambda ctx: {"is_on": _as_bool(ctx.value("switch", "on"))},
                    actions={"turn_on": _power_on, "turn_off": _power_off},
                )
            )

        # --- 童锁（配置） -----------------------------------------------
        if context.has_service("childLockSwitch"):
            specs.append(
                EntitySpec(
                    platform="switch",
                    key="child_lock",
                    name="童锁",
                    state=lambda ctx: {
                        "is_on": _as_bool(ctx.value("childLockSwitch", "on"))
                    },
                    actions={
                        "turn_on": _child_lock_on,
                        "turn_off": _child_lock_off,
                    },
                    metadata={"entity_category": "config"},
                )
            )

        # --- 氛围灯 -----------------------------------------------------
        if context.has_service("lightSwitch"):
            specs.append(
                EntitySpec(
                    platform="switch",
                    key="ambient_light",
                    name="氛围灯",
                    state=lambda ctx: {
                        "is_on": _as_bool(ctx.value("lightSwitch", "lightSwitch"))
                    },
                    actions={"turn_on": _light_on, "turn_off": _light_off},
                )
            )

        # --- 监测模式（配置） -------------------------------------------
        if context.has_service("monitoringSwitch"):
            specs.append(
                EntitySpec(
                    platform="switch",
                    key="monitoring",
                    name="监测模式",
                    state=lambda ctx: {
                        "is_on": _as_bool(ctx.value("monitoringSwitch", "on"))
                    },
                    actions={"turn_on": _monitor_on, "turn_off": _monitor_off},
                    metadata={"entity_category": "config"},
                )
            )

        # --- 模式 -------------------------------------------------------
        if context.has_service("mode"):
            specs.append(
                EntitySpec(
                    platform="select",
                    key="mode",
                    name="模式",
                    state=lambda ctx: {
                        "current_option": _mode_label(ctx.value("mode", "mode"))
                    },
                    metadata={"options": list(_MODE_OPTIONS)},
                    actions={"select_option": _select_mode},
                )
            )

        # --- 加湿（开关 + 目标湿度 + 当前湿度） --------------------------
        if context.has_service("aromaSwitch") and context.has_service("humidity"):
            specs.append(
                EntitySpec(
                    platform="humidifier",
                    key="humidifier",
                    name="加湿",
                    state=lambda ctx: {
                        "is_on": _as_bool(ctx.value("aromaSwitch", "on")),
                        "current_humidity": _as_int(
                            ctx.value("humidity", "current")
                        ),
                        "target_humidity": _as_int(
                            ctx.value("humidity", "target")
                        ),
                    },
                    metadata={
                        "device_class": "humidifier",
                        "min_humidity": _HUMIDITY_MIN,
                        "max_humidity": _HUMIDITY_MAX,
                    },
                    actions={
                        "turn_on": _humidify_on,
                        "turn_off": _humidify_off,
                        "set_humidity": _humidify_target,
                    },
                )
            )

        # --- 风速（档位 + 自动） -----------------------------------------
        if context.has_service("fan") and _field(profile, "fan", "gear") is not None:
            specs.append(
                EntitySpec(
                    platform="fan",
                    key="fan_speed",
                    name="风速",
                    state=lambda ctx: {
                        "is_on": _as_bool(ctx.value("switch", "on")),
                        "percentage": _gear_percentage(ctx.value("fan", "gear")),
                        "preset_mode": (
                            _FAN_PRESET_AUTO
                            if _as_bool(ctx.value("fan", "autoFanSwitch"))
                            else _FAN_PRESET_MANUAL
                        ),
                    },
                    metadata={
                        "supports_percentage": True,
                        "percentage_step": _FAN_PERCENTAGE_STEP,
                        "preset_modes": list(_FAN_PRESETS),
                    },
                    actions={
                        "turn_on": _power_on,
                        "turn_off": _power_off,
                        "set_percentage": _fan_set_percentage,
                        "set_preset_mode": _fan_set_preset,
                    },
                )
            )

        # --- PM2.5 ------------------------------------------------------
        if context.has_service("pm25"):
            specs.append(
                EntitySpec(
                    platform="sensor",
                    key="pm25",
                    name="PM2.5",
                    state=lambda ctx: {
                        "native_value": _as_int(ctx.value("pm25", "current"))
                    },
                    metadata={
                        "device_class": "pm25",
                        "state_class": "measurement",
                        "unit": "µg/m³",
                    },
                )
            )

        # --- 温度 -------------------------------------------------------
        if context.has_service("temperature"):
            specs.append(
                EntitySpec(
                    platform="sensor",
                    key="temperature",
                    name="温度",
                    state=lambda ctx: {
                        "native_value": _number(
                            ctx.value("temperature", "current")
                        )
                    },
                    metadata={
                        "device_class": "temperature",
                        "state_class": "measurement",
                        "unit": "°C",
                    },
                )
            )

        # --- 湿度 -------------------------------------------------------
        if context.has_service("humidity"):
            specs.append(
                EntitySpec(
                    platform="sensor",
                    key="humidity",
                    name="湿度",
                    state=lambda ctx: {
                        "native_value": _as_int(ctx.value("humidity", "current"))
                    },
                    metadata={
                        "device_class": "humidity",
                        "state_class": "measurement",
                        "unit": "%",
                    },
                )
            )

        # --- 空气质量等级 -----------------------------------------------
        if context.has_service("machinePara"):
            specs.append(
                EntitySpec(
                    platform="sensor",
                    key="aqi",
                    name="空气质量",
                    state=lambda ctx: {
                        "native_value": _aqi_label(
                            ctx.value("machinePara", "aqi")
                        )
                    },
                    metadata={},
                )
            )
            specs.append(
                EntitySpec(
                    platform="sensor",
                    key="water_level",
                    name="水量",
                    state=lambda ctx: {
                        "native_value": _as_int(
                            ctx.value("machinePara", "shuiliang")
                        )
                    },
                    metadata={
                        "state_class": "measurement",
                        "unit": "%",
                    },
                )
            )
            specs.append(
                EntitySpec(
                    platform="sensor",
                    key="clean_air_today",
                    name="今日净化量",
                    state=lambda ctx: {
                        "native_value": _as_int(
                            ctx.value("machinePara", "cavPerDay")
                        )
                    },
                    metadata={
                        "state_class": "total_increasing",
                        "unit": "m³",
                    },
                )
            )
            specs.append(
                EntitySpec(
                    platform="sensor",
                    key="outdoor_pm25",
                    name="户外 PM2.5",
                    state=lambda ctx: {
                        "native_value": _as_int(
                            ctx.value("machinePara", "oPM25")
                        )
                    },
                    metadata={
                        "state_class": "measurement",
                        "unit": "µg/m³",
                    },
                )
            )

        # --- 洁净空气累计量 ---------------------------------------------
        if context.has_service("cav"):
            specs.append(
                EntitySpec(
                    platform="sensor",
                    key="clean_air_total",
                    name="洁净空气总量",
                    state=lambda ctx: {
                        "native_value": _number(ctx.value("cav", "current"))
                    },
                    metadata={
                        "state_class": "total_increasing",
                        "unit": "m³",
                    },
                )
            )

        # --- 两个滤网 ---------------------------------------------------
        for sid, key, label in (
            ("filterElement1", "filter_humidify", "加湿滤网"),
            ("filterElement2", "filter_purify", "净化滤网"),
        ):
            if not context.has_service(sid):
                continue

            def _filter_state(
                device: DeviceContext,
                _sid: str = sid,
            ) -> Mapping[str, Any]:
                return {
                    "native_value": _as_int(device.value(_sid, "leftPercentage")),
                    "extra_state_attributes": {
                        "remaining_hours": _as_int(
                            device.value(_sid, "leftTime")
                        )
                    },
                }

            specs.append(
                EntitySpec(
                    platform="sensor",
                    key=key,
                    name=label,
                    state=_filter_state,
                    metadata={
                        "state_class": "measurement",
                        "unit": "%",
                        "entity_category": "diagnostic",
                    },
                )
            )

        # --- 故障 -------------------------------------------------------
        if context.has_service("faultDetection"):
            specs.append(
                EntitySpec(
                    platform="binary_sensor",
                    key="fault",
                    name="故障",
                    state=lambda ctx: {
                        "is_on": _as_bool(ctx.value("faultDetection", "status"))
                    },
                    metadata={
                        "device_class": "problem",
                        "entity_category": "diagnostic",
                    },
                )
            )
            specs.append(
                EntitySpec(
                    platform="sensor",
                    key="fault_code",
                    name="故障码",
                    state=lambda ctx: {
                        "native_value": _fault_label(
                            ctx.value("faultDetection", "code")
                        )
                    },
                    metadata={"entity_category": "diagnostic"},
                )
            )

        # --- workStatus 未做实体 -----------------------------------------
        # 实测: 电源开、模式自动、风速 40%、加湿运行中，machinePara.workStatus
        # 仍恒为 0；与"机器是否在运转"无关，故不暴露 binary_sensor「运行中」。

        return tuple(specs)


ADAPTER = Product2MLEAdapter()
