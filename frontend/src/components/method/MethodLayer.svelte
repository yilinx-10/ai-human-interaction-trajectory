<script>
  import { onMount } from 'svelte'
  import { methodData } from '../../stores.js'
  import Timeline from './Timeline.svelte'

  let loading = true
  let error = null

  onMount(async () => {
    if ($methodData !== null) { loading = false; return }
    try {
      const res = await fetch('/data/layer_method.json')
      if (!res.ok) throw new Error(res.statusText)
      const raw = await res.json()
      // Support both GLiNER output {conversations, stats} and legacy flat array
      methodData.set(Array.isArray(raw) ? raw : (raw.conversations ?? []))
    } catch (e) {
      error = e.message
    } finally {
      loading = false
    }
  })
</script>

<div class="layer">
  {#if loading}
    <div class="loading">Loading method timeline…</div>
  {:else if error}
    <div class="error">{error}</div>
  {:else}
    <Timeline data={$methodData} />
  {/if}
</div>

<style>
  .layer { width: 100%; height: 100%; }
</style>
