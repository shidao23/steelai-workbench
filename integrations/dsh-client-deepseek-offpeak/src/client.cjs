'use strict'

const React = require('react')
const { evaluateSchedule, formatCountdown } = require('./schedule.cjs')
const approvedDefaultConfig = require('./approved-2026.json')

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
