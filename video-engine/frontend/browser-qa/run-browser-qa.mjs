import { createHash } from 'node:crypto'
import { copyFile, mkdir, readFile, readdir, writeFile } from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { spawnSync } from 'node:child_process'
import process from 'node:process'
import { createRequire } from 'node:module'
import { chromium } from '@playwright/test'

const require = createRequire(import.meta.url)
const playwrightPackage = require('@playwright/test/package.json')
const ROOT = process.cwd()
const QA = path.join(ROOT, 'browser-qa')
const RESULT_JSON = path.join(QA, 'playwright-results.json')
const REPORT_JSON = path.join(QA, 'browser-qa-report.json')
const CONTENT = path.join(QA, 'artifacts', 'sha256')

function stableValue(value) {
  if (Array.isArray(value)) return value.map(stableValue)
  if (value && typeof value === 'object') {
    const out = {}
    for (const key of Object.keys(value).sort()) out[key] = stableValue(value[key])
    return out
  }
  return value
}

function stableJson(value) {
  return JSON.stringify(stableValue(value))
}

async function readStdin() {
  let raw = ''
  for await (const chunk of process.stdin) raw += chunk
  if (!raw.trim()) throw new Error('Browser QA request JSON is required on stdin')
  return JSON.parse(raw)
}

function normalizeLoopback(value) {
  const url = new URL(value)
  if (url.protocol !== 'http:') throw new Error('Browser QA URL must use http')
  if (!['127.0.0.1', 'localhost'].includes(url.hostname)) {
    throw new Error('Browser QA URL must remain loopback-only')
  }
  if (!['5173', '8760'].includes(url.port)) {
    throw new Error('Browser QA URL port is not allowlisted')
  }
  if (url.username || url.password || url.search || url.hash) {
    throw new Error('Browser QA URL contains forbidden components')
  }
  url.hostname = '127.0.0.1'
  return url.toString()
}

function flattenSpecs(suites, out = []) {
  for (const suite of suites || []) {
    for (const spec of suite.specs || []) {
      for (const item of spec.tests || []) {
        const result = (item.results || []).at(-1) || {}
        out.push({
          title: spec.title,
          project: item.projectName || '',
          status: result.status || 'unknown',
          duration_ms: result.duration || 0,
          errors: (result.errors || []).map((error) => error.message || String(error)),
        })
      }
    }
    flattenSpecs(suite.suites, out)
  }
  return out
}

function classifyFailures(assertions) {
  const classes = new Set()
  for (const item of assertions.filter((row) => row.status !== 'passed')) {
    const text = (item.title + ' ' + item.errors.join(' ')).toLowerCase()
    if (text.includes('axe') || text.includes('accessibility')) classes.add('ACCESSIBILITY_REGRESSION')
    else if (text.includes('network')) classes.add('NETWORK_FAILURE')
    else if (text.includes('console')) classes.add('CONSOLE_FAILURE')
    else if (text.includes('responsive') || text.includes('layout')) classes.add('VISUAL_REGRESSION')
    else classes.add('DETERMINISTIC_FAILURE')
  }
  return [...classes]
}

async function contentAddress(root) {
  const refs = []
  async function walk(dir) {
    let entries
    try {
      entries = await readdir(dir, { withFileTypes: true })
    } catch {
      return
    }
    for (const entry of entries) {
      const full = path.join(dir, entry.name)
      if (entry.isDirectory()) {
        await walk(full)
        continue
      }
      if (!entry.isFile()) continue
      const raw = await readFile(full)
      const digest = createHash('sha256').update(raw).digest('hex')
      const ext = path.extname(entry.name).toLowerCase()
      await mkdir(CONTENT, { recursive: true })
      const target = path.join(CONTENT, digest + ext)
      await copyFile(full, target)
      refs.push({
        source: path.relative(ROOT, full),
        artifact_ref: 'artifact:browser-qa/sha256/' + digest + ext,
        sha256: digest,
        size_bytes: raw.length,
      })
    }
  }
  await walk(root)
  return refs.sort((a, b) => a.artifact_ref.localeCompare(b.artifact_ref))
}

const started = performance.now()
const request = await readStdin()
const authorizedUrl = normalizeLoopback(request.authorized_url)
const allowedOperations = new Set(['functional', 'accessibility', 'aria', 'all'])
const operation = String(request.operation || 'all')
if (!allowedOperations.has(operation)) throw new Error('Browser QA operation is not allowlisted')
const scenarios = Array.isArray(request.scenario_ids) ? request.scenario_ids : []
if (scenarios.length > 32) throw new Error('Too many Browser QA scenarios')

const cli = path.join(ROOT, 'node_modules', '@playwright', 'test', 'cli.js')
const args = [cli, 'test', '--config=playwright.config.mjs']
if (request.viewport === 'desktop') args.push('--project=chromium-desktop')
if (request.viewport === 'desktop-narrow') args.push('--project=chromium-desktop-narrow')
if (operation !== 'all') args.push('--grep', '^\\[' + operation + ':')
if (scenarios.length) args.push('--grep', scenarios.join('|'))

const env = {
  ...process.env,
  BROWSER_QA_BASE_URL: authorizedUrl,
}
const executed = spawnSync(process.execPath, args, {
  cwd: ROOT,
  env,
  encoding: 'utf8',
  maxBuffer: 16 * 1024 * 1024,
})

let playwrightResults = { suites: [] }
try {
  playwrightResults = JSON.parse(await readFile(RESULT_JSON, 'utf8'))
} catch {}
const assertions = flattenSpecs(playwrightResults.suites)

let browserVersion = 'unavailable'
try {
  const browser = await chromium.launch({ headless: true })
  browserVersion = browser.version()
  await browser.close()
} catch {}

const evidence = [
  ...(await contentAddress(path.join(QA, 'test-results'))),
  ...(await contentAddress(path.join(QA, 'html-report'))),
]
const failedAssertions = assertions.filter((row) => row.status !== 'passed')
const failed = executed.status !== 0 || failedAssertions.length > 0
const errorText = failedAssertions.flatMap((row) => row.errors)
const body = {
  schema: 'BrowserQAReport/v1',
  authority: 'NONE',
  mission_id: String(request.mission_id || ''),
  plan_id: String(request.plan_id || ''),
  task_id: String(request.task_id || ''),
  candidate_sha: String(request.candidate_sha || ''),
  frontend_build_sha: String(request.frontend_build_sha || ''),
  scenario_id: scenarios.length ? scenarios.join(',') : 'configured-suite',
  scenario_version: '1',
  browser_name: 'chromium',
  browser_version: browserVersion,
  playwright_version: playwrightPackage.version,
  node_version: process.version,
  os_environment: {
    platform: process.platform,
    release: os.release(),
    arch: process.arch,
  },
  viewport: request.viewport || 'both',
  device_scale_factor: 1,
  functional_assertions: assertions.filter((row) => row.title.includes('[functional:')),
  aria_assertions: assertions.filter((row) => row.title.includes('[aria:')),
  accessibility_findings: assertions.filter((row) => row.title.includes('[accessibility:')),
  console_errors: errorText.filter((text) => text.toLowerCase().includes('console')),
  network_failures: errorText.filter((text) => text.toLowerCase().includes('network')),
  visual_baseline_ref: null,
  actual_screenshot_ref: evidence.find((row) => row.source.endsWith('.png'))?.artifact_ref || null,
  visual_diff_ref: null,
  trace_ref: evidence.find((row) => row.source.endsWith('trace.zip'))?.artifact_ref || null,
  html_report_ref: evidence.find((row) => row.source.endsWith('html-report/index.html'))?.artifact_ref || null,
  mcp_exploration_used: false,
  vision_fallback_used: false,
  result: failed ? 'FAIL' : 'PASS',
  failure_classes: classifyFailures(assertions),
  evidence_refs: evidence.map((row) => row.artifact_ref),
  evidence_manifest: evidence,
  metrics: {
    browser_qa_wall_ms: Math.round(performance.now() - started),
    assertion_count: assertions.length,
    failed_assertion_count: failedAssertions.length,
  },
}
const digest = createHash('sha256').update(stableJson(body)).digest('hex')
const report = { ...body, content_sha256: digest }
await mkdir(path.dirname(REPORT_JSON), { recursive: true })
await writeFile(REPORT_JSON, JSON.stringify(report, null, 2) + '\n')
await mkdir(CONTENT, { recursive: true })
await writeFile(path.join(CONTENT, digest + '.json'), JSON.stringify(report, null, 2) + '\n')
process.stdout.write(JSON.stringify(report) + '\n')
if (failed) process.exit(executed.status || 1)
