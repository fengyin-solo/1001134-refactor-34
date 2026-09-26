<template>
  <section class="page" data-module="storage">
    <header class="page-head">
      <div>
        <h2>堆存计费管理</h2>
        <p class="page-desc">维护计费单，围绕计费单号、关联箱号、计费周期、堆存天数做登记、筛选与状态流转。金额由服务端统一口径计算。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="toggleCreate">登记计费单</button>
        <button class="btn" type="button" @click="exportRows">导出堆存计费清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form v-if="showCreate" class="create-panel" @submit.prevent="submitCreate">
      <label v-for="field in createFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="createForm[field]" :placeholder="`请输入${field}`" />
      </label>
      <button class="btn primary" type="submit">提交登记</button>
      <button class="btn ghost" type="button" @click="toggleCreate">取消</button>
    </form>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无堆存计费数据，可先登记计费单</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条堆存计费记录</span>
      <span v-if="noticeMessage" class="ok-text">{{ noticeMessage }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>
type StatCard = { label: string; value: string | number }
type ActionResult = { ok: boolean; message: string }

const ENDPOINT = '/api/storage'
const columns = ["计费单号", "关联箱号", "计费周期", "堆存天数", "计费标准", "应收金额", "客户名称", "计费状态", "计费说明"]
const actions = ["生成账单", "确认对账", "开具发票"]
const createFields = ["计费单号", "关联箱号", "计费周期", "堆存天数", "计费标准", "客户名称"]

const rows = ref<Row[]>([])
const total = ref(0)
const stats = ref<StatCard[]>([])
const errorMessage = ref('')
const noticeMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)
const showCreate = ref(false)
const createForm = ref<Record<string, string>>({})

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function toggleCreate() {
  showCreate.value = !showCreate.value
  createForm.value = {}
}

async function parseResult(response: Response, fallback: string): Promise<ActionResult> {
  if (!response.ok) {
    throw new Error(fallback)
  }
  return (await response.json()) as ActionResult
}

async function applyResult(result: ActionResult) {
  if (result.ok) {
    noticeMessage.value = result.message
    await Promise.all([reload(), loadSummary()])
  } else {
    errorMessage.value = result.message
  }
}

async function submitCreate() {
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values: { ...createForm.value } }),
    })
    const result = await parseResult(response, '计费单登记未生效，请稍后重试')
    await applyResult(result)
    if (result.ok) {
      showCreate.value = false
      createForm.value = {}
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '计费单登记失败'
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const result = await parseResult(response, '堆存计费动作未生效，请稍后重试')
    await applyResult(result)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '堆存计费操作失败'
  }
}

async function reload() {
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('计费单列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '堆存计费列表读取失败'
  }
}

async function loadSummary() {
  try {
    const response = await request(`${ENDPOINT}/summary`)
    if (!response.ok) {
      throw new Error('堆存计费汇总读取失败')
    }
    const payload = await response.json()
    stats.value = payload.cards ?? []
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '堆存计费汇总读取失败'
  }
}

onMounted(() => {
  void reload()
  void loadSummary()
})
</script>
