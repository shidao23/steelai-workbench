'use strict'

const test = require('node:test')
const assert = require('node:assert/strict')
const { readFileSync } = require('node:fs')
const { join } = require('node:path')
const {
  evaluateSchedule,
  formatCountdown,
  validateConfig,
} = require('../src/schedule.cjs')

const official2026Config = JSON.parse(readFileSync(join(__dirname, '..', 'config', 'approved-2026.json'), 'utf8'))

function approvedConfig(overrides = {}) {
  return {
    schemaVersion: 1,
    version: 'test-version',
    authority: 'approved',
    source: {
      label: 'test authority',
      approvedBy: 'test approver',
      approvedAt: '2026-01-01T00:00:00Z',
    },
    effectiveFrom: '2026-01-01T00:00:00Z',
    expiresAt: '2027-01-01T00:00:00Z',
    timeZone: 'Asia/Shanghai',
    boundary: '[start,end)',
    periods: [
      { start: '01:00', end: '07:00', segment: 'off_peak', tier: 'TIER_B' },
      { start: '07:00', end: '01:00', segment: 'peak', tier: 'TIER_A' },
    ],
    ...overrides,
  }
}

test('missing source degrades explicitly to unconfigured', () => {
  assert.deepEqual(evaluateSchedule(undefined, Date.UTC(2026, 5, 1)), {
    available: false,
    reason: 'unconfigured',
    detail: undefined,
    segment: 'unknown',
    tier: 'UNKNOWN',
    remainingMs: null,
    nextSwitchAt: null,
    authority: 'unknown',
  })
})

test('expired source degrades to stale and does not reuse a prior period', () => {
  const state = evaluateSchedule(approvedConfig({ expiresAt: '2026-06-01T00:00:00Z' }), '2026-06-01T00:00:00Z')
  assert.equal(state.available, false)
  assert.equal(state.reason, 'stale')
  assert.equal(state.segment, 'unknown')
})

test('future source remains unknown until effectiveFrom', () => {
  const state = evaluateSchedule(approvedConfig({ effectiveFrom: '2026-06-02T00:00:00Z' }), '2026-06-01T00:00:00Z')
  assert.equal(state.available, false)
  assert.equal(state.reason, 'not_effective')
})

test('boundaries are start-inclusive and end-exclusive in the configured time zone', () => {
  const before = evaluateSchedule(approvedConfig(), '2026-06-01T22:59:59.999Z')
  assert.equal(before.segment, 'off_peak')
  assert.equal(before.tier, 'TIER_B')
  assert.equal(before.remainingMs, 1)

  const boundary = evaluateSchedule(approvedConfig(), '2026-06-01T23:00:00.000Z')
  assert.equal(boundary.segment, 'peak')
  assert.equal(boundary.tier, 'TIER_A')
  assert.equal(boundary.remainingMs, 18 * 60 * 60 * 1000)
})

test('cross-midnight periods resolve both sides of midnight and the next switch', () => {
  const beforeMidnight = evaluateSchedule(approvedConfig(), '2026-06-01T15:30:00Z')
  assert.equal(beforeMidnight.segment, 'peak')
  assert.equal(beforeMidnight.nextSwitchAt, Date.parse('2026-06-01T17:00:00Z'))

  const afterMidnight = evaluateSchedule(approvedConfig(), '2026-06-01T16:30:00Z')
  assert.equal(afterMidnight.segment, 'peak')
  assert.equal(afterMidnight.nextSwitchAt, Date.parse('2026-06-01T17:00:00Z'))
})

test('IANA time-zone offset is applied instead of the browser local zone', () => {
  const state = evaluateSchedule(approvedConfig(), '2026-06-01T17:30:00Z')
  assert.equal(state.segment, 'off_peak')
  assert.equal(state.remainingMs, 5.5 * 60 * 60 * 1000)
  assert.equal(state.nextSwitchAt, Date.parse('2026-06-01T23:00:00Z'))
})

test('invalid, overlapping, or incomplete periods fail closed', () => {
  const result = validateConfig(approvedConfig({
    periods: [
      { start: '00:00', end: '12:00', segment: 'peak', tier: 'A' },
      { start: '11:00', end: '23:00', segment: 'off_peak', tier: 'B' },
    ],
  }))
  assert.equal(result.ok, false)
  assert.equal(result.state.reason, 'invalid')
})

test('approved schedules require approval metadata', () => {
  const result = validateConfig(approvedConfig({ source: { label: 'missing approval' } }))
  assert.equal(result.ok, false)
  assert.match(result.state.detail, /approvedBy/)
})

test('estimate schedules are preserved as explicitly unofficial', () => {
  const config = approvedConfig({ authority: 'estimate', source: { label: 'operator estimate' } })
  const state = evaluateSchedule(config, '2026-06-01T18:00:00Z')
  assert.equal(state.available, true)
  assert.equal(state.authority, 'estimate')
})

test('countdown formatting includes the zero state', () => {
  assert.equal(formatCountdown(1), '00:00:01')
  assert.equal(formatCountdown(0), '00:00:00')
  assert.equal(formatCountdown(3_661_000), '01:01:01')
})

test('approved 2026 schedule applies both Beijing-time peak boundaries exactly', () => {
  const beforeFirstPeak = evaluateSchedule(official2026Config, '2026-09-21T00:59:59.999Z')
  assert.equal(beforeFirstPeak.segment, 'off_peak')
  assert.equal(beforeFirstPeak.nextSwitchAt, Date.parse('2026-09-21T01:00:00Z'))
  assert.equal(beforeFirstPeak.remainingMs, 1)

  const firstPeak = evaluateSchedule(official2026Config, '2026-09-21T01:00:00Z')
  assert.equal(firstPeak.segment, 'peak')
  assert.equal(firstPeak.tier, 'PEAK')
  assert.equal(firstPeak.nextSwitchAt, Date.parse('2026-09-21T04:00:00Z'))

  const betweenPeaks = evaluateSchedule(official2026Config, '2026-09-21T04:00:00Z')
  assert.equal(betweenPeaks.segment, 'off_peak')
  assert.equal(betweenPeaks.nextSwitchAt, Date.parse('2026-09-21T06:00:00Z'))

  const secondPeak = evaluateSchedule(official2026Config, '2026-09-21T06:00:00Z')
  assert.equal(secondPeak.segment, 'peak')
  assert.equal(secondPeak.nextSwitchAt, Date.parse('2026-09-21T10:00:00Z'))
})

test('weekends stay off-peak and countdown skips to the next active weekday', () => {
  const state = evaluateSchedule(official2026Config, '2026-09-20T02:00:00Z')
  assert.equal(state.segment, 'off_peak')
  assert.equal(state.nextSwitchAt, Date.parse('2026-09-21T01:00:00Z'))
})

test('approved schedule identifies its calendar and display zone as Beijing time', () => {
  const state = evaluateSchedule(official2026Config, '2026-09-21T01:00:00Z')
  assert.equal(state.timeZone, 'Asia/Shanghai')
  assert.equal(state.segment, 'peak')
})

test('Chinese public-holiday exclusions stay off-peak for the full configured date', () => {
  const state = evaluateSchedule(official2026Config, '2026-09-25T02:00:00Z')
  assert.equal(state.segment, 'off_peak')
  assert.equal(state.nextSwitchAt, Date.parse('2026-09-28T01:00:00Z'))
})

test('schema v2 rejects overlapping periods and invalid holiday dates', () => {
  const overlapping = structuredClone(official2026Config)
  overlapping.schedule.periods[1].start = '03:00'
  assert.equal(validateConfig(overlapping).ok, false)

  const invalidDate = structuredClone(official2026Config)
  invalidDate.schedule.excludedDates.push('2026-02-30')
  assert.equal(validateConfig(invalidDate).ok, false)
})

test('approved snapshot expires at Beijing midnight instead of extending its holiday calendar', () => {
  const state = evaluateSchedule(official2026Config, '2026-12-31T16:00:00Z')
  assert.equal(state.available, false)
  assert.equal(state.reason, 'stale')
  assert.equal(state.segment, 'unknown')
})
