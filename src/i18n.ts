// SPDX-License-Identifier: BSD-3-Clause
// Copyright (c) 2026 Rayekkk
// Legion Go 1 port
// https://github.com/Rayekkk/LeGoTDP

/**
 * Three languages, one string table.
 *
 * English is the source of truth: `Key` is derived from it, so every other
 * table is a `Record<Key, string>` and a missing or misspelled string is a
 * compile error rather than a blank label on the device.
 *
 * Placeholders are `{name}` style and substituted by `t()`. They are the same
 * in every language, which is what lets the check above be purely structural.
 */

export type Lang = "en" | "ru" | "es";

export const LANGS: Lang[] = ["en", "ru", "es"];

export const LANG_NAMES: Record<Lang, string> = {
  en: "English",
  ru: "Русский",
  es: "Español",
};

const EN = {
  // -- master panel ---------------------------------------------------------
  "panel.enable": "Enable",
  "panel.usingDefaults": "Using system defaults",
  "panel.global": "Global profile: ",
  "panel.globalBattery": "Global (battery): ",
  "panel.globalAc": " AC: ",
  "panel.exceeds": " ⚠ exceeds firmware limits",
  "panel.conflict":
    "Another TDP controller was detected: {list}. Two tools driving the same limits will overwrite each other - turn one of them off.",
  "panel.initializing": "Initializing...",
  "panel.setupError": "Setup Error",
  "panel.error": "Error",

  // -- status card ----------------------------------------------------------
  "card.limit": "TDP limit",
  "card.now": "drawing now",
  "card.backend": "Backend",
  "card.noBackend": "no backend",

  // -- live readings --------------------------------------------------------
  "live.title": "Current TDP",
  "live.spl": "TDP limit (SPL)",
  "live.sppt": "Slow limit (SPPT)",
  "live.fppt": "Fast limit (FPPT)",
  "live.draw": "Current package power",
  "live.setTo": "Set to {value}",
  "live.appliedVia": "applied via {backend}",
  "live.readFailed": "Failed to read TDP",

  // -- game profile ---------------------------------------------------------
  "game.title": "Game Profile",
  "game.perGame": "Per-game profile",
  "game.noGame": "No game running",
  "game.battery": "Battery: ",
  "game.ac": "AC: ",

  // -- power source ---------------------------------------------------------
  "power.title": "Power Source",
  "power.separate": "Separate charger profile",
  "power.separateOnGame": "{name}: battery and charger have their own TDP",
  "power.separateOn": "Battery and charger have their own TDP",
  "power.separateOff": "Enable to run a different TDP while the charger is plugged in",
  "power.batteryProfile": "Battery profile",
  "power.acProfile": "AC profile",
  "power.charging": "Charging (AC)",
  "power.onBattery": "On battery",

  // -- presets --------------------------------------------------------------
  "preset.title": "Preset",
  "preset.minimum": "Minimum",
  "preset.silent": "Silent",
  "preset.balanced": "Balanced",
  "preset.performance": "Performance",
  "preset.max": "Max",
  "preset.custom": "Custom",
  "preset.customValue": "Custom ({spl} +{sppt}/+{fppt})",

  // -- sliders --------------------------------------------------------------
  "limits.title": "TDP Limits",
  "limits.titleAc": "TDP Limits (AC)",
  "limits.spl": "SPL (TDP) - {value} W",
  "limits.splDesc": "Sustained power limit - the main TDP dial",
  "limits.sppt": "SPPT +{offset} W  =  {total} W",
  "limits.spptDesc": "Slow limit headroom above SPL (max +{max} W here)",
  "limits.fppt": "FPPT +{offset} W  =  {total} W",
  "limits.fpptDesc": "Fast limit headroom above SPL (max +{max} W here)",
  "limits.noHeadroom": "No headroom left at this SPL",

  // -- action ---------------------------------------------------------------
  "action.title": "Action",
  "action.apply": "Apply TDP",
  "action.applying": "Applying...",
  "action.saveFor": "Apply & save for {name}",
  "action.saveAcFor": "Save AC for {name}",

  // -- diagnostics ----------------------------------------------------------
  "diag.title": "Diagnostics",
  "diag.show": "Show diagnostics",
  "diag.refresh": "Refresh",
  "diag.reading": "Reading...",
  "diag.device": "Device",
  "diag.model": "Model",
  "diag.cpu": "CPU",
  "diag.biosKernel": "BIOS / kernel",
  "diag.biosBaseline": "the version this build targets",
  "diag.biosOlder": "older than {baseline}, the version this build targets",
  "diag.biosNewer": "newer than {baseline}, the version this build targets",
  "diag.biosWithdrawn": "withdrawn by Lenovo after boot failures were reported",
  "diag.activeBackend": "Active backend",
  "diag.available": "Available",
  "diag.unavailable": "Unavailable",
  "diag.splRange": "SPL range",
  "diag.spptRange": "SPPT range",
  "diag.fpptRange": "FPPT range",
  "diag.currentlySet": "Currently set",
  "diag.firmwareMode": "Firmware power mode",
  "diag.version": "Plugin version",
  "diag.sourceFirmware": "firmware",
  "diag.sourceProfile": "device profile",
  "diag.rangeOf": "{min} - {max} W  ({source})",
  "diag.of": "of {list}",
  "diag.failed": "Diagnostics failed",

  // -- extras ---------------------------------------------------------------
  "extras.title": "Extras",
  "extras.warning":
    "These settings are for advanced users only and are NOT recommended. Changes are made at your own risk - they override the manufacturer's TDP safety limits.",
  "extras.unlock": "Unlock Custom TDP to {max} W",
  "extras.on": "Custom sliders extended to {max} W - applied via ryzenadj instead of firmware",
  "extras.off": "Enable to allow Custom sliders up to {max} W",

  // -- fans -----------------------------------------------------------------
  "fan.title": "Fans",
  "fan.mode": "Fan mode",
  "fan.auto": "Auto",
  "fan.quiet": "Quiet",
  "fan.balanced": "Balanced",
  "fan.cool": "Cool",
  "fan.max": "Max",
  "fan.autoDesc": "The firmware decides, as it does out of the box",
  "fan.curveDesc": "A fixed curve, never below what the firmware allows",
  "fan.maxDesc": "Fans at full speed until you change this back",
  "fan.unsupported": "Fan control needs the firmware interface (acpi_call)",
  "fan.speed": "Fan speed",
  "fan.rpm": "{value} rpm",

  // -- readings -------------------------------------------------------------
  "live.temp": "SoC temperature",
  "card.temp": "temperature",

  // -- conflicts and backend detail (built by the backend, worded here) ------
  "conflict.process": "{name} is running and also sets TDP",
  "conflict.plugin": "the {name} Decky plugin is installed",
  "backend.wmi.ready": "the kernel driver is bound and a platform profile offers 'custom'",
  "backend.wmi.noCustomProfile": "lenovo-wmi-other is present but no platform profile offers 'custom'",
  "backend.wmi.absent": "lenovo-wmi-other attributes not present (needs Linux 6.17 or newer)",
  "backend.acpi.mode": "firmware power mode: {mode}",
  "backend.acpi.absent": "acpi_call is not loaded, or this firmware does not answer GameZone",
  "backend.acpi.unused": "not used on this device",
  "backend.ryzenadj.verified": "verified copy at {path}",
  "backend.ryzenadj.system": "unverified system copy at {path}",
  "backend.ryzenadj.absent": "ryzenadj is not available",
  "backend.ryzenadj.notUsed": "not installed on this device",

  // -- battery --------------------------------------------------------------
  "battery.title": "Battery",
  "battery.limit": "Limit charge to 80%",
  "battery.limitOn": "Charging stops at 80% to spare the cells",
  "battery.limitOff": "The battery charges to full",
  "battery.unsupported": "This system exposes no charge limit control",
  "battery.via": "via {source}",

  // -- tabs and enhancers ---------------------------------------------------
  "tab.tdp": "Power",
  "tab.enhancers": "Enhancers",
  "tab.hint": "R1 / R2 switches tab",
  "enhancer.title": "Enhancers",
  "enhancer.intro":
    "Tools on this machine that change how a game looks or how many frames it makes. LTDP reports them; it does not drive them - each has its own plugin or launcher.",
  "enhancer.installed": "Installed",
  "enhancer.missing": "Not installed",
  "enhancer.mako.desc":
    "Frame generation through a Vulkan layer. A separate Decky plugin, GPL-3.0, and it needs a licensed copy of Lossless Scaling.",
  "enhancer.makoRenderer.desc":
    "MAKO's renderer, installed into ~/.local/bin by its own plugin.",
  "enhancer.lossless.desc":
    "The Steam app MAKO reads its frame-generation model from. Bought separately.",
  "enhancer.mangohud.desc": "The on-screen overlay for frame rate, frame times and power.",
  "enhancer.vkbasalt.desc": "Post-processing: sharpening, FXAA, custom shaders.",
  "enhancer.why":
    "Frame generation and a TDP limit are two halves of the same decision: generated frames are what let the limit come down.",
  "enhancer.refresh": "Rescan",

  // -- updates --------------------------------------------------------------
  "update.title": "Updates",
  "update.installed": "Installed",
  "update.latest": "Latest",
  "update.check": "Check for updates",
  "update.checking": "Checking...",
  "update.upToDate": "Up to date",
  "update.download": "Download v{version}",
  "update.downloading": "Downloading...",
  "update.downloadedTo": "Downloaded to {path}",
  "update.howToInstall":
    "To install: Decky - Developer - Install Plugin from ZIP - pick the file. Your settings and per-game profiles are kept.",
  "update.failed": "Update check failed",
  "update.downloadFailed": "Download failed",

  // -- language -------------------------------------------------------------
  "lang.title": "Language",

  // -- status lines ---------------------------------------------------------
  "status.presetApplied": "{preset} applied.",
  "status.presetSavedFor": "{preset} saved for {name}.",
  "status.acPresetSaved": "AC: {preset} saved.",
  "status.acPresetSavedFor": "AC: {preset} saved for {name}.",
  "status.customApplied": "Custom settings applied.",
  "status.profileSavedFor": "Profile saved for {name}.",
  "status.acProfileSaved": "AC profile saved.",
  "status.acProfileSavedFor": "AC profile saved for {name}.",
  "status.globalRestored": "Global settings restored.",
  "status.switchedToGlobal": "Switched to global settings.",
  "status.autoApplied": "Auto-applied profile for {name}.",
  "status.profileApplied": "Profile applied for {name}.",
  "status.noProfile": "No saved profile for {name}. Use the sliders to create one.",
  "status.enabled": "Plugin enabled.",
  "status.disabled": "Plugin disabled. Firmware defaults restored.",
  "status.acOn": "Separate charger profile enabled.",
  "status.acOff": "One profile for battery and charger.",
  "status.chargeLimitOn": "Charging will stop at 80%.",
  "status.chargeLimitOff": "The battery will charge to full.",
  "status.errorPrefix": "Error: {message}",
  "status.unknownError": "unknown",
  "status.profileCorrupt": "Error: game profile data is missing or corrupt.",

  // -- errors ---------------------------------------------------------------
  "error.applyFailed": "TDP apply failed",
  "error.couldNotApply": "Could not apply TDP",
  "error.couldNotDelete": "Could not delete profile",
  "error.couldNotToggle": "Could not change plugin state",
  "error.couldNotAc": "Could not change AC profile",
  "error.couldNotSaveAc": "Could not save AC profile",
  "error.couldNotExtras": "Could not change Extras range",
  "error.couldNotChargeLimit": "Could not change the charge limit",
  "error.couldNotLanguage": "Could not save the language",
} as const;

export type Key = keyof typeof EN;

const RU: Record<Key, string> = {
  "panel.enable": "Включить",
  "panel.usingDefaults": "Используются системные значения",
  "panel.global": "Глобальный профиль: ",
  "panel.globalBattery": "Глобальный (батарея): ",
  "panel.globalAc": " Зарядка: ",
  "panel.exceeds": " ⚠ выше лимитов прошивки",
  "panel.conflict":
    "Обнаружен другой регулятор TDP: {list}. Две программы, управляющие одними лимитами, будут перезаписывать друг друга - выключите одну.",
  "panel.initializing": "Инициализация...",
  "panel.setupError": "Ошибка запуска",
  "panel.error": "Ошибка",

  "card.limit": "лимит TDP",
  "card.now": "потребляет сейчас",
  "card.backend": "Бэкенд",
  "card.noBackend": "нет бэкенда",

  "live.title": "Текущий TDP",
  "live.spl": "Лимит TDP (SPL)",
  "live.sppt": "Медленный лимит (SPPT)",
  "live.fppt": "Быстрый лимит (FPPT)",
  "live.draw": "Фактическое потребление",
  "live.setTo": "Установлено {value}",
  "live.appliedVia": "применено через {backend}",
  "live.readFailed": "Не удалось прочитать TDP",

  "game.title": "Профиль игры",
  "game.perGame": "Профиль для игры",
  "game.noGame": "Игра не запущена",
  "game.battery": "Батарея: ",
  "game.ac": "Зарядка: ",

  "power.title": "Источник питания",
  "power.separate": "Отдельный профиль для зарядки",
  "power.separateOnGame": "{name}: у батареи и зарядки свой TDP",
  "power.separateOn": "У батареи и зарядки свой TDP",
  "power.separateOff": "Включите, чтобы задать другой TDP при подключённой зарядке",
  "power.batteryProfile": "Профиль батареи",
  "power.acProfile": "Профиль зарядки",
  "power.charging": "Зарядка подключена",
  "power.onBattery": "От батареи",

  "preset.title": "Пресет",
  "preset.minimum": "Минимум",
  "preset.silent": "Тихий",
  "preset.balanced": "Баланс",
  "preset.performance": "Производительность",
  "preset.max": "Максимум",
  "preset.custom": "Свой",
  "preset.customValue": "Свой ({spl} +{sppt}/+{fppt})",

  "limits.title": "Лимиты TDP",
  "limits.titleAc": "Лимиты TDP (зарядка)",
  "limits.spl": "SPL (TDP) - {value} Вт",
  "limits.splDesc": "Устойчивый лимит мощности - основной регулятор TDP",
  "limits.sppt": "SPPT +{offset} Вт  =  {total} Вт",
  "limits.spptDesc": "Запас медленного лимита над SPL (здесь максимум +{max} Вт)",
  "limits.fppt": "FPPT +{offset} Вт  =  {total} Вт",
  "limits.fpptDesc": "Запас быстрого лимита над SPL (здесь максимум +{max} Вт)",
  "limits.noHeadroom": "При таком SPL запаса не осталось",

  "action.title": "Действие",
  "action.apply": "Применить TDP",
  "action.applying": "Применяю...",
  "action.saveFor": "Применить и сохранить для {name}",
  "action.saveAcFor": "Сохранить профиль зарядки для {name}",

  "diag.title": "Диагностика",
  "diag.show": "Показать диагностику",
  "diag.refresh": "Обновить",
  "diag.reading": "Читаю...",
  "diag.device": "Устройство",
  "diag.model": "Модель",
  "diag.cpu": "Процессор",
  "diag.biosKernel": "BIOS / ядро",
  "diag.biosBaseline": "версия, под которую сделана эта сборка",
  "diag.biosOlder": "старее {baseline} — версии, под которую сделана сборка",
  "diag.biosNewer": "новее {baseline} — версии, под которую сделана сборка",
  "diag.biosWithdrawn": "отозвана Lenovo после сообщений о незагружающихся устройствах",
  "diag.activeBackend": "Активный бэкенд",
  "diag.available": "Доступен",
  "diag.unavailable": "Недоступен",
  "diag.splRange": "Диапазон SPL",
  "diag.spptRange": "Диапазон SPPT",
  "diag.fpptRange": "Диапазон FPPT",
  "diag.currentlySet": "Сейчас установлено",
  "diag.firmwareMode": "Режим питания прошивки",
  "diag.version": "Версия плагина",
  "diag.sourceFirmware": "из прошивки",
  "diag.sourceProfile": "профиль устройства",
  "diag.rangeOf": "{min} - {max} Вт  ({source})",
  "diag.of": "из {list}",
  "diag.failed": "Диагностика не удалась",

  "extras.title": "Дополнительно",
  "extras.warning":
    "Только для опытных пользователей, НЕ рекомендуется. Вы делаете это на свой риск - настройки выходят за пределы, заданные производителем.",
  "extras.unlock": "Разблокировать свой TDP до {max} Вт",
  "extras.on": "Ползунки расширены до {max} Вт - применяется через ryzenadj, а не прошивку",
  "extras.off": "Включите, чтобы поднять предел ползунков до {max} Вт",

  "fan.title": "Вентиляторы",
  "fan.mode": "Режим вентиляторов",
  "fan.auto": "Авто",
  "fan.quiet": "Тихо",
  "fan.balanced": "Баланс",
  "fan.cool": "Холод",
  "fan.max": "Максимум",
  "fan.autoDesc": "Решает прошивка — как из коробки",
  "fan.curveDesc": "Фиксированная кривая, не ниже разрешённой прошивкой",
  "fan.maxDesc": "Вентиляторы на полную, пока вы это не смените",
  "fan.unsupported": "Управление вентиляторами требует интерфейса прошивки (acpi_call)",
  "fan.speed": "Обороты",
  "fan.rpm": "{value} об/мин",

  "live.temp": "Температура SoC",
  "card.temp": "температура",

  "conflict.process": "{name} запущен и тоже управляет TDP",
  "conflict.plugin": "установлен плагин {name}",
  "backend.wmi.ready": "драйвер ядра загружен, и platform profile предлагает «custom»",
  "backend.wmi.noCustomProfile": "lenovo-wmi-other есть, но ни один platform profile не предлагает «custom»",
  "backend.wmi.absent": "атрибутов lenovo-wmi-other нет (нужно ядро 6.17 или новее)",
  "backend.acpi.mode": "режим питания прошивки: {mode}",
  "backend.acpi.absent": "acpi_call не загружен, или эта прошивка не отвечает на GameZone",
  "backend.acpi.unused": "на этом устройстве не используется",
  "backend.ryzenadj.verified": "проверенная копия в {path}",
  "backend.ryzenadj.system": "непроверенная системная копия в {path}",
  "backend.ryzenadj.absent": "ryzenadj недоступен",
  "backend.ryzenadj.notUsed": "на этом устройстве не устанавливается",

  "battery.title": "Батарея",
  "battery.limit": "Ограничить заряд до 80%",
  "battery.limitOn": "Зарядка останавливается на 80%, чтобы беречь ячейки",
  "battery.limitOff": "Батарея заряжается полностью",
  "battery.unsupported": "Эта система не даёт управлять лимитом заряда",
  "battery.via": "через {source}",

  "tab.tdp": "Питание",
  "tab.enhancers": "Улучшайзеры",
  "tab.hint": "R1 / R2 — переключить вкладку",
  "enhancer.title": "Улучшайзеры",
  "enhancer.intro":
    "Инструменты на этой машине, которые меняют картинку или число кадров. LTDP их показывает, но не управляет ими — у каждого свой плагин или запускалка.",
  "enhancer.installed": "Установлено",
  "enhancer.missing": "Не установлено",
  "enhancer.mako.desc":
    "Генерация кадров через слой Vulkan. Отдельный плагин Decky, лицензия GPL-3.0, нужен купленный Lossless Scaling.",
  "enhancer.makoRenderer.desc":
    "Рендерер MAKO, его собственный плагин ставит его в ~/.local/bin.",
  "enhancer.lossless.desc":
    "Приложение Steam, из которого MAKO берёт модель генерации кадров. Покупается отдельно.",
  "enhancer.mangohud.desc": "Оверлей с кадрами, временем кадра и потреблением.",
  "enhancer.vkbasalt.desc": "Постобработка: резкость, FXAA, свои шейдеры.",
  "enhancer.why":
    "Генерация кадров и лимит TDP — две половины одного решения: сгенерированные кадры и позволяют опустить лимит.",
  "enhancer.refresh": "Пересканировать",

  "update.title": "Обновления",
  "update.installed": "Установлено",
  "update.latest": "Доступно",
  "update.check": "Проверить обновления",
  "update.checking": "Проверяю...",
  "update.upToDate": "Установлена последняя версия",
  "update.download": "Скачать v{version}",
  "update.downloading": "Скачиваю...",
  "update.downloadedTo": "Скачано в {path}",
  "update.howToInstall":
    "Установка: Decky - Developer - Install Plugin from ZIP - выбрать файл. Настройки и профили игр сохранятся.",
  "update.failed": "Не удалось проверить обновления",
  "update.downloadFailed": "Не удалось скачать",

  "lang.title": "Язык",

  "status.presetApplied": "Применён пресет {preset}.",
  "status.presetSavedFor": "{preset} сохранён для {name}.",
  "status.acPresetSaved": "Зарядка: {preset} сохранён.",
  "status.acPresetSavedFor": "Зарядка: {preset} сохранён для {name}.",
  "status.customApplied": "Свои настройки применены.",
  "status.profileSavedFor": "Профиль сохранён для {name}.",
  "status.acProfileSaved": "Профиль зарядки сохранён.",
  "status.acProfileSavedFor": "Профиль зарядки сохранён для {name}.",
  "status.globalRestored": "Глобальные настройки восстановлены.",
  "status.switchedToGlobal": "Переключено на глобальные настройки.",
  "status.autoApplied": "Профиль {name} применён автоматически.",
  "status.profileApplied": "Профиль применён для {name}.",
  "status.noProfile": "Для {name} профиля нет. Задайте его ползунками.",
  "status.enabled": "Плагин включён.",
  "status.disabled": "Плагин выключен. Значения прошивки восстановлены.",
  "status.acOn": "Отдельный профиль для зарядки включён.",
  "status.acOff": "Один профиль для батареи и зарядки.",
  "status.chargeLimitOn": "Зарядка будет останавливаться на 80%.",
  "status.chargeLimitOff": "Батарея будет заряжаться полностью.",
  "status.errorPrefix": "Ошибка: {message}",
  "status.unknownError": "неизвестно",
  "status.profileCorrupt": "Ошибка: данные профиля игры повреждены или отсутствуют.",

  "error.applyFailed": "Не удалось применить TDP",
  "error.couldNotApply": "Не удалось применить TDP",
  "error.couldNotDelete": "Не удалось удалить профиль",
  "error.couldNotToggle": "Не удалось изменить состояние плагина",
  "error.couldNotAc": "Не удалось изменить профиль зарядки",
  "error.couldNotSaveAc": "Не удалось сохранить профиль зарядки",
  "error.couldNotExtras": "Не удалось изменить диапазон Extras",
  "error.couldNotChargeLimit": "Не удалось изменить лимит заряда",
  "error.couldNotLanguage": "Не удалось сохранить язык",
};

const ES: Record<Key, string> = {
  "panel.enable": "Activar",
  "panel.usingDefaults": "Usando los valores del sistema",
  "panel.global": "Perfil global: ",
  "panel.globalBattery": "Global (batería): ",
  "panel.globalAc": " CA: ",
  "panel.exceeds": " ⚠ supera los límites del firmware",
  "panel.conflict":
    "Se detectó otro controlador de TDP: {list}. Dos herramientas ajustando los mismos límites se sobrescriben entre sí - desactiva una de ellas.",
  "panel.initializing": "Iniciando...",
  "panel.setupError": "Error de arranque",
  "panel.error": "Error",

  "card.limit": "límite de TDP",
  "card.now": "consumo actual",
  "card.backend": "Backend",
  "card.noBackend": "sin backend",

  "live.title": "TDP actual",
  "live.spl": "Límite de TDP (SPL)",
  "live.sppt": "Límite lento (SPPT)",
  "live.fppt": "Límite rápido (FPPT)",
  "live.draw": "Consumo real del paquete",
  "live.setTo": "Ajustado a {value}",
  "live.appliedVia": "aplicado mediante {backend}",
  "live.readFailed": "No se pudo leer el TDP",

  "game.title": "Perfil de juego",
  "game.perGame": "Perfil por juego",
  "game.noGame": "Ningún juego en ejecución",
  "game.battery": "Batería: ",
  "game.ac": "CA: ",

  "power.title": "Fuente de alimentación",
  "power.separate": "Perfil aparte con el cargador",
  "power.separateOnGame": "{name}: la batería y el cargador tienen su propio TDP",
  "power.separateOn": "La batería y el cargador tienen su propio TDP",
  "power.separateOff": "Actívalo para usar otro TDP con el cargador conectado",
  "power.batteryProfile": "Perfil de batería",
  "power.acProfile": "Perfil de CA",
  "power.charging": "Cargando (CA)",
  "power.onBattery": "Con batería",

  "preset.title": "Preajuste",
  "preset.minimum": "Mínimo",
  "preset.silent": "Silencioso",
  "preset.balanced": "Equilibrado",
  "preset.performance": "Rendimiento",
  "preset.max": "Máximo",
  "preset.custom": "Personalizado",
  "preset.customValue": "Personalizado ({spl} +{sppt}/+{fppt})",

  "limits.title": "Límites de TDP",
  "limits.titleAc": "Límites de TDP (CA)",
  "limits.spl": "SPL (TDP) - {value} W",
  "limits.splDesc": "Límite de potencia sostenida - el ajuste principal de TDP",
  "limits.sppt": "SPPT +{offset} W  =  {total} W",
  "limits.spptDesc": "Margen del límite lento sobre el SPL (aquí máx. +{max} W)",
  "limits.fppt": "FPPT +{offset} W  =  {total} W",
  "limits.fpptDesc": "Margen del límite rápido sobre el SPL (aquí máx. +{max} W)",
  "limits.noHeadroom": "No queda margen con este SPL",

  "action.title": "Acción",
  "action.apply": "Aplicar TDP",
  "action.applying": "Aplicando...",
  "action.saveFor": "Aplicar y guardar para {name}",
  "action.saveAcFor": "Guardar perfil de CA para {name}",

  "diag.title": "Diagnóstico",
  "diag.show": "Mostrar diagnóstico",
  "diag.refresh": "Actualizar",
  "diag.reading": "Leyendo...",
  "diag.device": "Dispositivo",
  "diag.model": "Modelo",
  "diag.cpu": "CPU",
  "diag.biosKernel": "BIOS / kernel",
  "diag.biosBaseline": "la versión para la que se hizo esta compilación",
  "diag.biosOlder": "anterior a {baseline}, la versión objetivo de esta compilación",
  "diag.biosNewer": "posterior a {baseline}, la versión objetivo de esta compilación",
  "diag.biosWithdrawn": "retirada por Lenovo tras informes de equipos que no arrancaban",
  "diag.activeBackend": "Backend activo",
  "diag.available": "Disponible",
  "diag.unavailable": "No disponible",
  "diag.splRange": "Rango de SPL",
  "diag.spptRange": "Rango de SPPT",
  "diag.fpptRange": "Rango de FPPT",
  "diag.currentlySet": "Ajustado ahora",
  "diag.firmwareMode": "Modo de energía del firmware",
  "diag.version": "Versión del plugin",
  "diag.sourceFirmware": "del firmware",
  "diag.sourceProfile": "perfil del dispositivo",
  "diag.rangeOf": "{min} - {max} W  ({source})",
  "diag.of": "de {list}",
  "diag.failed": "El diagnóstico falló",

  "extras.title": "Extras",
  "extras.warning":
    "Solo para usuarios avanzados y NO recomendado. Los cambios son bajo tu responsabilidad: sobrepasan los límites de seguridad de TDP del fabricante.",
  "extras.unlock": "Desbloquear el TDP personalizado hasta {max} W",
  "extras.on": "Deslizadores ampliados a {max} W - aplicados con ryzenadj en vez del firmware",
  "extras.off": "Actívalo para permitir deslizadores hasta {max} W",

  "fan.title": "Ventiladores",
  "fan.mode": "Modo de ventiladores",
  "fan.auto": "Automático",
  "fan.quiet": "Silencioso",
  "fan.balanced": "Equilibrado",
  "fan.cool": "Frío",
  "fan.max": "Máximo",
  "fan.autoDesc": "Lo decide el firmware, como de fábrica",
  "fan.curveDesc": "Una curva fija, nunca por debajo de lo que permite el firmware",
  "fan.maxDesc": "Ventiladores al máximo hasta que lo cambies",
  "fan.unsupported": "El control de ventiladores necesita la interfaz del firmware (acpi_call)",
  "fan.speed": "Velocidad del ventilador",
  "fan.rpm": "{value} rpm",

  "live.temp": "Temperatura del SoC",
  "card.temp": "temperatura",

  "conflict.process": "{name} está en ejecución y también ajusta el TDP",
  "conflict.plugin": "el plugin {name} está instalado",
  "backend.wmi.ready": "el controlador del kernel está cargado y un perfil de plataforma ofrece «custom»",
  "backend.wmi.noCustomProfile": "lenovo-wmi-other está presente pero ningún perfil de plataforma ofrece «custom»",
  "backend.wmi.absent": "los atributos de lenovo-wmi-other no están presentes (requiere Linux 6.17 o posterior)",
  "backend.acpi.mode": "modo de energía del firmware: {mode}",
  "backend.acpi.absent": "acpi_call no está cargado, o este firmware no responde a GameZone",
  "backend.acpi.unused": "no se usa en este dispositivo",
  "backend.ryzenadj.verified": "copia verificada en {path}",
  "backend.ryzenadj.system": "copia del sistema sin verificar en {path}",
  "backend.ryzenadj.absent": "ryzenadj no está disponible",
  "backend.ryzenadj.notUsed": "no se instala en este dispositivo",

  "battery.title": "Batería",
  "battery.limit": "Limitar la carga al 80%",
  "battery.limitOn": "La carga se detiene al 80% para cuidar las celdas",
  "battery.limitOff": "La batería se carga por completo",
  "battery.unsupported": "Este sistema no permite controlar el límite de carga",
  "battery.via": "mediante {source}",

  "tab.tdp": "Energía",
  "tab.enhancers": "Mejoras",
  "tab.hint": "R1 / R2 cambia de pestaña",
  "enhancer.title": "Mejoras",
  "enhancer.intro":
    "Herramientas de este equipo que cambian cómo se ve un juego o cuántos fotogramas produce. LTDP las muestra; no las controla: cada una tiene su propio plugin o lanzador.",
  "enhancer.installed": "Instalado",
  "enhancer.missing": "No instalado",
  "enhancer.mako.desc":
    "Generación de fotogramas mediante una capa Vulkan. Es un plugin de Decky aparte, GPL-3.0, y necesita una copia con licencia de Lossless Scaling.",
  "enhancer.makoRenderer.desc":
    "El renderizador de MAKO, instalado en ~/.local/bin por su propio plugin.",
  "enhancer.lossless.desc":
    "La aplicación de Steam de la que MAKO toma su modelo de generación de fotogramas. Se compra aparte.",
  "enhancer.mangohud.desc": "La superposición de fotogramas, tiempos de fotograma y consumo.",
  "enhancer.vkbasalt.desc": "Posprocesado: nitidez, FXAA, shaders propios.",
  "enhancer.why":
    "La generación de fotogramas y el límite de TDP son dos mitades de la misma decisión: los fotogramas generados son lo que permite bajar el límite.",
  "enhancer.refresh": "Volver a escanear",

  "update.title": "Actualizaciones",
  "update.installed": "Instalada",
  "update.latest": "Disponible",
  "update.check": "Buscar actualizaciones",
  "update.checking": "Buscando...",
  "update.upToDate": "Ya está actualizado",
  "update.download": "Descargar v{version}",
  "update.downloading": "Descargando...",
  "update.downloadedTo": "Descargado en {path}",
  "update.howToInstall":
    "Para instalar: Decky - Developer - Install Plugin from ZIP - elige el archivo. Tus ajustes y perfiles por juego se conservan.",
  "update.failed": "No se pudo buscar actualizaciones",
  "update.downloadFailed": "La descarga falló",

  "lang.title": "Idioma",

  "status.presetApplied": "{preset} aplicado.",
  "status.presetSavedFor": "{preset} guardado para {name}.",
  "status.acPresetSaved": "CA: {preset} guardado.",
  "status.acPresetSavedFor": "CA: {preset} guardado para {name}.",
  "status.customApplied": "Ajustes personalizados aplicados.",
  "status.profileSavedFor": "Perfil guardado para {name}.",
  "status.acProfileSaved": "Perfil de CA guardado.",
  "status.acProfileSavedFor": "Perfil de CA guardado para {name}.",
  "status.globalRestored": "Ajustes globales restaurados.",
  "status.switchedToGlobal": "Se cambió a los ajustes globales.",
  "status.autoApplied": "Perfil aplicado automáticamente para {name}.",
  "status.profileApplied": "Perfil aplicado para {name}.",
  "status.noProfile": "No hay perfil guardado para {name}. Créalo con los deslizadores.",
  "status.enabled": "Plugin activado.",
  "status.disabled": "Plugin desactivado. Valores del firmware restaurados.",
  "status.acOn": "Perfil aparte con el cargador activado.",
  "status.acOff": "Un solo perfil para batería y cargador.",
  "status.chargeLimitOn": "La carga se detendrá al 80%.",
  "status.chargeLimitOff": "La batería se cargará por completo.",
  "status.errorPrefix": "Error: {message}",
  "status.unknownError": "desconocido",
  "status.profileCorrupt": "Error: faltan los datos del perfil de juego o están dañados.",

  "error.applyFailed": "No se pudo aplicar el TDP",
  "error.couldNotApply": "No se pudo aplicar el TDP",
  "error.couldNotDelete": "No se pudo borrar el perfil",
  "error.couldNotToggle": "No se pudo cambiar el estado del plugin",
  "error.couldNotAc": "No se pudo cambiar el perfil de CA",
  "error.couldNotSaveAc": "No se pudo guardar el perfil de CA",
  "error.couldNotExtras": "No se pudo cambiar el rango de Extras",
  "error.couldNotChargeLimit": "No se pudo cambiar el límite de carga",
  "error.couldNotLanguage": "No se pudo guardar el idioma",
};

const TABLES: Record<Lang, Record<Key, string>> = { en: EN, ru: RU, es: ES };

export type Translate = (key: Key, params?: Record<string, string | number>) => string;

/** Look a key up and substitute `{placeholders}`. */
export function translate(lang: Lang, key: Key, params?: Record<string, string | number>): string {
  const template = TABLES[lang][key] ?? TABLES.en[key] ?? key;
  if (!params) return template;
  return template.replace(/\{(\w+)\}/g, (whole, name) =>
    name in params ? String(params[name]) : whole);
}

/**
 * The language to open on before anything has been saved.
 *
 * Steam's own language is what the user already chose once, and the browser
 * locale inside the client follows it. Anything that is not Russian gets
 * English, which is the table every other string falls back to anyway.
 */
export function detectLang(): Lang {
  try {
    const locales: string[] = [
      (window as any)?.LocalizationManager?.m_strLocale,
      navigator?.language,
      ...(navigator?.languages ?? []),
    ].filter((l): l is string => typeof l === "string");
    const first = (prefix: string) => locales.some(
      (l) => l.toLowerCase().startsWith(prefix));
    if (first("ru")) return "ru";
    if (first("es")) return "es";
  } catch {
    /* the client is free to expose none of this */
  }
  return "en";
}

export function isLang(value: unknown): value is Lang {
  return LANGS.includes(value as Lang);
}
