import path from 'node:path'

import { defineConfig } from '@playwright/test'

function requiredEnvironment(name: string): string {
  const value = process.env[name]
  if (value === undefined) {
    throw new Error(`E2E 测试启动已拒绝：缺少 ${name}。请通过 scripts/test.sh 或 scripts/test.ps1 运行。`)
  }
  return value
}

function isInside(root: string, target: string): boolean {
  const relative = path.relative(root, target)
  return (
    relative !== '' &&
    relative !== '..' &&
    !relative.startsWith(`..${path.sep}`) &&
    !path.isAbsolute(relative)
  )
}

const testRootValue = requiredEnvironment('AI_JOB_COACH_TEST_ROOT')
if (!path.isAbsolute(testRootValue)) {
  throw new Error('E2E 测试启动已拒绝：AI_JOB_COACH_TEST_ROOT 必须是绝对路径。')
}
const testRoot = path.resolve(testRootValue)

const expectedProviders = {
  APP_ENV: 'test',
  LLM_PROVIDER: 'mock',
  PAYMENT_PROVIDER: 'disabled',
  STORAGE_PROVIDER: 'local',
}
for (const [name, expected] of Object.entries(expectedProviders)) {
  if (requiredEnvironment(name) !== expected) {
    throw new Error(`E2E 测试启动已拒绝：${name} 必须为 ${expected}。`)
  }
}

const databaseUrl = requiredEnvironment('DATABASE_URL')
const sqlitePrefix = 'sqlite:///'
if (!databaseUrl.startsWith(sqlitePrefix)) {
  throw new Error('E2E 测试启动已拒绝：DATABASE_URL 必须为临时 SQLite 文件。')
}
const databaseValue = databaseUrl.slice(sqlitePrefix.length)
if (!path.isAbsolute(databaseValue) || !isInside(testRoot, path.resolve(databaseValue))) {
  throw new Error('E2E 测试启动已拒绝：数据库不在隔离测试目录中。')
}

const storageValue = requiredEnvironment('LOCAL_STORAGE_PATH')
if (!path.isAbsolute(storageValue) || !isInside(testRoot, path.resolve(storageValue))) {
  throw new Error('E2E 测试启动已拒绝：上传目录不在隔离测试目录中。')
}

const apiEnvironment = {
  AI_JOB_COACH_TEST_ROOT: testRoot,
  APP_ENV: 'test',
  DATABASE_URL: databaseUrl,
  LOCAL_STORAGE_PATH: storageValue,
  STORAGE_PROVIDER: 'local',
  LLM_PROVIDER: 'mock',
  LLM_API_BASE_URL: '',
  LLM_API_KEY: '',
  LLM_MODEL: '',
  LLM_MODEL_CHEAP: '',
  LLM_MODEL_STRONG: '',
  PAYMENT_PROVIDER: 'disabled',
  JOB_SOURCE_ALLOWED_HOSTS: '',
  DEMO_ADMIN_EMAIL: 'admin@example.test',
  DEMO_ADMIN_PASSWORD: 'ChangeMe123!',
  DEMO_ADVISOR_EMAIL: 'advisor@example.test',
  DEMO_ADVISOR_PASSWORD: 'ChangeMe123!',
  DEMO_USER_EMAIL: 'user@example.test',
  DEMO_USER_PASSWORD: 'ChangeMe123!',
}
const apiPython = process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python'

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  use: { baseURL: 'http://127.0.0.1:5173', trace: 'retain-on-failure' },
  webServer: [
    {
      command: `${apiPython} ../../scripts/run_e2e_api.py`,
      cwd: '../api',
      url: 'http://127.0.0.1:8000/api/health',
      env: apiEnvironment,
      reuseExistingServer: false,
    },
    {
      command: 'npm run dev -- --host 127.0.0.1',
      cwd: '.',
      url: 'http://127.0.0.1:5173',
      reuseExistingServer: false,
    },
  ],
})
