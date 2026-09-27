import { readFile, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const schedule = await readFile(join(root, 'src', 'schedule.cjs'), 'utf8')
const client = await readFile(join(root, 'src', 'client.cjs'), 'utf8')
const approvedConfig = await readFile(join(root, 'config', 'approved-2026.json'), 'utf8')
const outputPath = join(root, 'lib', 'client.js')

const indent = (value, spaces) => value.split('\n').map((line) => `${' '.repeat(spaces)}${line}`).join('\n')
const bundle = `window.__ModuleLoader__.load({
  id: '@steelai/dsh-client-deepseek-offpeak',
  factory: (require) => {
    const scheduleModule = { exports: {} }
    ;((module, exports) => {
${indent(schedule, 6)}
    })(scheduleModule, scheduleModule.exports)

    const approvedConfigModule = { exports: ${approvedConfig.trim()} }

    const pluginModule = { exports: {} }
    ;((module, exports, localRequire) => {
${indent(client, 6).replace(/require\(/g, 'localRequire(')}
    })(pluginModule, pluginModule.exports, (specifier) => {
      if (specifier === './schedule.cjs') return scheduleModule.exports
      if (specifier === './approved-2026.json') return approvedConfigModule.exports
      return require(specifier)
    })
    return pluginModule.exports
  },
})
`

if (process.argv.includes('--check')) {
  const existing = await readFile(outputPath, 'utf8').catch(() => '')
  if (existing !== bundle) {
    console.error('lib/client.js is stale; run npm run build')
    process.exitCode = 1
  }
} else {
  await writeFile(outputPath, bundle)
}
