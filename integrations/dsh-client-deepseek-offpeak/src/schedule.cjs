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
