window.__ModuleLoader__.load({
  id: '@steelai/dsh-client-deepseek-offpeak',
  factory: (require) => {
    const scheduleModule = { exports: {} }
    ;((module, exports) => {
      'use strict'
      
      const DAY_SECONDS = 24 * 60 * 60
      const VALID_SEGMENTS = new Set(['peak', 'off_peak'])
      const VALID_AUTHORITIES = new Set(['approved', 'estimate'])
      const VALID_WEEKDAYS = new Set([1, 2, 3, 4, 5, 6, 7])
      
      function unavailable(reason, detail) {
        return {
          available: false,
          reason,
          detail,
          segment: 'unknown',
          tier: 'UNKNOWN',
          remainingMs: null,
          nextSwitchAt: null,
          authority: 'unknown',
        }
      }
      
      function parseClock(value) {
        if (typeof value !== 'string' || !/^(?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d)?$/.test(value)) {
          return null
        }
        const [hour, minute, second = 0] = value.split(':').map(Number)
        return hour * 3600 + minute * 60 + second
      }
      
      function datePartsToOrdinal({ year, month, day }) {
        return Math.floor(Date.UTC(year, month - 1, day) / 86_400_000)
      }
      
      function ordinalToDateParts(ordinal) {
        const value = new Date(ordinal * 86_400_000)
        return {
          year: value.getUTCFullYear(),
          month: value.getUTCMonth() + 1,
          day: value.getUTCDate(),
        }
      }
      
      function createFormatter(timeZone) {
        return new Intl.DateTimeFormat('en-CA', {
          timeZone,
          calendar: 'iso8601',
          numberingSystem: 'latn',
          hourCycle: 'h23',
          year: 'numeric',
          month: '2-digit',
          day: '2-digit',
          hour: '2-digit',
          minute: '2-digit',
          second: '2-digit',
        })
      }
      
      function zonedParts(epochMs, formatter) {
        const result = {}
        for (const part of formatter.formatToParts(new Date(epochMs))) {
          if (part.type === 'literal') continue
          result[part.type] = Number(part.value)
        }
        return {
          year: result.year,
          month: result.month,
          day: result.day,
          hour: result.hour === 24 ? 0 : result.hour,
          minute: result.minute,
          second: result.second,
        }
      }
      
      function localPartsOrdinal(parts) {
        return Date.UTC(parts.year, parts.month - 1, parts.day, parts.hour, parts.minute, parts.second)
      }
      
      function zonedDateTimeToEpoch(parts, formatter) {
        const wanted = localPartsOrdinal(parts)
        let guess = wanted
      
        for (let iteration = 0; iteration < 5; iteration += 1) {
          const observed = zonedParts(guess, formatter)
          const difference = localPartsOrdinal(observed) - wanted
          if (difference === 0) return guess
          guess -= difference
        }
      
        const observed = zonedParts(guess, formatter)
        return localPartsOrdinal(observed) === wanted ? guess : null
      }
      
      function intervalContains(secondOfDay, start, end) {
        if (start < end) return secondOfDay >= start && secondOfDay < end
        return secondOfDay >= start || secondOfDay < end
      }
      
      function coverageIsComplete(periods) {
        const events = []
        for (const period of periods) {
          if (period.start < period.end) {
            events.push([period.start, 1], [period.end, -1])
          } else {
            events.push([0, 1], [period.end, -1], [period.start, 1], [DAY_SECONDS, -1])
          }
        }
        events.sort((left, right) => left[0] - right[0] || left[1] - right[1])
      
        let active = 0
        let cursor = 0
        for (let index = 0; index < events.length;) {
          const position = events[index][0]
          if (position > cursor && active !== 1) return false
          while (index < events.length && events[index][0] === position) {
            active += events[index][1]
            index += 1
          }
          cursor = position
        }
        return cursor === DAY_SECONDS && active === 0
      }
      
      function periodValue(candidate) {
        const start = parseClock(candidate?.start)
        const end = parseClock(candidate?.end)
        if (start == null || end == null || start === end) return null
        if (!VALID_SEGMENTS.has(candidate.segment)) return null
        if (typeof candidate.tier !== 'string' || candidate.tier.trim() === '') return null
        return { start, end, segment: candidate.segment, tier: candidate.tier }
      }
      
      function segmentValue(candidate) {
        if (!VALID_SEGMENTS.has(candidate?.segment)) return null
        if (typeof candidate.tier !== 'string' || candidate.tier.trim() === '') return null
        return { segment: candidate.segment, tier: candidate.tier }
      }
      
      function dateKey(parts) {
        return [parts.year, parts.month, parts.day]
          .map((value, index) => String(value).padStart(index === 0 ? 4 : 2, '0'))
          .join('-')
      }
      
      function isDateKey(value) {
        if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
        const [year, month, day] = value.split('-').map(Number)
        return dateKey(ordinalToDateParts(datePartsToOrdinal({ year, month, day }))) === value
      }
      
      function isoWeekday(parts) {
        const day = new Date(Date.UTC(parts.year, parts.month - 1, parts.day)).getUTCDay()
        return day === 0 ? 7 : day
      }
      
      function validateConfig(config) {
        if (config == null) return { ok: false, state: unavailable('unconfigured') }
        if (typeof config !== 'object' || Array.isArray(config)) {
          return { ok: false, state: unavailable('invalid', 'configuration must be an object') }
        }
        if (config.schemaVersion !== 1 && config.schemaVersion !== 2) {
          return { ok: false, state: unavailable('invalid', 'unsupported schemaVersion') }
        }
        if (typeof config.version !== 'string' || config.version.trim() === '') {
          return { ok: false, state: unavailable('invalid', 'version is required') }
        }
        if (!VALID_AUTHORITIES.has(config.authority)) {
          return { ok: false, state: unavailable('invalid', 'authority must be approved or estimate') }
        }
        if (typeof config.timeZone !== 'string' || config.timeZone.trim() === '') {
          return { ok: false, state: unavailable('invalid', 'timeZone is required') }
        }
        try {
          createFormatter(config.timeZone).format(new Date(0))
        } catch {
          return { ok: false, state: unavailable('invalid', 'timeZone is not supported') }
        }
        if (config.boundary !== '[start,end)') {
          return { ok: false, state: unavailable('invalid', 'boundary must be [start,end)') }
        }
        const effectiveFrom = Date.parse(config.effectiveFrom)
        const expiresAt = Date.parse(config.expiresAt)
        if (!Number.isFinite(effectiveFrom) || !Number.isFinite(expiresAt) || effectiveFrom >= expiresAt) {
          return { ok: false, state: unavailable('invalid', 'effectiveFrom/expiresAt are invalid') }
        }
        if (config.authority === 'approved') {
          if (typeof config.source?.approvedBy !== 'string' || config.source.approvedBy.trim() === '') {
            return { ok: false, state: unavailable('invalid', 'approved source requires approvedBy') }
          }
          if (!Number.isFinite(Date.parse(config.source?.approvedAt))) {
            return { ok: false, state: unavailable('invalid', 'approved source requires approvedAt') }
          }
        }
        if (config.schemaVersion === 1) {
          if (!Array.isArray(config.periods) || config.periods.length < 2) {
            return { ok: false, state: unavailable('invalid', 'at least two periods are required') }
          }
          const periods = config.periods.map(periodValue)
          if (periods.some((period) => period == null)) {
            return { ok: false, state: unavailable('invalid', 'periods are invalid') }
          }
          if (!coverageIsComplete(periods)) {
            return { ok: false, state: unavailable('invalid', 'periods must cover each day exactly once') }
          }
          return { ok: true, schemaVersion: 1, config, effectiveFrom, expiresAt, periods }
        }
      
        const fallback = segmentValue(config.default)
        const activeWeekdays = config.schedule?.activeWeekdays
        const excludedDates = config.schedule?.excludedDates
        const candidates = config.schedule?.periods
        if (!fallback) return { ok: false, state: unavailable('invalid', 'default segment is invalid') }
        if (!Array.isArray(activeWeekdays) || activeWeekdays.length === 0 ||
            new Set(activeWeekdays).size !== activeWeekdays.length ||
            activeWeekdays.some((day) => !Number.isInteger(day) || !VALID_WEEKDAYS.has(day))) {
          return { ok: false, state: unavailable('invalid', 'activeWeekdays must contain unique ISO weekdays') }
        }
        if (!Array.isArray(excludedDates) || new Set(excludedDates).size !== excludedDates.length ||
            excludedDates.some((date) => !isDateKey(date))) {
          return { ok: false, state: unavailable('invalid', 'excludedDates must contain unique ISO dates') }
        }
        if (!Array.isArray(candidates) || candidates.length === 0) {
          return { ok: false, state: unavailable('invalid', 'schedule periods are required') }
        }
        const periods = candidates.map(periodValue)
        if (periods.some((period) => period == null || period.start >= period.end)) {
          return { ok: false, state: unavailable('invalid', 'schema v2 periods must not cross midnight') }
        }
        const ordered = periods.slice().sort((left, right) => left.start - right.start)
        if (ordered.some((period, index) => index > 0 && ordered[index - 1].end > period.start)) {
          return { ok: false, state: unavailable('invalid', 'schedule periods must not overlap') }
        }
        return {
          ok: true,
          schemaVersion: 2,
          config,
          effectiveFrom,
          expiresAt,
          fallback,
          activeWeekdays: new Set(activeWeekdays),
          excludedDates: new Set(excludedDates),
          periods: ordered,
        }
      }
      
      function resolvePeriod(validated, parts) {
        const secondOfDay = parts.hour * 3600 + parts.minute * 60 + parts.second
        if (validated.schemaVersion === 1) {
          return validated.periods.find((candidate) => intervalContains(secondOfDay, candidate.start, candidate.end))
        }
        const activeDate = validated.activeWeekdays.has(isoWeekday(parts)) &&
          !validated.excludedDates.has(dateKey(parts))
        if (!activeDate) return validated.fallback
        return validated.periods.find((candidate) => intervalContains(secondOfDay, candidate.start, candidate.end)) ?? validated.fallback
      }
      
      function periodBoundaryEpoch(period, parts, secondOfDay, formatter) {
        const endOnNextDay = period.start > period.end && secondOfDay >= period.start
        const date = ordinalToDateParts(datePartsToOrdinal(parts) + (endOnNextDay ? 1 : 0))
        return zonedDateTimeToEpoch({
          ...date,
          hour: Math.floor(period.end / 3600),
          minute: Math.floor((period.end % 3600) / 60),
          second: period.end % 60,
        }, formatter)
      }
      
      function nextV2Switch(validated, nowMs, parts, formatter, currentPeriod) {
        const firstOrdinal = datePartsToOrdinal(parts)
        for (let offset = 0; offset <= 370; offset += 1) {
          const date = ordinalToDateParts(firstOrdinal + offset)
          const seconds = new Set([0])
          for (const period of validated.periods) {
            seconds.add(period.start)
            seconds.add(period.end)
          }
          for (const second of [...seconds].sort((left, right) => left - right)) {
            const epoch = zonedDateTimeToEpoch({
              ...date,
              hour: Math.floor(second / 3600),
              minute: Math.floor((second % 3600) / 60),
              second: second % 60,
            }, formatter)
            if (epoch == null || epoch <= nowMs || epoch >= validated.expiresAt) continue
            const candidate = resolvePeriod(validated, zonedParts(epoch, formatter))
            if (candidate.segment !== currentPeriod.segment || candidate.tier !== currentPeriod.tier) return epoch
          }
        }
        return null
      }
      
      function evaluateSchedule(config, nowInput = Date.now()) {
        const validated = validateConfig(config)
        if (!validated.ok) return validated.state
      
        const nowMs = typeof nowInput === 'number' ? nowInput : new Date(nowInput).getTime()
        if (!Number.isFinite(nowMs)) return unavailable('invalid', 'current time is invalid')
        if (nowMs < validated.effectiveFrom) return unavailable('not_effective')
        if (nowMs >= validated.expiresAt) return unavailable('stale')
      
        const formatter = createFormatter(config.timeZone)
        const parts = zonedParts(nowMs, formatter)
        const secondOfDay = parts.hour * 3600 + parts.minute * 60 + parts.second
        const period = resolvePeriod(validated, parts)
        if (!period) return unavailable('invalid', 'no period matched current time')
      
        const nextSwitchAt = validated.schemaVersion === 1
          ? periodBoundaryEpoch(period, parts, secondOfDay, formatter)
          : nextV2Switch(validated, nowMs, parts, formatter, period)
        if (nextSwitchAt == null || nextSwitchAt <= nowMs) {
          return unavailable('invalid', 'next boundary cannot be represented in the configured time zone')
        }
      
        return {
          available: true,
          reason: null,
          detail: null,
          segment: period.segment,
          tier: period.tier,
          remainingMs: nextSwitchAt - nowMs,
          nextSwitchAt,
          authority: config.authority,
          timeZone: config.timeZone,
          version: config.version,
          source: config.source ?? null,
        }
      }
      
      function formatCountdown(milliseconds) {
        if (!Number.isFinite(milliseconds) || milliseconds < 0) return '--:--:--'
        const totalSeconds = Math.ceil(milliseconds / 1000)
        const hours = Math.floor(totalSeconds / 3600)
        const minutes = Math.floor((totalSeconds % 3600) / 60)
        const seconds = totalSeconds % 60
        return [hours, minutes, seconds].map((value) => String(value).padStart(2, '0')).join(':')
      }
      
      module.exports = {
        DAY_SECONDS,
        evaluateSchedule,
        formatCountdown,
        parseClock,
        validateConfig,
      }
      
    })(scheduleModule, scheduleModule.exports)

    const approvedConfigModule = { exports: {
  "schemaVersion": 2,
  "version": "deepseek-pricing-2026-09-20+cn-holidays-2026-bjt",
  "authority": "approved",
  "source": {
    "label": "DeepSeek Models & Pricing；国务院办公厅 2026 年部分节假日安排",
    "urls": [
      "https://api-docs.deepseek.com/quick_start/pricing/",
      "https://www.gov.cn/zhengce/content/202511/content_7047090.htm"
    ],
    "approvedBy": "workspace owner",
    "approvedAt": "2026-09-20T08:32:09.959Z"
  },
  "effectiveFrom": "2026-09-10T04:00:00Z",
  "expiresAt": "2026-12-31T16:00:00Z",
  "timeZone": "Asia/Shanghai",
  "boundary": "[start,end)",
  "default": {
    "segment": "off_peak",
    "tier": "OFF_PEAK"
  },
  "schedule": {
    "activeWeekdays": [1, 2, 3, 4, 5],
    "excludedDates": [
      "2026-01-01",
      "2026-01-02",
      "2026-01-03",
      "2026-02-15",
      "2026-02-16",
      "2026-02-17",
      "2026-02-18",
      "2026-02-19",
      "2026-02-20",
      "2026-02-21",
      "2026-02-22",
      "2026-02-23",
      "2026-04-04",
      "2026-04-05",
      "2026-04-06",
      "2026-05-01",
      "2026-05-02",
      "2026-05-03",
      "2026-05-04",
      "2026-05-05",
      "2026-06-19",
      "2026-06-20",
      "2026-06-21",
      "2026-09-25",
      "2026-09-26",
      "2026-09-27",
      "2026-10-01",
      "2026-10-02",
      "2026-10-03",
      "2026-10-04",
      "2026-10-05",
      "2026-10-06",
      "2026-10-07"
    ],
    "periods": [
      {
        "start": "09:00",
        "end": "12:00",
        "segment": "peak",
        "tier": "PEAK"
      },
      {
        "start": "14:00",
        "end": "18:00",
        "segment": "peak",
        "tier": "PEAK"
      }
    ]
  }
} }

    const pluginModule = { exports: {} }
    ;((module, exports, localRequire) => {
      'use strict'
      
      const React = localRequire('react')
      const { evaluateSchedule, formatCountdown } = localRequire('./schedule.cjs')
      const approvedDefaultConfig = localRequire('./approved-2026.json')
      
      const CONFIG_KEY = '__DSH_DEEPSEEK_OFFPEAK_CONFIG__'
      const CONFIG_EVENT = 'dsh:deepseek-offpeak-config'
      const STYLE_ID = '@steelai/dsh-client-deepseek-offpeak/badge.css'
      
      const copy = {
        peak: '峰段',
        off_peak: '谷段',
        unknown: '未知',
        unconfigured: '未配置',
        invalid: '配置无效',
        stale: '数据过期',
        not_effective: '尚未生效',
      }
      
      function readRuntimeConfig() {
        if (typeof window === 'undefined') return approvedDefaultConfig
        return Object.prototype.hasOwnProperty.call(window, CONFIG_KEY)
          ? window[CONFIG_KEY]
          : approvedDefaultConfig
      }
      
      function useScheduleState() {
        const [config, setConfig] = React.useState(readRuntimeConfig)
        const [now, setNow] = React.useState(() => Date.now())
      
        React.useEffect(() => {
          const tick = window.setInterval(() => setNow(Date.now()), 250)
          const update = (event) => {
            setConfig(event.detail === undefined ? readRuntimeConfig() : event.detail)
            setNow(Date.now())
          }
          window.addEventListener(CONFIG_EVENT, update)
          return () => {
            window.clearInterval(tick)
            window.removeEventListener(CONFIG_EVENT, update)
          }
        }, [])
      
        return evaluateSchedule(config, now)
      }
      
      function tooltipFor(state) {
        if (!state.available) {
          const base = `DeepSeek 峰谷时段：${copy[state.reason] ?? copy.unknown}`
          return state.detail ? `${base}（${state.detail}）` : base
        }
        const authority = state.authority === 'approved' ? '已批准来源' : '非官方推算'
        const source = state.source?.label ? `；来源：${state.source.label}` : ''
        return `DeepSeek ${copy[state.segment]}；档位：${state.tier}；时区：${state.timeZone}；版本：${state.version}；${authority}${source}`
      }
      
      function DeepSeekOffPeakBadge() {
        const state = useScheduleState()
        if (!state.available) {
          return React.createElement('div', {
            className: 'steelai-dsh-offpeak steelai-dsh-offpeak--unknown',
            role: 'status',
            title: tooltipFor(state),
            'data-state': state.reason,
            'aria-label': `DeepSeek 峰谷时段 ${copy[state.reason] ?? copy.unknown}`,
          },
          React.createElement('span', { className: 'steelai-dsh-offpeak__dot', 'aria-hidden': 'true' }),
          React.createElement('span', null, '峰谷时段'),
          React.createElement('strong', null, copy[state.reason] ?? copy.unknown))
        }
      
        const unofficial = state.authority !== 'approved'
        return React.createElement('div', {
          className: `steelai-dsh-offpeak steelai-dsh-offpeak--${state.segment}`,
          role: 'timer',
          title: tooltipFor(state),
          'data-state': state.segment,
          'data-tier': state.tier,
          'data-authority': state.authority,
          'aria-label': `DeepSeek ${copy[state.segment]}，档位 ${state.tier}，距离切换 ${formatCountdown(state.remainingMs)}${unofficial ? '，非官方推算' : ''}`,
        },
        React.createElement('span', { className: 'steelai-dsh-offpeak__dot', 'aria-hidden': 'true' }),
        React.createElement('span', null, copy[state.segment]),
        React.createElement('strong', { className: 'steelai-dsh-offpeak__countdown' }, formatCountdown(state.remainingMs)),
        React.createElement('code', { className: 'steelai-dsh-offpeak__tier' }, state.tier),
        unofficial ? React.createElement('em', null, '非官方推算') : null)
      }
      
      function ensureStyles() {
        if (document.querySelector(`style[data-plugin-css="${STYLE_ID}"]`)) return () => {}
        const style = document.createElement('style')
        style.dataset.plugin = '@steelai/dsh-client-deepseek-offpeak'
        style.dataset.pluginCss = STYLE_ID
        style.textContent = `
      .steelai-dsh-offpeak{box-sizing:border-box;min-height:28px;display:inline-flex;align-items:center;gap:6px;padding:4px 9px;border:1px solid var(--dsw-alias-border-l1);border-radius:999px;background:var(--dsw-alias-bg-base);color:var(--dsw-alias-label-secondary);font-size:12px;line-height:18px;white-space:nowrap}
      .steelai-dsh-offpeak strong{color:var(--dsw-alias-label-primary);font-weight:600}
      .steelai-dsh-offpeak__dot{width:7px;height:7px;border-radius:50%;background:var(--dsw-alias-label-caption)}
      .steelai-dsh-offpeak--peak .steelai-dsh-offpeak__dot{background:#e68a27}
      .steelai-dsh-offpeak--off_peak .steelai-dsh-offpeak__dot{background:#20a56b}
      .steelai-dsh-offpeak__countdown{font-variant-numeric:tabular-nums}
      .steelai-dsh-offpeak__tier{padding:0 4px;border-radius:4px;background:var(--dsw-alias-interactive-bg-hover);color:inherit;font-size:11px}
      .steelai-dsh-offpeak em{color:var(--dsw-alias-state-warning-primary,#b06a00);font-style:normal}
      `
        document.head.appendChild(style)
        return () => style.remove()
      }
      
      const inject = ['slots']
      
      function apply(ctx) {
        ctx.effect(ensureStyles, 'steelai-deepseek-offpeak: styles')
        ctx.slots.inject('conversation.session.header.actions', () => ctx.slots.register({
          name: 'conversation.session.header.actions',
          id: 'deepseek-offpeak',
          order: -5,
        }, DeepSeekOffPeakBadge))
        ctx.slots.inject('settings.general.item', () => ctx.slots.register({
          name: 'settings.general.item',
          id: 'deepseek-offpeak',
          order: -20,
        }, DeepSeekOffPeakBadge))
      }
      
      module.exports = {
        CONFIG_EVENT,
        CONFIG_KEY,
        DeepSeekOffPeakBadge,
        apply,
        inject,
      }
      
    })(pluginModule, pluginModule.exports, (specifier) => {
      if (specifier === './schedule.cjs') return scheduleModule.exports
      if (specifier === './approved-2026.json') return approvedConfigModule.exports
      return require(specifier)
    })
    return pluginModule.exports
  },
})
