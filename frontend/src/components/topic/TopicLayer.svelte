<script>
  import { onMount } from 'svelte'
  import { topicData } from '../../stores.js'
  import ScatterPlot from './ScatterPlot.svelte'

  let loading = true
  let error = null

  onMount(async () => {
    if ($topicData !== null) { loading = false; return }
    try {
      const res = await fetch('/data/layer_topic.json')
      if (!res.ok) throw new Error(res.statusText)
      topicData.set(await res.json())
    } catch (e) {
      error = e.message
    } finally {
      loading = false
    }
  })
</script>

<div class="layer">
  {#if loading}
    <div class="loading">Loading conversations…</div>
  {:else if error}
    <div class="error">{error}</div>
  {:else}
    <ScatterPlot data={$topicData} />
  {/if}
</div>

<style>
  .layer { width: 100%; height: 100%; }
</style>
