<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
const tree = ref<any[]>([])
const saving = ref(false)
const notice = ref('')
const errors = ref<string[]>([])

async function load() { tree.value = await api('/bom/tree') }

function fmtErr(raw: string): string[] {
  try {
    const d = JSON.parse(raw).detail
    const arr = Array.isArray(d) ? d : [d]
    return arr.map((x: any) => (typeof x === 'string' ? x : x.msg || JSON.stringify(x)))
  } catch { return [raw] }
}

async function save() {
  notice.value = ''; errors.value = []
  const lines = tree.value.flatMap((d: any) =>
    d.children.map((c: any) => ({
      dish_id: d.dish_id, ingredient_id: c.ingredient_id, qty_per_portion: Number(c.qty),
    })))
  saving.value = true
  try {
    const res = await api('/bom', { method: 'PUT', body: JSON.stringify({ lines }) })
    notice.value = `已保存：${res.rewritten_runs.length} 张有效备料单与缺料贴已按新用量重写，库存结存未变`
    await load()
  } catch (e: any) {
    errors.value = fmtErr(e?.message || String(e))
  } finally { saving.value = false }
}
onMounted(load)
</script>
<template>
  <h1>BOM 树</h1>
  <p class="sub">菜品用料树 · 直接改用量，保存即重写当前备料单与缺料贴（不做出库，库存结存不变）</p>
  <div class="kp-bom-tree" style="max-width:460px">
    <h2>菜品 / BOM</h2>
    <div v-for="d in tree" :key="d.code" class="kp-dish-node">
      <strong>{{ d.dish }}</strong>
      <span style="font-size:0.7rem;color:#8a8078">{{ d.code }}</span>
      <ul>
        <li v-for="c in d.children" :key="c.ingredient_id">
          {{ c.ingredient }} ·
          <input v-model.number="c.qty" type="number" min="0" step="0.001" class="kp-qty-input" />
          {{ c.unit }} / 份
        </li>
      </ul>
    </div>
  </div>
  <div style="margin-top:0.75rem;display:flex;align-items:center;gap:0.6rem;flex-wrap:wrap">
    <button class="btn" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存用量' }}</button>
    <span v-if="notice" class="badge badge-ok">{{ notice }}</span>
  </div>
  <div v-if="errors.length" class="card" style="max-width:460px;margin-top:0.6rem">
    <span class="badge badge-bad">保存被拒绝：树 / 备料单 / 缺料贴均未改动</span>
    <ul style="margin:0.5rem 0 0;padding-left:1.1rem;font-size:0.8rem">
      <li v-for="(e, i) in errors" :key="i">{{ e }}</li>
    </ul>
  </div>
</template>
