# DSH DeepSeek 峰谷时段客户端插件

这是一个纯展示型 DSH Web 客户端插件。它在会话标题栏和“设置 → 常规”中显示当前峰段/谷段、下一次切换倒计时和配置提供的计费档位枚举。插件不读取账号、额度、账单或凭据，也不代理 API 请求。

## 已批准数据源与持久配置

项目负责人于 2026-09-20 明确批准以下来源作为唯一真源：

- DeepSeek 官方 [Models & Pricing](https://api-docs.deepseek.com/quick_start/pricing/)：峰段为周一至周五 UTC `01:00–04:00` 与 `06:00–10:00`，换算为北京时间 `09:00–12:00` 与 `14:00–18:00`；中国法定节假日除外，其余时间为谷段。
- 国务院办公厅 [2026 年部分节假日安排](https://www.gov.cn/zhengce/content/202511/content_7047090.htm)：提供 2026 年中国法定节假日排除日期。

审核快照保存在 `config/approved-2026.json` 并编入浏览器产物，因此刷新和重启后仍然生效。判定时区为 `Asia/Shanghai`，节假日日期也按北京时间解释。该快照在北京时间 2027-01-01 00:00 到期；到期后立即显示“数据过期”，不得推断或沿用 2027 年规则。国务院公告中的调休上班日仍是周末；DeepSeek 明确说明周末全天谷段，因此不会把调休周末改成峰段。

## 可选运行时覆盖

部署方仍可在插件执行前把新一版已审核配置写入 `window.__DSH_DEEPSEEK_OFFPEAK_CONFIG__`。显式写入 `null` 会触发“未配置”，不会回退到内置快照。

运行中替换配置后，分发 `dsh:deepseek-offpeak-config` 事件即可立即重算：

```js
window.__DSH_DEEPSEEK_OFFPEAK_CONFIG__ = nextApprovedConfig
window.dispatchEvent(new CustomEvent('dsh:deepseek-offpeak-config', {
  detail: nextApprovedConfig,
}))
```

配置契约：

```ts
interface DeepSeekOffPeakConfigV2 {
  schemaVersion: 2
  version: string
  authority: 'approved' | 'estimate'
  source?: {
    label?: string
    urls?: string[]
    approvedBy?: string
    approvedAt?: string // ISO 8601；authority=approved 时必填
  }
  effectiveFrom: string // ISO 8601
  expiresAt: string // ISO 8601
  timeZone: string // IANA 时区，以来源官方口径为准
  boundary: '[start,end)'
  default: { segment: 'peak' | 'off_peak'; tier: string }
  schedule: {
    activeWeekdays: number[] // ISO 周一=1，周日=7
    excludedDates: string[] // 配置时区内的 YYYY-MM-DD
    periods: Array<{
      start: string // HH:mm 或 HH:mm:ss
      end: string
      segment: 'peak' | 'off_peak'
      tier: string // 仅显示枚举/符号，不解释为折扣比例
    }>
  }
}
```

schema v2 的 `schedule.periods` 不能重叠或跨零点；未命中的时间、非活动星期和排除日期都使用 `default`。开始时刻包含、结束时刻不包含。判定与倒计时均使用配置中的 IANA 时区，而不是浏览器本地时区。旧的 schema v1（日内完整覆盖）仍兼容，但不适合表达当前官方周规则。

## 权威性与失效策略

- `authority: approved` 必须同时提供 `approvedBy` 和合法的 `approvedAt`；当前内置快照记录了本任务中项目负责人的明确批准。
- `authority: estimate` 会在 GUI 中持续标注“非官方推算”。
- `effectiveFrom` 之前显示“尚未生效”；达到 `expiresAt` 后立即显示“数据过期”，不沿用旧时段。
- schema、时区、日期、覆盖关系或档位不合法时显示“配置无效”；缺少入口时显示“未配置”。所有失败态的 segment/tier 均降级为 `unknown`/`UNKNOWN`。

## 构建与测试

```powershell
node scripts/build.mjs
node scripts/build.mjs --check
node --test test/*.test.cjs
```

`lib/client.js` 是 DSH 浏览器模块表读取的构建产物。源文件变更后必须重建；`npm test` 会先验证构建产物未过期，再运行边界、跨零点、时区偏移、缺失与过期测试。

## DSH 0.1.1-rc.2 装载

把本目录作为本地依赖加入 Web profile，并把 `deployment/cordis.patch.yml` 的客户端行合并到该 profile 的 `cordis.patch.yml`：

```yaml
- insert:
    - id: steelai-deepseek-offpeak
      name: '@steelai/dsh-client-deepseek-offpeak'
```

生产 profile 不运行 `dev:web` watcher，因此安装/构建后需要重启 DSH Web 进程并刷新现有 URL。此插件不要求修改 `apps/web` 外壳或任何 DSH plain package。

### 运营 profile 集成

运营控制面已将本插件加入精确 allowlist。`launch-operational-console.ps1 -Action Validate` 会同时检查：

- profile 只有 allowlist 中的客户端依赖；
- 依赖来自本目录，而不是同名远程包；
- profile patch 与 `deployment/cordis.patch.yml` 的 SHA-256 完全一致；
- 已安装的 `lib/client.js` 与本地审核构建完全一致。

正式 `51828` Web profile 会加载已批准的 2026 快照；正常状态应显示“峰段”或“谷段”、倒计时和 `PEAK`/`OFF_PEAK` 档位。若显式覆盖为空则显示“未配置”，配置不合法显示“配置无效”，2027 年起显示“数据过期”。
