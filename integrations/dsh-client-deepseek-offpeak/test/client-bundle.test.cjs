'use strict'

const test = require('node:test')
const assert = require('node:assert/strict')
const vm = require('node:vm')
const { readFileSync } = require('node:fs')
const { join } = require('node:path')

const FIXED_NOW = Date.parse('2026-06-01T22:30:00Z')

function approvedConfig(overrides = {}) {
  return {
    schemaVersion: 1,
    version: 'browser-test',
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

function loadBundle(config, includeRuntimeOverride = true, fixedNow = FIXED_NOW) {
  let declaration
  const window = {
    __ModuleLoader__: {
      load(value) {
        declaration = value
      },
    },
    addEventListener() {},
    removeEventListener() {},
    setInterval() { return 1 },
    clearInterval() {},
  }
  if (includeRuntimeOverride) window.__DSH_DEEPSEEK_OFFPEAK_CONFIG__ = config
  class FixedDate extends Date {
    static now() {
      return fixedNow
    }
  }
  const document = {
    querySelector() { return null },
    createElement() {
      return { dataset: {}, remove() {} }
    },
    head: { appendChild() {} },
  }
  const react = {
    createElement(type, props, ...children) {
      return { type, props: props ?? {}, children }
    },
    useEffect() {},
    useState(initial) {
      return [typeof initial === 'function' ? initial() : initial, () => {}]
    },
  }
  const context = vm.createContext({ Date: FixedDate, Intl, console, document, window })
  const bundle = readFileSync(join(__dirname, '..', 'lib', 'client.js'), 'utf8')
  vm.runInContext(bundle, context)
  assert.equal(declaration.id, '@steelai/dsh-client-deepseek-offpeak')
  return declaration.factory((specifier) => {
    if (specifier === 'react') return react
    throw new Error(`unexpected external: ${specifier}`)
  })
}

test('bundle registers both zero-session settings and active-session header surfaces', () => {
  const plugin = loadBundle(undefined)
  const registrations = []
  const ctx = {
    effect(callback) { return callback() },
    slots: {
      inject(_name, callback) { return callback() },
      register(options, component) {
        registrations.push({ options, component })
        return () => {}
      },
    },
  }
  plugin.apply(ctx)
  assert.deepEqual(registrations.map(({ options }) => `${options.name}:${options.id}`), [
    'conversation.session.header.actions:deepseek-offpeak',
    'settings.general.item:deepseek-offpeak',
  ])
})

test('browser component renders an explicit unconfigured state', () => {
  const plugin = loadBundle(undefined)
  const tree = plugin.DeepSeekOffPeakBadge()
  assert.equal(tree.props.role, 'status')
  assert.equal(tree.props['data-state'], 'unconfigured')
  assert.match(tree.props['aria-label'], /未配置/)
})

test('browser component renders configured segment, countdown role, and tier', () => {
  const plugin = loadBundle(approvedConfig())
  const tree = plugin.DeepSeekOffPeakBadge()
  assert.equal(tree.props.role, 'timer')
  assert.equal(tree.props['data-state'], 'off_peak')
  assert.equal(tree.props['data-tier'], 'TIER_B')
  assert.equal(tree.props['data-authority'], 'approved')
  assert.match(tree.props['aria-label'], /谷段/)
  assert.match(tree.props['aria-label'], /TIER_B/)
})

test('browser component loads the persisted approved snapshot when no runtime override exists', () => {
  const plugin = loadBundle(undefined, false, Date.parse('2026-09-20T02:00:00Z'))
  const tree = plugin.DeepSeekOffPeakBadge()
  assert.equal(tree.props.role, 'timer')
  assert.equal(tree.props['data-state'], 'off_peak')
  assert.equal(tree.props['data-tier'], 'OFF_PEAK')
  assert.equal(tree.props['data-authority'], 'approved')
})
